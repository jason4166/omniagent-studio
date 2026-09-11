<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, shallowRef } from 'vue'
import { ApiClient } from '../api/client'
import { EventCursor } from '../api/events'
import { describeError, describeRunError, type UserError } from '../api/errors'
import { citationPresentation } from '../api/citationPresentation'
import { toolLabel } from '../api/businessPresentation'
import type {
  AgentProfile,
  Approval,
  EventEnvelope,
  ResolvedCitation,
  RuntimeInfo,
  Session,
} from '../api/types'
import ApprovalCard from './ApprovalCard.vue'
import BusinessFields from './BusinessFields.vue'

const props = defineProps<{ api: ApiClient }>()
const badges: Record<string, string> = { hr: 'HR', support: 'CX', sales: 'SO' }
const profiles = ref<AgentProfile[]>([])
const runtimeInfo = ref<RuntimeInfo | null>(null)
const sessions = shallowRef<Session[]>([])
const chosen = ref('hr')
const current = shallowRef<Session | null>(null)
const approval = shallowRef<Approval | null>(null)
const query = ref('')
const busy = ref(false)
const cancelling = ref(false)
const error = ref<UserError | null>(null)
const connection = ref('未连接')
const events = shallowRef<EventEnvelope[]>([])
const liveText = ref('')
const pendingText = ref('')
const citation = shallowRef<ResolvedCitation | null>(null)
const citationOpen = ref(false)
const citationLoading = ref(false)
const citationError = ref<UserError | null>(null)
const citationTarget = ref('')
let citationRequest = 0
const logOpen = ref(false)
const transcript = ref<HTMLElement>()
const retry = ref<{ id: string; message: string; key: string } | null>(null)
let controller: AbortController | null = null
let cursor: EventCursor | null = null
let epoch = 0
let refreshGeneration = 0
const profile = computed(() => profiles.value.find((p) => p.profile_id === chosen.value))
const runError = computed(() =>
  current.value?.error ? describeRunError(current.value.error) : null,
)
const visibleSessions = computed(() => sessions.value.filter((s) => s.profile_id === chosen.value))
const citationSource = computed(() => citationPresentation(citation.value?.metadata ?? {}))
const activity = computed(() => events.value.filter((event) => event.kind !== 'message.delta'))
const eventLabels: Record<string, string> = {
  'run.started': '开始处理问题',
  'node.status': '正在处理',
  'citation.added': '已找到参考资料',
  'run.completed': '回答已完成',
  'run.failed': '本次处理未完成',
  'run.cancelled': '会话已取消',
  'approval.required': '等待你的审批',
  'approval.preflight': '已核对操作依据',
  'approval.decided': '审批状态已更新',
}
const statusLabels = {
  ready: '就绪',
  running: '运行中',
  awaiting_approval: '等待审批',
  completed: '已完成',
  failed: '运行失败',
  cancelled: '已取消',
}
const canSend = computed(
  () => !busy.value && (!current.value || ['ready', 'completed'].includes(current.value.status)),
)
const suggestions: Record<string, string[]> = {
  hr: ['今年有多少天带薪年假？', '差旅住宿费每天最多报销多少？', '可以申请远程办公吗？'],
  support: ['了解 P-100 的产品信息', '查询 SN-100 的保修情况', '介绍一下 P-200'],
  sales: [
    '客户查询 C-100',
    '为客户 C-100 创建回访，备注：确认续约需求',
    '为客户 C-100 申请 10% 折扣，原因：年度续约',
  ],
}

async function scroll() {
  await nextTick()
  transcript.value?.scrollTo({ top: transcript.value.scrollHeight, behavior: 'instant' })
}
function showError(e: unknown) {
  error.value = describeError(e)
}
async function refreshList() {
  sessions.value = await props.api.sessions()
}
async function apply(session: Session) {
  if (
    current.value?.thread_id === session.thread_id &&
    current.value.status === 'cancelled' &&
    session.status !== 'cancelled'
  )
    return
  const generation = ++refreshGeneration
  current.value = session
  chosen.value = session.profile_id
  if (session.approval_id) {
    const found = await props.api.approval(session.thread_id, session.approval_id)
    if (
      generation === refreshGeneration &&
      current.value?.thread_id === session.thread_id &&
      current.value.approval_id === found.approval_id
    )
      approval.value = found
  } else approval.value = null
  await scroll()
}
async function refreshCurrent() {
  const id = current.value?.thread_id
  const version = epoch
  if (!id) return
  const generation = ++refreshGeneration
  try {
    const s = await props.api.session(id)
    if (version === epoch && generation === refreshGeneration) await apply(s)
  } catch (e) {
    if (version === epoch && generation === refreshGeneration) showError(e)
  }
}
function receive(e: EventEnvelope) {
  events.value = [...events.value, e].slice(-60)
  if (e.kind === 'run.started') liveText.value = ''
  if (e.kind === 'message.delta' && typeof e.data.text === 'string') liveText.value += e.data.text
  if (e.kind === 'run.cancelled') void refreshCurrent()
  if (e.kind === 'approval.required' || e.kind === 'run.completed' || e.kind === 'run.failed') {
    if (!busy.value) void refreshCurrent()
  }
  void scroll()
}
function connect() {
  controller?.abort()
  if (!current.value) return
  if (cursor?.threadId !== current.value.thread_id)
    cursor = new EventCursor(current.value.thread_id)
  const active = new AbortController()
  controller = active
  connection.value = '连接中'
  void props.api.events(
    cursor,
    active.signal,
    (event) => {
      if (!active.signal.aborted) receive(event)
    },
    (state) => {
      if (!active.signal.aborted) connection.value = state
    },
  )
}
async function select(s: Session) {
  if (busy.value) return
  resetCitation()
  epoch++
  const version = epoch
  controller?.abort()
  error.value = null
  liveText.value = ''
  events.value = []
  retry.value = null
  try {
    const loaded = await props.api.session(s.thread_id)
    if (version !== epoch) return
    await apply(loaded)
    connect()
  } catch (e) {
    showError(e)
  }
}
function choose(id: string) {
  if (busy.value) return
  resetCitation()
  epoch++
  chosen.value = id
  current.value = null
  approval.value = null
  retry.value = null
  controller?.abort()
  cursor = null
  connection.value = '未连接'
  error.value = null
  query.value = ''
  events.value = []
  liveText.value = ''
}
async function create() {
  resetCitation()
  const session = await props.api.createSession(chosen.value)
  await apply(session)
  connect()
  await refreshList()
  return session
}
async function newSession() {
  if (busy.value) return
  busy.value = true
  error.value = null
  try {
    await create()
  } catch (e) {
    showError(e)
  } finally {
    busy.value = false
  }
}
async function send(repeat = false) {
  if (busy.value || (!repeat && (!query.value.trim() || !canSend.value))) return
  busy.value = true
  error.value = null
  liveText.value = ''
  try {
    const session = current.value ?? (await create())
    const operation =
      repeat && retry.value
        ? retry.value
        : { id: session.thread_id, message: query.value.trim(), key: crypto.randomUUID() }
    retry.value = operation
    pendingText.value = operation.message
    query.value = ''
    await apply(await props.api.send(operation.id, operation.message, operation.key))
    retry.value = null
    pendingText.value = ''
    await refreshList()
  } catch (e) {
    showError(e)
    await refreshCurrent()
  } finally {
    busy.value = false
    await scroll()
  }
}
async function action(name: 'resume' | 'cancel' | 'deleteSession') {
  if (!current.value || cancelling.value || (busy.value && name !== 'cancel')) return
  if (name === 'cancel') cancelling.value = true
  else busy.value = true
  error.value = null
  try {
    const s = await props.api[name](current.value.thread_id)
    if (s) await apply(s)
    else choose(chosen.value)
    if (!s) {
      current.value = null
      approval.value = null
      controller?.abort()
      connection.value = '未连接'
    }
    await refreshList()
  } catch (e) {
    showError(e)
  } finally {
    if (name === 'cancel') cancelling.value = false
    else busy.value = false
  }
}
async function approved(s: Session) {
  try {
    await apply(s)
    await refreshList()
  } catch (e) {
    showError(e)
  }
}
function resetCitation() {
  citationRequest++
  citationOpen.value = false
  citation.value = null
  citationError.value = null
  citationLoading.value = false
}
async function locate(chunk: string) {
  if (!current.value) return
  const request = ++citationRequest
  const thread = current.value.thread_id
  citationTarget.value = chunk
  citation.value = null
  citationError.value = null
  citationLoading.value = true
  citationOpen.value = true
  try {
    const found = await props.api.citation(thread, chunk)
    if (request === citationRequest && current.value?.thread_id === thread) citation.value = found
  } catch (e) {
    if (request === citationRequest) citationError.value = describeError(e)
  } finally {
    if (request === citationRequest) citationLoading.value = false
  }
}
onMounted(async () => {
  busy.value = true
  try {
    const [available, info] = await Promise.all([props.api.profiles(), props.api.runtimeInfo()])
    profiles.value = available
    runtimeInfo.value = info
    chosen.value = profiles.value[0]?.profile_id ?? ''
    await refreshList()
  } catch (e) {
    showError(e)
  } finally {
    busy.value = false
  }
})
onBeforeUnmount(() => {
  epoch++
  resetCitation()
  controller?.abort()
})
</script>

<template>
  <section class="workspace">
    <div class="page-heading">
      <div>
        <div class="eyebrow">OMNIAGENT STUDIO</div>
        <h1>今天，有什么可以帮你？</h1>
        <p>查制度、了解产品、处理客户事务。选择一位助手，开始对话。</p>
        <p v-if="runtimeInfo" class="runtime-context">
          当前业务操作使用演示数据，不会发送邮件或修改实际客户记录。
        </p>
      </div>
      <span class="quiet-badge">{{ profiles.length }} 位专属助手</span>
    </div>
    <div class="profile-grid">
      <button
        v-for="(p, i) in profiles"
        :key="p.profile_id"
        class="profile-card"
        :class="{ selected: chosen === p.profile_id }"
        :disabled="busy"
        @click="choose(p.profile_id)"
      >
        <div class="profile-top">
          <span class="agent-avatar" :class="`tone-${i % 3}`">{{
            badges[p.profile_id] || p.name.slice(0, 2)
          }}</span
          ><span class="small">{{ chosen === p.profile_id ? '● 已选择' : '○ 选择' }}</span>
        </div>
        <h2>{{ p.name }}</h2>
        <p>{{ p.description }}</p>
        <div class="profile-meta">
          <span v-if="p.knowledge_base_ids.length">回答可查来源</span>
          <span v-if="p.tool_ids.length">支持业务查询与操作</span>
          <span v-if="p.provider_id === 'fake'">预设示例演示</span>
        </div>
      </button>
    </div>
    <el-alert
      v-if="error"
      class="error-banner"
      :title="error.title"
      type="error"
      show-icon
      @close="error = null"
    >
      <p>{{ error.description }}</p>
      <details v-if="error.code" class="small">
        <summary>错误详情</summary>
        <code>{{ error.code }}</code>
      </details>
    </el-alert>
    <el-empty v-if="!busy && !profiles.length" description="暂无可用助手，请联系管理员。" />
    <div v-if="profiles.length" class="conversation-grid">
      <aside class="session-panel">
        <div class="panel-heading">
          <h3>会话记录</h3>
          <el-button text type="primary" :disabled="busy" @click="newSession">＋ 新会话</el-button>
        </div>
        <p class="small session-hint">选择一段对话，继续聊</p>
        <div v-if="!visibleSessions.length" class="muted-empty">
          还没有会话<br />从右侧开始一次对话
        </div>
        <button
          v-for="s in visibleSessions"
          :key="s.thread_id"
          :data-session-id="s.thread_id"
          class="session-item"
          :class="{ active: s.thread_id === current?.thread_id }"
          :disabled="busy"
          @click="select(s)"
        >
          <span>{{ s.message || '新会话' }}</span
          ><small>{{ statusLabels[s.status] }}</small>
        </button>
      </aside>
      <section class="chat-panel" aria-label="会话工作区">
        <div class="chat-heading">
          <div>
            <span class="status-dot"></span><strong>{{ profile?.name }}</strong
            ><span class="small">{{ current ? statusLabels[current.status] : '准备就绪' }}</span>
          </div>
          <div class="action-row">
            <el-button size="small" text @click="logOpen = true">会话详情</el-button
            ><el-button v-if="current" size="small" text @click="connect">{{
              connection
            }}</el-button>
          </div>
        </div>
        <div ref="transcript" class="transcript" aria-live="polite">
          <el-alert
            v-if="current?.result?.degraded"
            title="服务已自动切换备用通道，本次回答已完成。"
            type="warning"
            :closable="false"
          />
          <div v-if="!current?.history.length && !current?.message && !busy" class="welcome">
            <span class="welcome-mark">✧</span>
            <h2>从一个问题开始</h2>
            <p>{{ profile?.description }}</p>
            <div class="suggestions">
              <button
                v-for="example in suggestions[chosen] || []"
                :key="example"
                @click="query = example"
              >
                {{ example }} <span>↗</span>
              </button>
            </div>
          </div>
          <div
            v-for="(message, i) in current?.history || []"
            :key="i"
            class="message-row"
            :class="message.role"
          >
            <span class="message-avatar">{{ message.role === 'user' ? '你' : 'O' }}</span>
            <div class="message-body">
              <div class="message-label">{{ message.role === 'user' ? '你' : profile?.name }}</div>
              <div class="message-text">{{ message.content }}</div>
              <div v-if="message.role === 'assistant'" class="citation-list">
                <button
                  v-for="c in message.citations ??
                  (i === current!.history.length - 1 ? current?.result?.citations : [])"
                  :key="c.chunk_id"
                  class="citation-chip"
                  @click="locate(c.chunk_id)"
                >
                  {{ c.citation_label }} ·
                  {{ citationPresentation(c.source_locator ?? {}).title }} ↗
                </button>
              </div>
            </div>
          </div>
          <div
            v-if="
              (busy && pendingText) ||
              current?.status === 'awaiting_approval' ||
              current?.status === 'failed'
            "
            class="message-row user"
          >
            <span class="message-avatar">你</span>
            <div class="message-body">
              <div class="message-label">你</div>
              <div class="message-text">{{ pendingText || current?.message }}</div>
            </div>
          </div>
          <div v-if="busy" class="message-row streaming">
            <span class="message-avatar">O</span>
            <div class="message-body">
              <div class="message-label">处理中 <span class="loading-dots">•••</span></div>
              <div class="message-text">{{ liveText || '正在检索与验证…' }}</div>
            </div>
          </div>
          <details v-if="current?.result?.tool_name && !approval" class="tool-summary">
            <summary>{{ toolLabel(current.result.tool_name) }} · 查看操作详情</summary>
            <BusinessFields :values="current.result.arguments ?? {}" />
          </details>
          <ApprovalCard
            v-if="approval"
            :key="approval.approval_id"
            :api="api"
            :approval="approval"
            @completed="approved"
          />
          <el-alert
            v-if="runError"
            :title="runError.title"
            type="error"
            :closable="false"
            class="run-error"
          >
            <p>{{ runError.description }}</p>
            <details v-if="runError.code" class="small">
              <summary>错误详情</summary>
              <code>{{ runError.code }}</code>
            </details>
          </el-alert>
        </div>
        <div class="composer">
          <div
            v-if="
              current &&
              (busy || ['failed', 'running', 'awaiting_approval'].includes(current.status))
            "
            class="action-row recovery"
          >
            <el-button size="small" :disabled="busy" @click="action('resume')">恢复会话</el-button
            ><el-button
              size="small"
              :loading="cancelling"
              :disabled="current.status === 'cancelled'"
              @click="action('cancel')"
              >取消会话</el-button
            >
          </div>
          <div v-if="retry" class="action-row recovery">
            <span class="small">上次请求尚未确认</span
            ><el-button size="small" :disabled="busy" @click="send(true)">重试原请求</el-button>
          </div>
          <div class="composer-field">
            <el-input
              v-model="query"
              type="textarea"
              :autosize="{ minRows: 2, maxRows: 5 }"
              :maxlength="8000"
              aria-label="消息"
              placeholder="输入你的问题，或选择上方示例…"
              :disabled="!canSend"
              @keydown.ctrl.enter.prevent="send()"
            /><el-button
              type="primary"
              :loading="busy"
              :disabled="!canSend || !query.trim()"
              @click="send()"
              >发送 ↗</el-button
            >
          </div>
          <div class="composer-footer">
            <span>Ctrl + Enter 发送 · 写操作需要审批</span>
            <span v-if="current" class="usage-summary">
              {{ current.usage.model_calls }} 次模型调用 / {{ current.usage.tool_calls }} 次工具调用
              ·
              {{ current.usage.total_tokens }}
              {{ profile?.provider_id === 'fake' ? '模拟 token' : 'token' }} ·
              {{
                current.usage.cost_microusd === null
                  ? '成本未知'
                  : '$' + (current.usage.cost_microusd / 1000000).toFixed(4)
              }}
            </span>
          </div>
        </div>
      </section>
    </div>
    <el-drawer
      v-model="citationOpen"
      title="引用原文"
      size="min(600px, 95vw)"
      @close="resetCitation"
    >
      <el-skeleton v-if="citationLoading" :rows="5" animated aria-label="正在加载原文" />
      <div v-else-if="citationError" role="alert" class="citation-error">
        <h2>暂时无法打开原文</h2>
        <p>{{ citationError.description }}</p>
        <el-button @click="locate(citationTarget)">重试加载</el-button>
      </div>
      <article v-else-if="citation" class="citation-document" aria-label="引用资料">
        <div class="eyebrow">回答依据</div>
        <h2>{{ citationSource.title }}</h2>
        <div class="citation-location">
          <span v-if="citationSource.filename">{{ citationSource.filename }}</span>
          <span v-if="citationSource.page">第 {{ citationSource.page }} 页</span>
        </div>
        <p class="citation-note">以下为这条回答引用的原文片段。</p>
        <blockquote class="citation-content">{{ citation.content }}</blockquote>
      </article>
    </el-drawer>
    <el-drawer v-model="logOpen" title="会话详情" size="min(500px, 95vw)">
      <p class="small">{{ connection }}</p>
      <h3>处理进度</h3>
      <el-empty v-if="!activity.length" description="开始对话后，可以在这里查看处理进度。" />
      <div v-for="e in activity" :key="e.event_id" class="event-row">
        <span class="status-dot"></span>
        <div>
          <strong>{{ eventLabels[e.kind] || '会话状态已更新' }}</strong>
          <p class="small">{{ e.created_at }}</p>
        </div>
      </div>
    </el-drawer>
  </section>
</template>
