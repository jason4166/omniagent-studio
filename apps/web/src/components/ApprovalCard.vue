<script setup lang="ts">
import { ref, watch } from 'vue'
import { errorMessage, InputError, parseInputJson } from '../api/errors'
import type { ApiClient } from '../api/client'
import type { Approval, ApprovalDecision, Json, Session } from '../api/types'

const props = defineProps<{ api: ApiClient; approval: Approval }>()
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
      <span class="approval-icon">!</span>
      <div>
        <h3>此操作需要你的审批</h3>
        <p>确认业务参数后执行，编辑后将重新验证权限与风险。</p>
      </div>
      <el-tag type="warning">{{ approval.risk.toUpperCase() }} RISK</el-tag>
    </div>
    <div class="tool-name">
      {{ approval.tool_name }}
      <span class="small">{{ approval.status }} · v{{ approval.version }}</span>
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
      有效期至 {{ new Date(approval.expires_at).toLocaleString() }} · 重复提交使用同一操作标识
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
    <el-alert v-else :title="`审批状态：${approval.status}`" type="info" :closable="false" />
  </section>
</template>
