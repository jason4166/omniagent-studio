<script setup lang="ts">
import { onMounted, ref } from 'vue'
import type { ApiClient } from '../api/client'
import type {
  AgentProfile,
  AuditEvent,
  KnowledgeBase,
  PromptVersion,
  Provider,
  Source,
  ToolDefinition,
} from '../api/types'
import ProfileEditor from './ProfileEditor.vue'

const props = defineProps<{ api: ApiClient }>()
const tab = ref('profiles')
const busy = ref(false)
const error = ref('')
const success = ref('')
const profiles = ref<AgentProfile[]>([])
const kbs = ref<KnowledgeBase[]>([])
const tools = ref<ToolDefinition[]>([])
const prompts = ref<PromptVersion[]>([])
const providers = ref<Provider[]>([])
const audit = ref<AuditEvent[]>([])
const editor = ref<AgentProfile | null>(null)
const editorOpen = ref(false)
const creating = ref(false)
const kbDraft = ref({ knowledge_base_id: '', name: '' })
const activeKB = ref('')
const sources = ref<Source[]>([])
const promptId = ref('')
const promptContent = ref('')
const activeTool = ref<ToolDefinition | null>(null)
const toolOpen = ref(false)
const importOpen = ref(false)
const importKind = ref<'profile' | 'openapi'>('profile')
const importText = ref('')
const exportText = ref('')
const exportOpen = ref(false)

async function load() {
  const data = await Promise.all([
    props.api.profiles(),
    props.api.knowledgeBases(),
    props.api.tools(),
    props.api.prompts(),
    props.api.providers(),
    props.api.audit(),
  ])
  ;[profiles.value, kbs.value, tools.value, prompts.value, providers.value, audit.value] = data
}
async function perform(fn: () => Promise<void>, message = '操作成功') {
  if (busy.value) return
  busy.value = true
  error.value = ''
  success.value = ''
  try {
    await fn()
    success.value = message
  } catch (e) {
    error.value = e instanceof Error ? e.message : '操作失败'
  } finally {
    busy.value = false
  }
}
function edit(profile?: AgentProfile) {
  creating.value = !profile
  editor.value = profile
    ? JSON.parse(JSON.stringify(profile))
    : {
        profile_id: '',
        name: '',
        description: '',
        version: 1,
        enabled: true,
        provider_id: 'fake',
        model: 'fake-v1',
        temperature: 0,
        allowed_roles: ['admin', 'member', 'viewer'],
        auto_approve_read: true,
        require_evidence: true,
        tool_ids: [],
        knowledge_base_ids: [],
        prompt_version_id: prompts.value[0]?.prompt_version_id ?? '',
        budget_policy_id: 'standard',
        approval_policy_id: 'safe-default',
        context_policy: {
          last_n: 8,
          max_characters: 12000,
          max_tokens: 16000,
          summarize: true,
          summary_characters: 500,
          ttl_seconds: 86400,
        },
        budgets: {
          max_steps: 24,
          max_model_calls: 4,
          max_tool_calls: 4,
          max_tokens: 64000,
          max_cost_microusd: null,
          deadline_seconds: 120,
        },
      }
  editorOpen.value = true
}
async function saved() {
  editorOpen.value = false
  await perform(load, 'Profile 已保存，新运行使用更新后的配置')
}
function importDialog(kind: 'profile' | 'openapi') {
  importKind.value = kind
  importText.value = ''
  importOpen.value = true
}
async function importData() {
  await perform(async () => {
    if (importText.value.length > 65536) throw new Error('导入内容超过 64 KiB')
    const document: unknown = JSON.parse(importText.value)
    if (importKind.value === 'profile') await props.api.importProfile(document)
    else await props.api.importOpenAPI(document)
    importOpen.value = false
    await load()
  }, '导入成功')
}
async function exportProfile(id: string) {
  await perform(async () => {
    exportText.value = JSON.stringify(await props.api.exportProfile(id), null, 2)
    exportOpen.value = true
  }, '导出已生成')
}
function download() {
  const url = URL.createObjectURL(new Blob([exportText.value], { type: 'application/json' }))
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = 'agent-profile.json'
  anchor.click()
  URL.revokeObjectURL(url)
}
async function loadSources() {
  await perform(async () => {
    sources.value = activeKB.value ? await props.api.sources(activeKB.value) : []
  }, '文档状态已刷新')
}
async function createKB() {
  await perform(async () => {
    const kb = await props.api.createKnowledgeBase(kbDraft.value)
    activeKB.value = kb.knowledge_base_id
    sources.value = []
    kbDraft.value = { knowledge_base_id: '', name: '' }
    await load()
  }, '知识库已创建')
}
async function upload(e: Event) {
  const element = e.target as HTMLInputElement
  const file = element.files?.[0]
  if (!file || !activeKB.value) return
  await perform(async () => {
    if (file.size > 1048576) throw new Error('文件不能超过 1 MiB')
    const result = await props.api.upload(activeKB.value, file)
    if (!['imported', 'duplicate', 'rebuilt'].includes(result.status))
      throw new Error(`导入未完成：${result.status}`)
    sources.value = await props.api.sources(activeKB.value)
  }, '文档已导入并完成索引（重复文档自动复用）')
  element.value = ''
}
function editTool(tool: ToolDefinition) {
  activeTool.value = JSON.parse(JSON.stringify(tool))
  toolOpen.value = true
}
async function saveTool() {
  if (!activeTool.value) return
  const tool = activeTool.value
  await perform(async () => {
    await props.api.saveTool(tool)
    toolOpen.value = false
    await load()
  }, '工具配置已保存')
}
async function createPrompt() {
  await perform(async () => {
    await props.api.createPrompt(promptId.value, promptContent.value)
    promptId.value = ''
    promptContent.value = ''
    await load()
  }, '不可变 Prompt 版本已创建')
}
onMounted(() => perform(load, '配置已加载'))
</script>

<template>
  <section class="workspace admin-workspace">
    <div class="page-heading">
      <div>
        <div class="eyebrow">CONFIGURATION & GOVERNANCE</div>
        <h1>配置助手，也定义它的边界。</h1>
        <p>知识、工具与权限分别管理，通过 Profile 组合成可运行的助手。</p>
      </div>
      <el-button :loading="busy" @click="perform(load, '已刷新')">刷新</el-button>
    </div>
    <el-alert v-if="error" :title="error" type="error" show-icon @close="error = ''" /><el-alert
      v-if="success"
      :title="success"
      type="success"
      show-icon
      @close="success = ''"
    />
    <el-tabs v-model="tab" class="admin-tabs">
      <el-tab-pane label="Agent Profiles" name="profiles">
        <div class="section-toolbar">
          <div>
            <h2>Agent Profiles</h2>
            <p class="small">每个配置独立绑定知识库、工具和安全策略</p>
          </div>
          <div>
            <el-button @click="importDialog('profile')">导入 JSON</el-button
            ><el-button type="primary" @click="edit()">创建 Profile</el-button>
          </div>
        </div>
        <el-table :data="profiles" stripe
          ><el-table-column prop="name" label="名称" min-width="170" /><el-table-column
            prop="profile_id"
            label="ID"
          /><el-table-column label="模型" min-width="130"
            ><template #default="scope"
              >{{ scope.row.provider_id }} / {{ scope.row.model }}</template
            ></el-table-column
          ><el-table-column label="授权范围" min-width="170"
            ><template #default="scope"
              >{{ scope.row.knowledge_base_ids.length }} KB ·
              {{ scope.row.tool_ids.length }} 工具</template
            ></el-table-column
          ><el-table-column label="版本 / 状态"
            ><template #default="scope"
              >v{{ scope.row.version }} · {{ scope.row.enabled ? '启用' : '停用' }}</template
            ></el-table-column
          ><el-table-column label="操作" width="155"
            ><template #default="scope"
              ><el-button text type="primary" @click="edit(scope.row)">编辑</el-button
              ><el-button text @click="exportProfile(scope.row.profile_id)"
                >导出</el-button
              ></template
            ></el-table-column
          ></el-table
        >
      </el-tab-pane>
      <el-tab-pane label="知识库" name="knowledge">
        <div class="section-toolbar">
          <h2>知识与来源</h2>
          <span class="small">PDF / Markdown / TXT · 单文件最多 1 MiB</span>
        </div>
        <div class="form-grid admin-create-row">
          <el-input
            v-model="kbDraft.knowledge_base_id"
            placeholder="知识库 ID"
            aria-label="知识库 ID"
          /><el-input
            v-model="kbDraft.name"
            placeholder="知识库名称"
            aria-label="知识库名称"
          /><el-button
            type="primary"
            :disabled="busy || !kbDraft.name || !kbDraft.knowledge_base_id"
            @click="createKB"
            >创建知识库</el-button
          >
        </div>
        <div class="section-toolbar">
          <el-select
            v-model="activeKB"
            placeholder="选择知识库"
            aria-label="选择知识库"
            style="width: 280px"
            @change="loadSources"
            ><el-option
              v-for="kb in kbs"
              :key="kb.knowledge_base_id"
              :label="kb.name"
              :value="kb.knowledge_base_id" /></el-select
          ><label class="upload-label" :class="{ disabled: !activeKB || busy }"
            >上传文档<input
              type="file"
              accept=".pdf,.md,.markdown,.txt"
              aria-label="上传文档"
              :disabled="!activeKB || busy"
              @change="upload"
          /></label>
        </div>
        <el-table :data="sources" empty-text="选择知识库查看文档，或上传第一份文档"
          ><el-table-column prop="source_name" label="文件" /><el-table-column
            prop="title"
            label="标题" /><el-table-column label="状态"
            ><template #default="scope"
              ><el-tag type="success">{{ scope.row.status }}</el-tag></template
            ></el-table-column
          ><el-table-column prop="source_id" label="来源 ID"
        /></el-table>
      </el-tab-pane>
      <el-tab-pane label="工具与连接器" name="tools">
        <div class="section-toolbar">
          <div>
            <h2>受控工具目录</h2>
            <p class="small">固定连接器合同；模型只提交业务参数。写入和风险操作强制审批。</p>
          </div>
          <el-button @click="importDialog('openapi')">导入 OpenAPI 子集</el-button>
        </div>
        <el-table :data="tools"
          ><el-table-column prop="name" label="工具" min-width="190" /><el-table-column
            prop="adapter_id"
            label="连接器"
            min-width="190"
          /><el-table-column label="风险"
            ><template #default="scope"
              ><el-tag :type="scope.row.risk === 'low' ? 'success' : 'warning'">{{
                scope.row.risk
              }}</el-tag></template
            ></el-table-column
          ><el-table-column label="审批要求"
            ><template #default="scope">{{
              scope.row.requires_approval ? '需要审批' : '只读 · 按 Profile 策略'
            }}</template></el-table-column
          ><el-table-column label="超时"
            ><template #default="scope"
              >{{ scope.row.timeout_seconds }} s</template
            ></el-table-column
          ><el-table-column label="操作" width="90"
            ><template #default="scope"
              ><el-button text type="primary" @click="editTool(scope.row)"
                >管理</el-button
              ></template
            ></el-table-column
          ></el-table
        >
      </el-tab-pane>
      <el-tab-pane label="Prompt 版本" name="prompts">
        <div class="section-toolbar">
          <div>
            <h2>不可变 Prompt 版本</h2>
            <p class="small">通过新版本更新内容，再修改 Profile 引用。</p>
          </div>
        </div>
        <el-form label-position="top" class="prompt-form"
          ><el-form-item label="新版本 ID"
            ><el-input
              v-model="promptId"
              placeholder="例如 support:v2"
              maxlength="120" /></el-form-item
          ><el-form-item label="Prompt 内容"
            ><el-input
              v-model="promptContent"
              type="textarea"
              :rows="5"
              maxlength="6000"
              show-word-limit /></el-form-item
          ><el-button
            type="primary"
            :disabled="busy || !promptId || !promptContent"
            @click="createPrompt"
            >创建版本</el-button
          ></el-form
        >
        <el-collapse
          ><el-collapse-item
            v-for="p in prompts"
            :key="p.prompt_version_id"
            :title="p.prompt_version_id"
            :name="p.prompt_version_id"
            ><p class="small">SHA-256 {{ p.content_hash }}</p>
            <pre class="citation-content">{{ p.content }}</pre>
          </el-collapse-item></el-collapse
        >
      </el-tab-pane>
      <el-tab-pane label="Provider" name="providers"
        ><div class="section-toolbar"><h2>Provider 配置状态</h2></div>
        <el-alert
          title="真实 Provider 密钥仅在服务端配置。此页面只显示引用、模型与是否可用。"
          type="info"
          :closable="false"
        /><el-table :data="providers"
          ><el-table-column prop="provider_id" label="引用" /><el-table-column
            prop="model"
            label="模型"
          /><el-table-column label="状态"
            ><template #default="scope"
              ><el-tag :type="scope.row.configured ? 'success' : 'info'">{{
                scope.row.configured ? '已配置' : '未配置（可选）'
              }}</el-tag></template
            ></el-table-column
          ></el-table
        ></el-tab-pane
      >
      <el-tab-pane label="审计" name="audit"
        ><div class="section-toolbar">
          <h2>最近 100 条审计事件</h2>
          <p class="small">仅保留标识、计数和摘要哈希</p>
        </div>
        <el-table :data="audit"
          ><el-table-column prop="action" label="操作" min-width="170" /><el-table-column
            prop="created_at"
            label="时间"
            min-width="190"
          /><el-table-column prop="thread_id" label="会话" min-width="160" /><el-table-column
            label="脱敏详情"
            min-width="240"
            ><template #default="scope"
              ><span class="audit-detail">{{ JSON.stringify(scope.row.details) }}</span></template
            ></el-table-column
          ></el-table
        ></el-tab-pane
      >
    </el-tabs>
    <el-drawer
      v-model="editorOpen"
      :title="creating ? '创建 AgentProfile' : '编辑 AgentProfile'"
      size="min(720px, 97vw)"
      destroy-on-close
      ><ProfileEditor
        v-if="editor"
        :api="api"
        :profile="editor"
        :creating="creating"
        :knowledge-bases="kbs"
        :tools="tools"
        :prompts="prompts"
        :providers="providers"
        @saved="saved"
    /></el-drawer>
    <el-dialog v-model="toolOpen" title="工具配置" width="min(640px, 95vw)"
      ><el-form v-if="activeTool" label-position="top"
        ><p>
          <strong>{{ activeTool.name }}</strong> · {{ activeTool.adapter_id }}
        </p>
        <el-form-item label="描述"><el-input v-model="activeTool.description" /></el-form-item>
        <div class="form-grid">
          <el-form-item label="风险级别（不能低于连接器要求）"
            ><el-select v-model="activeTool.risk"
              ><el-option value="low" /><el-option value="medium" /><el-option
                value="high" /></el-select></el-form-item
          ><el-form-item label="超时（秒）"
            ><el-input-number
              v-model="activeTool.timeout_seconds"
              :min="0.1"
              :max="30" /></el-form-item
          ><el-form-item label="启用"><el-switch v-model="activeTool.enabled" /></el-form-item
          ><el-form-item label="需要审批"
            ><el-switch
              v-model="activeTool.requires_approval"
              :disabled="activeTool.effect === 'write' || activeTool.risk === 'high'"
          /></el-form-item>
        </div>
        <el-form-item label="角色"
          ><el-checkbox-group v-model="activeTool.allowed_roles"
            ><el-checkbox value="admin" label="admin" /><el-checkbox
              value="member"
              label="member" /></el-checkbox-group
        ></el-form-item>
        <h3>固定业务参数 Schema</h3>
        <pre class="code-block">{{ JSON.stringify(activeTool.parameters_schema, null, 2) }}</pre>
        <el-button type="primary" :loading="busy" @click="saveTool">保存工具</el-button
        ><el-alert v-if="error" :title="error" type="error" :closable="false" /></el-form
    ></el-dialog>
    <el-dialog
      v-model="importOpen"
      :title="importKind === 'profile' ? '导入 Profile JSON' : '导入受控 OpenAPI 子集'"
      width="min(680px, 95vw)"
      ><p class="small">
        {{
          importKind === 'profile'
            ? 'schema_version 必须为 1；知识库、Prompt 与工具引用需已存在。'
            : '仅允许目录内已批准的固定路径、GET/POST 方法与业务 Schema。'
        }}
      </p>
      <el-input v-model="importText" type="textarea" :rows="16" aria-label="导入 JSON" /><el-alert
        v-if="error"
        :title="error"
        type="error"
        :closable="false"
      /><template #footer
        ><el-button type="primary" :loading="busy" @click="importData"
          >验证并导入</el-button
        ></template
      ></el-dialog
    >
    <el-dialog v-model="exportOpen" title="Profile 导出" width="min(680px, 95vw)">
      <pre class="code-block">{{ exportText }}</pre>
      <template #footer
        ><el-button type="primary" @click="download">下载 JSON</el-button></template
      ></el-dialog
    >
  </section>
</template>
