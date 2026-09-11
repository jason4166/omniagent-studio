<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, shallowRef } from 'vue'
import { ApiClient } from '../api/client'
import { EventCursor } from '../api/events'
import type {
  AgentProfile,
  Approval,
  EventEnvelope,
  ResolvedCitation,
  RuntimeInfo,
  Session,
} from '../api/types'
import ApprovalCard from './ApprovalCard.vue'

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
const error = ref('')
const connection = ref('未连接')
const events = shallowRef<EventEnvelope[]>([])
const liveText = ref('')
const pendingText = ref('')
const citation = shallowRef<ResolvedCitation | null>(null)
const citationOpen = ref(false)
const logOpen = ref(false)
const transcript = ref<HTMLElement>()
const retry = ref<{ id: string; message: string; key: string } | null>(null)
let controller: AbortController | null = null
let cursor: EventCursor | null = null
let epoch = 0
let refreshGeneration = 0
const profile = computed(() => profiles.value.find((p) => p.profile_id === chosen.value))
const visibleSessions = computed(() => sessions.value.filter((s) => s.profile_id === chosen.value))
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
  hr: ['今年有多少天带薪年假？', '差旅住宿费每天最多报销多少？', '月球基地停车费是多少？'],
  support: ['产品查询 P-100', '保修查询 SN-100', 'MCP 查询 P-200'],
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
  error.value = e instanceof Error ? e.message : '请求失败'
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
  epoch++
  const version = epoch
  controller?.abort()
  error.value = ''
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
  epoch++
  chosen.value = id
  current.value = null
  approval.value = null
  retry.value = null
  controller?.abort()
  cursor = null
  connection.value = '未连接'
  error.value = ''
  query.value = ''
  events.value = []
  liveText.value = ''
}
async function create() {
  const session = await props.api.createSession(chosen.value)
  await apply(session)
  connect()
  await refreshList()
  return session
}
async function newSession() {
  if (busy.value) return
  busy.value = true
  error.value = ''
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
  error.value = ''
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
  error.value = ''
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
async function locate(chunk: string) {
  if (!current.value) return
  try {
    citation.value = await props.api.citation(current.value.thread_id, chunk)
    citationOpen.value = true
  } catch (e) {
    showError(e)
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
  controller?.abort()
})
</script>

<template>
  <section class="workspace">
    <div class="page-heading">
      <div>
        <div class="eyebrow">YOUR AGENTS, UNDER CONTROL</div>
        <h1>让每一次回答与行动，都有依据。</h1>
        <p>选择专属助手，查询知识、连接工具，在关键操作前保留你的决定权。</p>
        <p v-if="runtimeInfo" class="runtime-context">
          向量检索：{{ runtimeInfo.embedding.model }} ·
          {{ runtimeInfo.embedding.provider === 'fake' ? '离线测试' : '真实 API' }} ·
          业务操作：本地沙箱
        </p>
      </div>
      <span class="quiet-badge">{{ profiles.length }} AGENT PROFILES</span>
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
          <span>{{ p.knowledge_base_ids.length }} 知识库</span
          ><span>{{ p.tool_ids.length }} 工具</span
          ><span>{{ p.provider_id === 'fake' ? 'Fake 测试' : '真实模型' }}</span>
          <span :title="p.model">{{ p.model }}</span>
        </div>
      </button>
    </div>
    <el-alert
      v-if="error"
      class="error-banner"
      :title="error"
      type="error"
      show-icon
      @close="error = ''"
    />
    <el-empty v-if="!busy && !profiles.length" description="暂无可用 Profile，请联系管理员创建。" />
    <div v-if="profiles.length" class="conversation-grid">
      <aside class="session-panel">
        <div class="panel-heading">
          <h3>会话记录</h3>
          <el-button text type="primary" :disabled="busy" @click="newSession">＋ 新会话</el-button>
        </div>
        <p class="small session-hint">会话在重启后仍可恢复</p>
        <div v-if="!visibleSessions.length" class="muted-empty">
          还没有会话<br />从右侧开始一次对话
        </div>
        <button
          v-for="s in visibleSessions"
          :key="s.thread_id"
          class="session-item"
          :class="{ active: s.thread_id === current?.thread_id }"
          :disabled="busy"
          @click="select(s)"
        >
          <span>{{ s.message || '新会话' }}</span
          ><small>{{ statusLabels[s.status] }} · {{ s.thread_id.slice(0, 8) }}</small>
        </button>
      </aside>
      <section class="chat-panel" aria-label="会话工作区">
        <div class="chat-heading">
          <div>
            <span class="status-dot"></span><strong>{{ profile?.name }}</strong
            ><span class="small">{{ current ? statusLabels[current.status] : '准备就绪' }}</span>
          </div>
          <div class="action-row">
            <el-button size="small" text @click="logOpen = true">事件记录</el-button
            ><el-button v-if="current" size="small" text @click="connect">{{
              connection
            }}</el-button>
          </div>
        </div>
        <div ref="transcript" class="transcript" aria-live="polite">
          <el-alert
            v-if="current?.result?.degraded"
            title="主模型暂不可用，已通过配置的备用模型完成请求。"
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
                  {{ c.source_locator?.source_name || c.source_id.slice(0, 12) }} ↗
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
          <div v-if="current?.result?.tool_name && !approval" class="tool-summary">
            <el-tag type="info">{{ current.result.tool_name }}</el-tag>
            <pre class="code-block">{{ JSON.stringify(current.result.arguments, null, 2) }}</pre>
          </div>
          <ApprovalCard
            v-if="approval"
            :key="approval.approval_id"
            :api="api"
            :approval="approval"
            @completed="approved"
          />
          <el-alert
            v-if="current?.error"
            :title="`运行未完成：${current.error}。恢复仍受原预算与权限约束。`"
            type="error"
            :closable="false"
          />
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
            <span>Ctrl + Enter 发送 · 写操作需要审批</span
            ><span v-if="current"
              >{{ current.usage.model_calls }} 模型 / {{ current.usage.tool_calls }} 工具 ·
              {{ current.usage.total_tokens }}
              {{ profile?.provider_id === 'fake' ? '模拟 token' : 'token' }} ·
              {{
                current.usage.cost_microusd === null
                  ? '成本 unknown'
                  : '$' + (current.usage.cost_microusd / 1000000).toFixed(4)
              }}</span
            >
          </div>
        </div>
      </section>
    </div>
    <el-drawer v-model="citationOpen" title="引用原文" size="min(560px, 95vw)"
      ><template v-if="citation"
        ><el-tag>{{ citation.knowledge_base_id }}</el-tag>
        <p class="small">{{ citation.source_id }}</p>
        <pre class="citation-content">{{ citation.content }}</pre>
        <p class="small">Chunk: {{ citation.chunk_id }}</p>
        <pre class="code-block">{{ JSON.stringify(citation.metadata, null, 2) }}</pre>
      </template></el-drawer
    >
    <el-drawer v-model="logOpen" title="会话事件" size="min(500px, 95vw)"
      ><p class="small">{{ connection }} · 已消费序列 {{ events.at(-1)?.sequence || 0 }}</p>
      <el-empty v-if="!events.length" description="暂无事件" />
      <div v-for="e in events" :key="e.event_id" class="event-row">
        <span class="sequence">{{ e.sequence }}</span>
        <div>
          <strong>{{ e.kind }}</strong>
          <p class="small">{{ e.created_at }}</p>
          <pre class="event-data">{{ JSON.stringify(e.data, null, 2) }}</pre>
        </div>
      </div></el-drawer
    >
  </section>
</template>
