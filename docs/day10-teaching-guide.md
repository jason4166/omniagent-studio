# Day 10 教学讲义：从一份文件到可定位的 Chunks

这份讲义解释 OmniAgent Studio 的 Day 10 文档导入管线。它以概念和运行时过程为主，代码只用于说明关键动作。完整实现请配合文末的源码地图阅读。

本文不包含最终验收练习、工程门禁、Git、学习日志或 Day 11 收尾。

---

## 0. 我们到底要解决什么问题

假设用户向知识库上传三个文件：

- 一份 TXT 售后说明；
- 一份按章节编写的 Markdown 手册；
- 一份两页 PDF 保修指南。

以后 Agent 回答问题时，不能只说“答案来自某个大字符串”。系统至少需要知道：

- 原始文件是哪一个；
- 文件是否和以前上传的内容完全相同；
- 这段文字来自 PDF 第几页或 Markdown 哪个章节；
- 它在规范化文本中的字符范围；
- 它由哪个解析器版本和切块配置生成；
- 重复上传时是否会产生重复数据；
- 改变切块配置后，哪些产物需要重新生成。

所以今天的任务并不是“把文本切成几段”这么简单，而是建立一条可以解释、定位、去重和重建的导入管线：

```text
原始文件
  ↓
读取 bytes
  ↓
解析格式
  ↓
规范化文本
  ↓
保留页面或章节边界
  ↓
按配置切块
  ↓
生成 metadata 和稳定 ID
  ↓
保存原文件、解析结果和 chunks
```

Day 10 到这里结束。embedding、向量数据库、正式检索、重排和引用属于后面的阶段。

---

## 1. 先分清五个容易混在一起的动作

我们固定使用下面这段合成 Markdown：

```text
# Warranty\r\n
\r\n
Returns are accepted within 30 days.  \r\n
Order number required.\r\n
```

其中 `\r\n` 表示 Windows 换行，`days.` 后面故意放了两个空格。

### 1.1 解析：理解文件格式

文件进入程序时首先是 `bytes`，不是可以直接按字符处理的 `str`。

Markdown parser 需要完成两件事：

1. 用 UTF-8 把 bytes 解码为字符串；
2. 识别 `# Warranty` 是标题，后面的内容属于 Warranty 章节。

解析后的结果可以描述为：

```text
格式：Markdown
章节：Warranty
正文：Returns are accepted within 30 days.  \r\nOrder number required.\r\n
```

注意，解析阶段知道了“这是 Warranty 章节”，但换行和尾随空格仍然存在。

为什么不在上传接口里直接写这些逻辑？因为 TXT、Markdown、PDF 的格式规则不同。上传接口应该负责接收文件，parser 才负责理解格式。

三种 parser 的工作差异是：

| 格式 | parser 理解什么 | 自然定位边界 |
|---|---|---|
| TXT | UTF-8 文本 | 整篇文件 |
| Markdown | 标题和章节 | section |
| PDF | 页面中的文字层 | page |

### 1.2 规范化：统一文本表示

下面两段文字在人眼看来相同：

```text
Alpha\r\nBeta
```

```text
Alpha\nBeta
```

但对 Python 来说，第一段包含两个换行字符，第二段只包含一个。如果直接计算字符位置，同一句话在不同操作系统生成的文件里可能得到不同 range。

规范化就是先约定一种统一表示。当前规则是：

- `\r\n` 和单独的 `\r` 都变成 `\n`；
- 删除每一行末尾的空白；
- 删除全文首尾的空行；
- 不随意删除正文中间有意义的空格。

同一份 Warranty 正文规范化后变成：

```text
Returns are accepted within 30 days.\nOrder number required.
```

为什么必须在切块前规范化？因为 chunk 的字符范围指向规范化后的文本。如果先计算 range，再删空格或换行，原来的位置就失效了。

实际核心只有一行组合操作：

```python
normalized = "\n".join(
    line.rstrip() for line in normalized_lines
).strip("\n")
```

这里 `rstrip()` 只处理行尾；它没有把整行左侧可能有意义的缩进全部删除。

### 1.3 切块：把长文本变成有上限的窗口

模型或未来的检索系统通常不希望每次处理整本手册，因此要把文本切成较小的 chunk。

切块配置包含：

- `chunk_size`：每块最多包含多少字符；
- `overlap`：相邻两块重复保留多少字符；
- `version`：这套切块规则的版本。

假设：

```text
chunk_size = 24
overlap = 6
```

真正向前移动的距离是：

```text
step = chunk_size - overlap = 18
```

对规范化后的 Warranty 正文进行切块：

| chunk | 字符范围 | 内容 |
|---:|---:|---|
| 0 | `[0, 24)` | `Returns are accepted wit` |
| 1 | `[18, 42)` | `ed within 30 days.\nOrder` |
| 2 | `[36, 59)` | `\nOrder number required.` |

为什么要 overlap？如果完全不重叠，一句话可能正好被切在两块中间。保留少量上下文，可以降低边界处语义断裂的程度。

为什么 overlap 不能大于或等于 chunk size？因为此时：

```text
step = chunk_size - overlap
```

会变成 0 或负数，循环无法正常向前推进。

### 1.4 Metadata：回答“这块从哪里来”

下面两块内容可能完全相同：

```text
SAME
SAME
```

但第一块可能来自“退货”章节，第二块来自“保修”章节。只看 content 无法区分它们。

Metadata 会记录：

- source ID；
- KB ID；
- 安全文件名；
- 原始文件 checksum；
- parser version；
- chunking version；
- chunk size 和 overlap；
- unit 顺序；
- page 或 section；
- `[char_start, char_end)`。

Warranty 第一块的 metadata 可以理解为：

```text
source_name       = warranty.md
knowledge_base_id = kb-demo
section           = Warranty
page_number       = None
char_start        = 0
char_end          = 24
chunk_size        = 24
overlap           = 6
```

`[start, end)` 是半开区间：包含 start，不包含 end。它与 Python 切片完全一致：

```python
document.content[start:end] == chunk.content
```

这个等式是来源定位是否可靠的核心证据。

### 1.5 索引：以后如何快速找到 chunk

Metadata 描述 chunk，索引帮助系统快速查找 chunk。二者不是一回事。

未来可能出现：

```text
关键词 warranty → chunk_id
向量 [0.12, -0.08, 0.31] → chunk_id
```

Day 10 还没有索引。当前系统只是把 chunks 保存进 in-memory Repository。因此今天的实现证明了“可以产生可靠的检索素材”，并不等于已经完成正式 RAG。

把五个动作压缩成一句话：

```text
解析理解格式，规范化统一字符，切块限制长度，metadata 保存来源，索引负责未来查找。
```

---

## 2. 文档为什么需要两层结构

如果只有一个巨大的 `ParsedDocument.content`，PDF 页码和 Markdown 章节很容易丢失。如果每种格式都使用完全不同的模型，chunker 又会充满格式分支。

当前设计使用两层统一结构：

```text
ParsedDocument
  ├── ParsedUnit：TXT 整篇
  ├── ParsedUnit：Markdown section
  └── ParsedUnit：PDF page
```

### 2.1 ParsedUnit 是语义边界

`ParsedUnit` 表示 parser 能够可靠识别的自然边界。

它包含：

- `unit_index`：在文档中的顺序；
- `content`：该单元规范化后的正文；
- `char_start/char_end`：在完整文档文本中的位置；
- `page_number`：PDF 使用；
- `section`：Markdown 使用。

例如 PDF 第 2 页：

```text
unit_index  = 1
page_number = 2
section     = None
content     = Warranty requests require an order number.
```

例如 Markdown 的 Warranty 章节：

```text
unit_index  = 2
page_number = None
section     = Warranty
content     = Warranty requests require an order number.
```

文字相同，但定位方式不同。

模型还验证：

```text
char_end - char_start == len(content)
```

这可以阻止“正文有 20 个字符，却声称范围长度是 19”这样的坏数据进入系统。

### 2.2 ParsedDocument 是统一 parser 输出

三种 parser 最终都返回 `ParsedDocument`。这样 chunker 不需要知道输入原来是 PDF、Markdown 还是 TXT。

字段可以分成四组理解。

第一组是身份：

- `source_id`；
- `knowledge_base_id`；
- `source_name`。

第二组是展示和格式：

- `title`；
- `mime_type`。

第三组是可重建证据：

- `checksum`；
- `parser_version`。

第四组是文本和定位：

- `content`；
- `units`。

为什么既保存完整 `content`，又保存 `units`？

- 完整 content 提供统一的全局字符坐标；
- units 保留 page/section 边界；
- 每个 unit 都能通过自己的 range 从完整 content 中取回。

如果有两个 unit，构造器会使用两个换行连接它们：

```text
unit 0 content
\n\n
unit 1 content
```

因此第二个 unit 的起点不仅要加上第一个 unit 的长度，还要加上中间两个换行字符。

### 2.3 title、section 和 source_name 不要混用

假设文件名是：

```text
synthetic-handbook.md
```

当前 Service 得到：

```text
source_name = synthetic-handbook.md
title       = synthetic-handbook
```

Markdown parser 可能得到三个 section：

```text
Synthetic Handbook
Returns
Warranty
```

它们的职责分别是：

- source_name：上传文件的安全名称；
- title：文档级展示名称；
- section：文档内部定位名称。

---

## 3. Hash、稳定 ID 与版本

### 3.1 Hash 是什么

Hash 函数把任意长度输入转换成固定长度摘要。当前使用 SHA-256，结果是 64 个十六进制字符。

重要性质是：

- 相同输入稳定得到相同摘要；
- 输入发生微小变化，摘要通常会明显变化；
- 摘要用于比较和标识，不用于恢复原文。

Python 中的核心动作是：

```python
checksum = hashlib.sha256(raw_bytes).hexdigest()
```

### 3.2 checksum 为什么基于原始 bytes

两份文件规范化后可能得到相同文本，但原始 bytes 不同。例如：

```text
第一份使用 \r\n
第二份使用 \n
```

如果 checksum 基于规范化文本，系统会失去“原始文件是否完全相同”的证据。

因此当前规则是：

```text
checksum = SHA-256(original bytes)
```

解析和规范化规则以后改变，也不会改变已经上传文件的原始 checksum。

### 3.3 source ID 为什么不只使用 checksum

用户之前指出了一个关键事实：内容相同不一定是同一个文件。

例如：

```text
refund-policy.txt
warranty-appendix.txt
```

它们可能暂时拥有完全相同的文字，但仍然是两个独立来源。若 source ID 只使用 checksum，系统会错误地把它们合并。

所以当前 source ID 同时考虑：

```text
knowledge_base_id
+ case-insensitive source_name
+ checksum
```

由此产生四种情况：

| 输入关系 | source ID |
|---|---|
| 同一 KB、同名、同 bytes | 相同 |
| 同一 KB、不同名、同 bytes | 不同 |
| 同一 KB、同名、不同 bytes | 不同 |
| 不同 KB、同名、同 bytes | 不同 |

### 3.4 chunk ID 为什么还要考虑配置

同一份原文件使用不同切块配置，会产生不同的派生结果。

例如：

```text
配置 A：chunk_size=500, overlap=50
配置 B：chunk_size=300, overlap=30
```

即使某一块碰巧拥有相同内容，也不能假设它与旧配置下的 chunk 是同一产物。

当前 chunk ID 考虑：

- source ID；
- checksum；
- parser version；
- chunking version；
- chunk size；
- overlap；
- range；
- chunk content。

所以：

```text
同输入 + 同配置 → 稳定得到相同 chunk ID
配置、位置或内容变化 → chunk ID 改变
```

### 3.5 版本字段解决什么问题

假设以后 Markdown parser 开始支持另一种标题规则。即使原始文件没变，解析出来的 section 可能不同。

如果不记录 parser version，我们无法回答“这个 ParsedDocument 是由哪套规则生成的”。

同理，chunking version 说明 chunks 属于哪套切块规则。

当前版本是：

```text
TXT parser       = txt-v1
Markdown parser  = markdown-v1
PDF parser       = pypdf-6.16.2-v1
默认 chunking    = day10-v1
```

版本不是自动递增的数据库行号，而是生成规则的一部分。

---

## 4. 三种 Parser 如何进入同一个模型

### 4.1 共享构造过程

三个 parser 只负责提供各自的语义单元。公共构造器负责：

1. 逐个规范化 unit；
2. 跳过空 unit；
3. 用 `\n\n` 连接非空 units；
4. 计算每个 unit 的全局 range；
5. 如果最终没有正文，返回 `empty_document`；
6. 创建统一 ParsedDocument。

每个 parser 交给公共构造器的数据可以理解为：

```text
(unit_content, page_number, section)
```

这让坐标计算、空文档判断和 checksum 逻辑只实现一次。

### 4.2 TXT parser

TXT 是最薄的 parser：

```text
raw bytes
  ↓ UTF-8 decode
一个没有 page/section 的 unit
  ↓
ParsedDocument
```

它仍然可能失败。如果 bytes 不是合法 UTF-8，会得到：

```text
code    = invalid_utf8
message = Document must be valid UTF-8
```

内部会保留原始 `UnicodeDecodeError` 作为异常链，方便开发时定位；对外只暴露固定消息。

### 4.3 Markdown parser

当前 Markdown parser 只实现透明、可读的 ATX 标题规则：

```text
# 一级标题
## 二级标题
###### 六级标题
```

它的运行过程像一个很小的状态机：

1. `current_section` 保存当前章节名；
2. `current_lines` 收集当前章节正文；
3. 遇到普通行就追加正文；
4. 遇到新标题先保存旧章节；
5. 把标题文字设为新的 current_section；
6. 循环结束后保存最后一个章节。

例如：

```text
# Guide
Introduction.
## Warranty
Order number required.
```

状态变化是：

```text
看到 # Guide
→ current_section=Guide

看到 Introduction.
→ current_lines=[Introduction.]

看到 ## Warranty
→ 保存 Guide unit
→ current_section=Warranty
→ current_lines=[]

看到 Order number required.
→ current_lines=[Order number required.]

文件结束
→ 保存 Warranty unit
```

这套实现没有使用大型文档框架，也不声称覆盖完整 CommonMark。Day 10 的目标是看清标题如何变成 section，而不是隐藏解析细节。

### 4.4 PDF parser

PDF 不是“带分页符的普通文本”。它主要描述文字或图形在页面上的绘制方式，因此提取文字存在天然限制。

当前使用固定版本 `pypdf==6.16.2`：

```text
raw bytes
  ↓ BytesIO
PdfReader
  ↓ 遍历 pages
page.extract_text()
  ↓
每页一个 unit
```

`BytesIO` 只是把内存中的 bytes 包装成类文件对象，没有把上传内容写到服务器临时路径。

Python 页列表从 0 开始，但用户看到的 PDF 页码从 1 开始，所以：

```python
page_number = page_index + 1
```

#### 文字 PDF 与扫描 PDF

文字 PDF 包含可提取的文字层，`extract_text()` 可以返回字符串。

扫描 PDF 可能只包含页面图片。pypdf 不是 OCR 软件，不能从图片像素中识别文字。

当前判定是：

```text
至少一页有可提取文本 → 继续导入
所有页面都没有可提取文本 → scanned_pdf_unsupported
```

这不是说“所有无文本 PDF 一定是扫描件”，而是给 Day 10 的能力边界一个诚实、稳定的分类：当前没有文字可供导入，也没有 OCR。

官方参考：

- <https://pypdf.readthedocs.io/en/stable/user/extract-text.html>
- <https://pypdf.readthedocs.io/en/stable/user/installation.html>
- <https://pypi.org/project/pypdf/>

#### 损坏 PDF

如果 PdfReader 或页面提取失败，底层异常可能包含复杂实现信息。API 不应该把它直接返回给用户。

因此统一映射为：

```text
code    = invalid_pdf
message = PDF could not be parsed
```

真实异常仍作为内部异常链保存。

---

## 5. 层级切块为什么比“整篇直接切”可靠

### 5.1 第一层：语义单元

先按 parser 能识别的边界划分：

```text
TXT       → 整篇 unit
Markdown  → section units
PDF       → page units
```

### 5.2 第二层：固定窗口

然后在每个 unit 内应用 `chunk_size/overlap`。

这能保证：

- PDF chunk 不跨页；
- Markdown chunk 不跨章节；
- 每块都能继承准确 page/section；
- 仍然可以控制极长章节的 chunk 大小。

### 5.3 局部坐标如何变成全文坐标

`chunk_text()` 看到的是一个 unit，所以它产生的是 unit 内局部 range。

假设：

```text
unit.char_start       = 100
text_chunk.char_start = 20
text_chunk.char_end   = 50
```

文档全局位置是：

```text
char_start = 100 + 20 = 120
char_end   = 100 + 50 = 150
```

这就是 `chunk_document()` 的核心工作：把纯文本切片升级为具有文档来源的 DocumentChunk。

### 5.4 为什么最后要检查 end

每一轮先计算：

```text
end = min(start + chunk_size, len(text))
```

如果 end 已经等于文本长度，就应该停止。否则在 overlap 很大时，后续循环可能继续生成完全包含在上一块里的小尾块。

例如长度 6、size 5、overlap 4：

```text
正确：[0,5)、[1,6)
```

到 `[1,6)` 时已经覆盖末尾，不应继续生成 `[2,6)`、`[3,6)`。

### 5.5 重复内容块为什么不能随便删除

假设两个章节都包含：

```text
SAME
```

第一块来自 Returns，第二块来自 Warranty。虽然 content 相同，但 source location 不同。

当前系统不会按纯内容删除其中一块。range 和 section 会参与 metadata，range 也参与 chunk ID，因此两个引用位置保持独立。

Day 10 的“去重”主要指重复导入安全，不是对全库相同字符串进行破坏性合并。

---

## 6. 从上传到保存：Service 如何编排整条管线

### 6.1 为什么要有 Repository、Service 和 API 三层

API 负责 HTTP：

- 接收路径参数和上传文件；
- 异步读取 bytes；
- 把结果状态映射成 HTTP 状态码。

Service 负责业务流程：

- 校验 KB 和文件边界；
- 计算 hash 和 ID；
- 选择 parser；
- 判断 duplicate/rebuilt；
- 调用 chunker；
- 要求 Repository 保存结果。

Repository 负责存储契约：

- 保存和读取 KB；
- 保存原始 bytes；
- 保存 ParsedDocument；
- 保存和列出 chunks。

依赖方向是：

```text
API → Service → Repository
          ├── parser
          └── chunker
```

Repository 不应该反过来调用 Service，parser 也不应该知道 HTTP Response。

### 6.2 文件 I/O 为什么读取上限加 1

上传限制是 1 MiB。

如果只读取正好 1 MiB，我们无法判断文件是：

- 正好 1 MiB；
- 还是 1 MiB 后面仍有更多内容。

因此 API 执行：

```python
raw_bytes = await file.read(MAX_UPLOAD_BYTES + 1)
```

结果长度大于上限就拒绝。这样不需要先把任意大的文件全部读入内存。

这里的 `await` 表示读取可能需要等待，事件循环可以在等待期间处理其他工作；它不会把 parser 自动变成并行程序。

### 6.3 校验顺序

当前 Service 按下面的顺序处理：

1. KB 是否存在；
2. 文件名是否存在并安全化；
3. 文件是否超过大小上限；
4. 计算 checksum 和 source ID；
5. 扩展名是否支持；
6. MIME 是否与扩展名匹配；
7. 是否已有相同 source；
8. 选择 parser；
9. 生成 chunks；
10. 保存原始 bytes、文档和 chunks。

大小检查必须在完整 checksum 之前。API 对超大文件只读取上限加 1 字节，这不是完整文件，不能把这个前缀 hash 冒充成完整 source checksum。

### 6.4 扩展名和 MIME 为什么都要检查

只检查文件名：用户可以把任意内容改名为 `.pdf`。

只相信 MIME：客户端也可以错误声明 MIME。

Day 10 采用明确配对：

| 扩展名 | MIME |
|---|---|
| `.txt` | `text/plain` |
| `.md` | `text/markdown` |
| `.markdown` | `text/markdown` |
| `.pdf` | `application/pdf` |

这仍不是生产级文件内容嗅探或恶意文件扫描，但建立了最小上传边界。

### 6.5 为什么要安全化文件名

客户端可能提交：

```text
C:\private\synthetic.pdf
```

Service 只保留最后一段：

```text
synthetic.pdf
```

这样响应、metadata 和错误中不会保留客户端路径。parser 本身只接收 bytes，也不接触服务器文件系统路径。

### 6.6 六种结果状态

| status | 含义 |
|---|---|
| `imported` | 首次成功导入并保存 |
| `duplicate` | source 和切块配置都相同，不重复写入 |
| `rebuilt` | source 相同但配置改变，重新生成派生产物 |
| `rejected` | 上传边界不接受，例如大小、扩展名、MIME |
| `unsupported` | 文件有效，但当前能力不支持，例如纯图片 PDF |
| `failed` | 文件应可处理，但解析失败 |

成功状态不能携带 error；非成功状态必须携带稳定的 error code 和公开 message。结果模型通过 validator 保证这个组合关系。

### 6.7 duplicate 与 rebuilt 的区别

第一次导入：

```text
保存 raw bytes
保存 ParsedDocument
保存 chunks
返回 imported
```

再次上传同一 source、使用同一配置：

```text
不增加 source
不增加 chunks
返回 duplicate
```

再次上传同一 source、切块配置改变：

```text
raw bytes 保留
ParsedDocument 保留
旧 chunks 被新 chunks 替换
metadata 更新
chunk IDs 更新
返回 rebuilt
```

为什么不重新解析？因为这次变化发生在切块配置，parser 输入和 parser version 没变。重新解析不会提供新信息。

如果将来 parser version 改变，则需要单独定义重新解析策略；Day 10 没有偷偷加入这条额外流程。

### 6.8 API Route

创建 KB：

```text
POST /api/knowledge-bases
```

上传 source：

```text
POST /api/knowledge-bases/{knowledge_base_id}/sources
```

HTTP 状态大致映射为：

| 导入结果 | HTTP |
|---|---:|
| imported | 201 |
| duplicate / rebuilt | 200 |
| upload too large | 413 |
| extension/MIME rejected | 415 |
| unsupported/failed | 422 |
| KB missing | 404 |

API 返回 source、status、checksum、chunk count 和分类错误，不返回 ParsedDocument 全文或原始文件内容。

---

## 7. 错误边界：失败也必须是稳定契约

### 7.1 为什么不能直接返回 `str(exc)`

第三方异常可能包含：

- 服务器本地路径；
- 库内部对象名称；
- 文件结构细节；
- 不稳定、随版本变化的文案。

如果 API 直接返回它，既可能泄露信息，也会让客户端测试依赖第三方错误字符串。

因此对外使用稳定分类：

| code | 含义 |
|---|---|
| `missing_filename` | 缺少文件名 |
| `upload_too_large` | 超过大小上限 |
| `unsupported_extension` | 扩展名不支持 |
| `mime_type_mismatch` | MIME 与扩展名不匹配 |
| `invalid_utf8` | TXT/Markdown 解码失败 |
| `empty_document` | 规范化后没有文本 |
| `invalid_pdf` | PDF 结构解析失败 |
| `scanned_pdf_unsupported` | 没有文字层，当前不做 OCR |

### 7.2 rejected、unsupported、failed 为什么分开

它们代表不同责任边界：

- rejected：请求没有通过入口规则；
- unsupported：输入可能完全有效，但产品没有该能力；
- failed：产品声称能够处理这种输入，但具体解析没有成功。

扫描 PDF 返回 unsupported 比返回 failed 更准确，因为失败原因不是“程序意外出错”，而是当前明确没有 OCR 能力。

---

## 8. 测试应该证明什么

测试不是为了堆数量，而是证明关键不变量。

### 8.1 Fixture 为什么必须固定且合成

当前 fixture 包括：

```text
synthetic-policy.txt
synthetic-handbook.md
synthetic-support-guide.pdf
synthetic-scanned-page.pdf
```

它们全部是自编微型内容。这样做有三个好处：

1. 没有个人资料和真实用户数据；
2. 没有版权来源不清的问题；
3. 文件足够小，失败时能够人工检查。

文字 PDF 有两页，用于证明 page 定位；扫描 PDF 只有图片，用于证明 unsupported 边界。

### 8.2 解析测试

解析测试至少要验证：

- TXT 进入统一 ParsedDocument；
- 换行和尾随空格被规范化；
- 非 UTF-8 文本得到 invalid_utf8；
- Markdown 标题形成多个 section；
- 没有标题时使用文档 title 作为 section；
- 中文 UTF-8 文本正常工作；
- Markdown 可选结尾 `#` 不进入 section 名称；
- 文字 PDF 形成正确 page units；
- 扫描 PDF 返回明确 unsupported；
- 损坏 PDF 返回固定错误且不含路径；
- 同样输入产生稳定 source ID；
- 同内容不同文件名保持不同 source ID。

关键断言不是“函数返回了对象”，而是来源能够取回：

```python
document.content[
    unit.char_start : unit.char_end
] == unit.content
```

### 8.3 切块测试

切块测试需要证明：

- overlap 的 start/end 正确；
- 空字符串不产生空 chunk；
- overlap 必须小于 chunk size；
- 极长文本的每块都不超过 chunk size；
- 到达末尾后不会继续产生被包含的小尾块；
- chunk 保留 section/page 和全局 range；
- chunk 不跨语义 unit；
- 同文档同配置的 IDs 稳定；
- 配置改变后 IDs 改变；
- 相同文字出现在不同位置时不会错误合并。

经典 overlap 例子是：

```text
text = ABCDEFGH
size = 3
overlap = 1

[0,3) ABC
[2,5) CDE
[4,7) EFG
[6,8) GH
```

把范围、内容放进同一个列表断言，比拆成许多零散断言更容易看出整体规律。

### 8.4 去重和重建测试

重建测试要同时验证变化项和不变项。

不变项：

- source ID；
- 原始 bytes；
- ParsedDocument；
- checksum。

变化项：

- chunk 数量可能变化；
- char ranges 可能变化；
- chunking metadata 改变；
- chunk IDs 改变。

如果测试只断言 `status == rebuilt`，并没有证明系统真的正确重建了派生产物。

### 8.5 API 测试

API 测试使用 multipart 上传，验证：

- 创建 KB 返回 201；
- 首次 TXT 上传返回 imported；
- 重复上传返回 duplicate；
- 扫描 PDF 返回 unsupported；
- 扩展名和 MIME 错误返回稳定分类；
- 超大文件返回 413；
- KB 不存在返回 404；
- 客户端路径不会出现在响应里。

扩展名和 MIME 可以使用参数化测试，因为它们属于“上传类型边界”下的两个代表等价类。没有必要为每一个可能的扩展名单独复制整条测试。

### 8.6 如何判断修改配置后哪些测试应变化

如果只把：

```text
chunk_size=5, overlap=1
```

改成：

```text
chunk_size=6, overlap=2
```

应该重新检查：

- 预期 chunk 数；
- 每块 `[start, end)`；
- 每块 content；
- metadata 中的 size/overlap/version；
- chunk IDs。

不应该改变：

- 原始 bytes；
- checksum；
- source ID；
- parser version；
- page/section 的语义含义。

这就是“配置改变只影响它下游的派生产物”。

---

## 9. 当前代码地图

这一节不重复粘贴完整源码，只说明每个名称负责什么，以及推荐阅读顺序。

### 9.1 `src/omniagent/ingestion.py`

| 名称 | 用途 |
|---|---|
| `DocumentParseError` | 可分类的解析失败，保存 code 和公开 message |
| `UnsupportedDocumentError` | 有效输入但能力不支持，例如无文字层 PDF |
| `ParsedUnit` | TXT 文档、Markdown section 或 PDF page 的统一语义单元 |
| `ParsedDocument` | 三种 parser 的统一输出 |
| `ImportErrorDetail` | API 可返回的固定错误结构 |
| `SourceImportResult` | imported/duplicate/rebuilt/rejected/unsupported/failed 统一结果 |
| `checksum_bytes()` | 对原始 bytes 计算 SHA-256 |
| `build_source_id()` | 使用 KB、文件名和 checksum 生成稳定 source ID |
| `normalize_text()` | 统一换行、行尾空白和首尾空行 |
| `_decode_utf8()` | UTF-8 解码并映射 invalid_utf8 |
| `_build_document()` | 统一规范化 units、计算全局 range、构造文档 |
| `parse_txt()` | TXT 最小解析路径 |
| `parse_markdown()` | 基于 ATX 标题构造 section units |
| `parse_pdf()` | 使用 pypdf 提取 page units 并识别无文字层边界 |

推荐阅读顺序：

```text
normalize_text
→ ParsedUnit
→ ParsedDocument
→ _build_document
→ parse_txt
→ parse_markdown
→ parse_pdf
→ hash 和结果模型
```

### 9.2 `src/omniagent/chunking.py`

| 名称 | 用途 |
|---|---|
| `ChunkingConfig` | 保存 size、overlap、version，并拒绝非法步长 |
| `TextChunk` | 纯文本和局部 range |
| `ChunkMetadata` | 完整来源、位置和版本信息 |
| `DocumentChunk` | 稳定 chunk ID、顺序、content、metadata |
| `chunk_text()` | 在一个字符串内执行固定窗口 overlap |
| `_build_chunk_id()` | 从 source、配置、range、content 生成稳定 ID |
| `chunk_document()` | 按 units 分层切块，并把局部坐标转换成全局坐标 |

推荐阅读顺序：

```text
ChunkingConfig
→ chunk_text
→ TextChunk
→ ChunkMetadata / DocumentChunk
→ _build_chunk_id
→ chunk_document
```

### 9.3 `src/omniagent/repositories.py`

| 名称 | 用途 |
|---|---|
| `KnowledgeRepository` | 定义 KB、source bytes、文档和 chunks 的存储接口 |
| `InMemoryKnowledgeRepository` | 用四个字典实现离线存储 |

四个字典分别保存：

```text
knowledge bases
ParsedDocuments
original bytes
chunks by source ID
```

返回 chunks 时会复制列表，避免调用者直接修改 Repository 内部列表对象。

### 9.4 `src/omniagent/services.py`

| 名称 | 用途 |
|---|---|
| `KnowledgeBaseAlreadyExistsError` | 创建重复 KB |
| `KnowledgeBaseNotFoundError` | 上传目标 KB 不存在 |
| `KnowledgeBaseService.create()` | 最小 KB 创建流程 |
| `KnowledgeBaseService.import_source()` | 上传校验、hash、去重、解析、切块和保存的总编排 |
| `_error_result()` | 统一构造带 ImportErrorDetail 的失败结果 |

阅读 `import_source()` 时，不要一次盯着所有分支。按下面五段理解：

```text
入口校验
→ source 身份
→ duplicate/rebuilt
→ parser dispatch
→ chunk + persistence
```

### 9.5 `src/omniagent/api.py`

Day 10 新增：

| 名称 | 用途 |
|---|---|
| `get_knowledge_base_service()` | FastAPI 依赖注入入口 |
| `create_knowledge_base()` | 创建 KB Route |
| `upload_knowledge_source()` | 异步读取文件并调用 Service |
| KB 异常 handlers | 把领域异常映射成稳定 404/409 |

API 不包含 parser 细节，也不自己计算 chunk ID。它只负责 HTTP 边界。

### 9.6 测试文件

| 文件 | 主要证据 |
|---|---|
| `tests/test_ingestion.py` | 三格式、规范化、中文、空/坏/扫描件、source ID |
| `tests/test_chunking.py` | overlap、range、层级边界、稳定 ID、长块和重复文字 |
| `tests/test_knowledge_service.py` | duplicate、rebuilt、原文件保留 |
| `tests/test_api.py` | KB、multipart 上传、大小/类型/路径错误 |

推荐先读测试名称，再读生产代码。测试名称先告诉你系统承诺了哪些行为，生产代码再告诉你这些行为如何实现。

---

## 10. 把整条运行时链路串起来

一次成功的 TXT 上传按以下顺序发生：

```text
客户端上传文件
→ FastAPI 读取有限长度 bytes
→ Service 检查 KB、名称、大小、扩展名和 MIME
→ 对原始 bytes 计算 checksum
→ 生成 source ID
→ Repository 检查是否已有 source
→ TXT parser 解码 UTF-8
→ 规范化文本
→ 创建 ParsedUnit 和 ParsedDocument
→ chunker 在 unit 内切块
→ 生成全局 range、metadata 和 chunk IDs
→ Repository 保存原始 bytes、文档和 chunks
→ API 返回 imported、source、checksum、chunk count
```

同一 source 再次进入时，流程在 Repository 检查处发生分叉：

```text
切块配置相同
→ duplicate
→ 不重复生成

切块配置改变
→ rebuilt
→ 原文件和 ParsedDocument 保留
→ chunks、metadata、IDs 重新生成
```

这条因果链是理解 Day 10 的核心：原始 source 是事实，ParsedDocument 是解析产物，chunks 和 metadata 是配置驱动的派生产物。
