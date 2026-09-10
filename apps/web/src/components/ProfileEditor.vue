<script setup lang="ts">
import { ref } from 'vue'
import type {
  AgentProfile,
  KnowledgeBase,
  PromptVersion,
  Provider,
  ToolDefinition,
} from '../api/types'
import type { ApiClient } from '../api/client'

const props = defineProps<{
  api: ApiClient
  profile: AgentProfile
  creating: boolean
  knowledgeBases: KnowledgeBase[]
  tools: ToolDefinition[]
  prompts: PromptVersion[]
  providers: Provider[]
}>()
const emit = defineEmits<{ saved: [] }>()
const draft = ref<AgentProfile>(JSON.parse(JSON.stringify(props.profile)))
const busy = ref(false)
const notice = ref('')
const error = ref('')
async function save(validateOnly = false) {
  busy.value = true
  error.value = ''
  notice.value = ''
  try {
    if (validateOnly) {
      await props.api.validateProfile(draft.value)
      notice.value = '配置验证通过'
    } else {
      if (props.creating) await props.api.createProfile(draft.value)
      else await props.api.saveProfile(draft.value)
      emit('saved')
    }
  } catch (e) {
    error.value = e instanceof Error ? e.message : '配置无效'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <el-form label-position="top" @submit.prevent="save()">
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <el-alert v-if="notice" :title="notice" type="success" :closable="false" />
    <div class="form-grid">
      <el-form-item label="Profile ID"
        ><el-input v-model="draft.profile_id" :disabled="!creating" maxlength="120"
      /></el-form-item>
      <el-form-item label="名称"><el-input v-model="draft.name" maxlength="120" /></el-form-item>
    </div>
    <el-form-item label="用途描述"
      ><el-input v-model="draft.description" type="textarea" maxlength="1000"
    /></el-form-item>
    <div class="form-grid">
      <el-form-item label="Provider 引用"
        ><el-select v-model="draft.provider_id"
          ><el-option
            v-for="p in providers"
            :key="p.provider_id"
            :label="`${p.provider_id} · ${p.configured ? '已配置' : '未配置'}`"
            :value="p.provider_id" /></el-select
      ></el-form-item>
      <el-form-item label="模型"><el-input v-model="draft.model" /></el-form-item>
      <el-form-item label="Prompt 版本"
        ><el-select v-model="draft.prompt_version_id"
          ><el-option
            v-for="p in prompts"
            :key="p.prompt_version_id"
            :label="p.prompt_version_id"
            :value="p.prompt_version_id" /></el-select
      ></el-form-item>
      <el-form-item label="Temperature"
        ><el-input-number v-model="draft.temperature" :min="0" :max="2" :step="0.1"
      /></el-form-item>
    </div>
    <el-form-item label="知识库 allowlist"
      ><el-select v-model="draft.knowledge_base_ids" multiple
        ><el-option
          v-for="kb in knowledgeBases"
          :key="kb.knowledge_base_id"
          :label="kb.name"
          :value="kb.knowledge_base_id" /></el-select
    ></el-form-item>
    <el-form-item label="工具 allowlist"
      ><el-select v-model="draft.tool_ids" multiple
        ><el-option
          v-for="t in tools"
          :key="t.name"
          :label="`${t.name} · ${t.risk} · ${t.requires_approval ? '需审批' : '只读'}`"
          :value="t.name" /></el-select
    ></el-form-item>
    <el-form-item label="可用角色"
      ><el-checkbox-group v-model="draft.allowed_roles"
        ><el-checkbox label="admin" value="admin" /><el-checkbox
          label="member"
          value="member" /><el-checkbox label="viewer" value="viewer" /></el-checkbox-group
    ></el-form-item>
    <div class="form-grid">
      <el-form-item label="启用 Profile"><el-switch v-model="draft.enabled" /></el-form-item>
      <el-form-item label="回答必须有知识依据"
        ><el-switch v-model="draft.require_evidence"
      /></el-form-item>
      <el-form-item label="低风险只读工具自动执行"
        ><el-switch v-model="draft.auto_approve_read"
      /></el-form-item>
      <el-form-item label="审批策略"
        ><el-select v-model="draft.approval_policy_id"
          ><el-option
            value="safe-default"
            label="safe-default · 写入与风险操作强制审批" /></el-select
      ></el-form-item>
    </div>
    <h3>上下文与保留期限</h3>
    <div class="form-grid">
      <el-form-item label="保留消息数"
        ><el-input-number v-model="draft.context_policy.last_n" :min="1" :max="50"
      /></el-form-item>
      <el-form-item label="上下文长度上限"
        ><el-input-number v-model="draft.context_policy.max_characters" :min="1024" :max="32000"
      /></el-form-item>
      <el-form-item label="上下文 token 上限"
        ><el-input-number v-model="draft.context_policy.max_tokens" :min="1024" :max="64000"
      /></el-form-item>
      <el-form-item label="摘要长度"
        ><el-input-number v-model="draft.context_policy.summary_characters" :min="0" :max="2000"
      /></el-form-item>
      <el-form-item label="使用有界摘要"
        ><el-switch v-model="draft.context_policy.summarize"
      /></el-form-item>
      <el-form-item label="会话 TTL（秒）"
        ><el-input-number v-model="draft.context_policy.ttl_seconds" :min="60" :max="604800"
      /></el-form-item>
    </div>
    <h3>每次运行的预算</h3>
    <div class="form-grid">
      <el-form-item label="步骤上限"
        ><el-input-number v-model="draft.budgets.max_steps" :min="2" :max="100"
      /></el-form-item>
      <el-form-item label="模型调用上限"
        ><el-input-number v-model="draft.budgets.max_model_calls" :min="1" :max="12"
      /></el-form-item>
      <el-form-item label="工具调用上限"
        ><el-input-number v-model="draft.budgets.max_tool_calls" :min="0" :max="20"
      /></el-form-item>
      <el-form-item label="总 token 预留上限"
        ><el-input-number v-model="draft.budgets.max_tokens" :min="512" :max="256000"
      /></el-form-item>
      <el-form-item label="执行期限（秒，不含审批等待）"
        ><el-input-number v-model="draft.budgets.deadline_seconds" :min="5" :max="300"
      /></el-form-item>
      <el-form-item label="成本上限（微美元，留空表示不设置）"
        ><el-input-number v-model="draft.budgets.max_cost_microusd" :min="0" :controls="false"
      /></el-form-item>
    </div>
    <p class="small">
      价格 unknown 时不能执行带成本上限的真实 Provider 调用。密钥仅在服务端环境配置。
    </p>
    <div class="action-row sticky-actions">
      <el-button type="primary" native-type="submit" :loading="busy">保存 Profile</el-button
      ><el-button :disabled="busy" @click="save(true)">验证配置</el-button>
    </div>
  </el-form>
</template>
