<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { errorMessage, InputError, parseInputJson } from '../api/errors'
import type { ApiClient } from '../api/client'
import type { Approval, ApprovalDecision, Json, Session } from '../api/types'

const props = defineProps<{ api: ApiClient; approval: Approval }>()
const statusCopy = {
  pending: {
    label: '待审批',
    title: '此操作需要你的审批',
    description: '请先核对业务参数。批准或编辑后，服务端仍会检查权限与风险。',
    icon: '!',
  },
  approved: {
    label: '已批准',
    title: '审批已通过，执行结果待确认',
    description: '已记录批准决定，请查看会话中的最新执行结果。',
    icon: '…',
  },
  executed: {
    label: '已执行',
    title: '操作已执行',
    description: '工具已返回成功结果，请查看会话中的结果记录。',
    icon: '✓',
  },
  rejected: {
    label: '已拒绝',
    title: '此操作已拒绝',
    description: '这项提案未获批准，不会按此提案执行。需要继续时，请重新发起请求。',
    icon: '×',
  },
  expired: {
    label: '已过期',
    title: '审批已过期',
    description: '这项提案已不能批准或编辑。需要继续时，请重新发起请求。',
    icon: '–',
  },
  failed: {
    label: '执行失败',
    title: '工具未返回成功结果',
    description: '请先核对会话与业务记录，再决定是否重新发起请求。',
    icon: '!',
  },
} satisfies Record<
  Approval['status'],
  {
    label: string
    title: string
    description: string
    icon: string
  }
>
const state = computed(() =>
  Object.hasOwn(statusCopy, props.approval.status)
    ? statusCopy[props.approval.status]
    : {
        label: '状态待确认',
        title: '审批状态暂不可用',
        description: '请刷新会话后检查最新状态。',
        icon: '?',
      },
)
const riskLabels: Record<string, string> = { low: '低风险', medium: '中风险', high: '高风险' }
const riskLabel = computed(() =>
  Object.hasOwn(riskLabels, props.approval.risk) ? riskLabels[props.approval.risk] : '风险待确认',
)
const emit = defineEmits<{ completed: [session: Session] }>()
const editing = ref(false)
const editVersion = ref<number | null>(null)
const text = ref('')
const error = ref('')
const busy = ref(false)
const decisions = new Map<string, ApprovalDecision>()
watch(
  () => props.approval,
  (a) => {
    if (!busy.value && !editing.value) text.value = JSON.stringify(a.arguments, null, 2)
  },
  { immediate: true },
)

function toggleEditing() {
  if (busy.value) return
  editing.value = !editing.value
  editVersion.value = editing.value ? props.approval.version : null
  text.value = JSON.stringify(props.approval.arguments, null, 2)
  error.value = ''
}

async function decide(action: ApprovalDecision['action']) {
  if (busy.value || props.approval.status !== 'pending') return
  error.value = ''
  let args: Record<string, Json> | undefined
  try {
    if (action === 'edit') {
      if (editVersion.value !== props.approval.version) throw new InputError('approval_changed')
      const parsed = parseInputJson(text.value)
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed))
        throw new InputError('json_object_required')
      args = parsed as Record<string, Json>
    }
    const fingerprint = JSON.stringify([
      props.approval.approval_id,
      props.approval.version,
      action,
      args,
    ])
    let payload = decisions.get(fingerprint)
    if (!payload) {
      payload = {
        action,
        expected_version: props.approval.version,
        decision_key: crypto.randomUUID(),
        ...(args ? { arguments: args } : {}),
      }
      decisions.set(fingerprint, payload)
    }
    busy.value = true
    const result = await props.api.decide(
      props.approval.thread_id,
      props.approval.approval_id,
      payload,
    )
    emit('completed', result)
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <section class="approval-card" aria-label="审批请求">
    <div class="approval-heading">
      <span class="approval-icon" aria-hidden="true">{{ state.icon }}</span>
      <div>
        <h3>{{ state.title }}</h3>
        <p>{{ state.description }}</p>
      </div>
      <el-tag type="warning">{{ riskLabel }}</el-tag>
    </div>
    <div class="tool-name">
      {{ approval.tool_name }}
      <span class="small">{{ state.label }} · v{{ approval.version }}</span>
    </div>
    <details v-if="approval.preflight" class="preflight-evidence">
      <summary>查看前置查询与政策依据</summary>
      <p class="small">已核对 {{ approval.preflight.read_tool }}；修改关联对象需要重新提案。</p>
      <pre class="code-block">{{ JSON.stringify(approval.preflight.read_result, null, 2) }}</pre>
      <blockquote
        v-for="evidence in approval.preflight.policy_context?.evidence ?? []"
        :key="evidence.citation_label"
      >
        <strong>{{ evidence.citation_label }}</strong>
        <span class="small"> · {{ evidence.source_locator.source_name }}</span>
        <p>{{ evidence.content }}</p>
      </blockquote>
    </details>
    <el-input
      v-if="editing && approval.status === 'pending'"
      v-model="text"
      type="textarea"
      :rows="7"
      aria-label="审批参数 JSON"
      :disabled="busy"
    />
    <pre v-else class="code-block">{{ JSON.stringify(approval.arguments, null, 2) }}</pre>
    <p class="small">
      {{ approval.status === 'pending' ? '有效期至' : '原有效期至' }}
      {{ new Date(approval.expires_at).toLocaleString() }}
    </p>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <div v-if="approval.status === 'pending'" class="action-row">
      <el-button type="primary" :loading="busy" @click="decide(editing ? 'edit' : 'approve')">{{
        editing ? '保存编辑并批准' : '批准执行'
      }}</el-button>
      <el-button :disabled="busy" @click="toggleEditing">{{
        editing ? '取消编辑' : '编辑参数'
      }}</el-button>
      <el-button type="danger" plain :disabled="busy" @click="decide('reject')">拒绝</el-button>
    </div>
    <el-alert v-else :title="`审批状态：${state.label}`" type="info" :closable="false" />
  </section>
</template>
