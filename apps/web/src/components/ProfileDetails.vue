<script setup lang="ts">
import type { AgentProfile, KnowledgeBase } from '../api/types'
defineProps<{ profile: AgentProfile; knowledgeBases: KnowledgeBase[] }>()
const roles: Record<string, string> = { admin: '管理员', member: '成员', viewer: '访客' }
</script>

<template>
  <article class="profile-details">
    <h2>{{ profile.name }}</h2>
    <p>{{ profile.description }}</p>
    <dl>
      <dt>助手 ID</dt>
      <dd>{{ profile.profile_id }}</dd>
      <dt>版本 / 状态</dt>
      <dd>v{{ profile.version }} · {{ profile.enabled ? '启用' : '停用' }}</dd>
      <dt>模型服务</dt>
      <dd>{{ profile.provider_id }}</dd>
      <dt>模型</dt>
      <dd>{{ profile.model }}</dd>
      <dt>Temperature</dt>
      <dd>{{ profile.temperature }}</dd>
      <dt>提示词版本</dt>
      <dd>{{ profile.prompt_version_id }}</dd>
      <dt>可用知识库</dt>
      <dd>
        {{
          profile.knowledge_base_ids
            .map((id) => knowledgeBases.find((kb) => kb.knowledge_base_id === id)?.name ?? id)
            .join('、') || '无'
        }}
      </dd>
      <dt>可用工具</dt>
      <dd>{{ profile.tool_ids.join('、') || '无' }}</dd>
      <dt>可用角色</dt>
      <dd>{{ profile.allowed_roles.map((role) => roles[role] ?? role).join('、') }}</dd>
      <dt>回答必须有知识依据</dt>
      <dd>{{ profile.require_evidence ? '是' : '否' }}</dd>
      <dt>低风险只读工具自动执行</dt>
      <dd>{{ profile.auto_approve_read ? '是' : '否' }}</dd>
      <dt>审批策略</dt>
      <dd>{{ profile.approval_policy_id }}</dd>
      <dt>预算策略</dt>
      <dd>{{ profile.budget_policy_id }}</dd>
    </dl>
    <h3>上下文与保留期限</h3>
    <dl>
      <dt>保留消息数</dt>
      <dd>{{ profile.context_policy.last_n }}</dd>
      <dt>上下文长度上限</dt>
      <dd>{{ profile.context_policy.max_characters }}</dd>
      <dt>上下文 token 上限</dt>
      <dd>{{ profile.context_policy.max_tokens }}</dd>
      <dt>会话摘要</dt>
      <dd>{{ profile.context_policy.summarize ? '启用' : '停用' }}</dd>
      <dt>摘要长度</dt>
      <dd>{{ profile.context_policy.summary_characters }}</dd>
      <dt>会话保留时长</dt>
      <dd>{{ profile.context_policy.ttl_seconds }} 秒</dd>
    </dl>
    <h3>每次运行的预算</h3>
    <dl>
      <dt>步骤上限</dt>
      <dd>{{ profile.budgets.max_steps }}</dd>
      <dt>模型调用上限</dt>
      <dd>{{ profile.budgets.max_model_calls }}</dd>
      <dt>工具调用上限</dt>
      <dd>{{ profile.budgets.max_tool_calls }}</dd>
      <dt>总 token 预留上限</dt>
      <dd>{{ profile.budgets.max_tokens }}</dd>
      <dt>执行期限</dt>
      <dd>{{ profile.budgets.deadline_seconds }} 秒</dd>
      <dt>成本上限</dt>
      <dd>
        {{
          profile.budgets.max_cost_microusd === null
            ? '未设置'
            : `${profile.budgets.max_cost_microusd} 微美元`
        }}
      </dd>
    </dl>
    <template v-if="profile.write_preflight">
      <h3>操作前置校验</h3>
      <dl>
        <dt>写入工具</dt>
        <dd>{{ profile.write_preflight.write_tool }}</dd>
        <dt>查询工具</dt>
        <dd>{{ profile.write_preflight.read_tool }}</dd>
        <dt>政策查询</dt>
        <dd>{{ profile.write_preflight.policy_query }}</dd>
      </dl>
      <h4>参数映射</h4>
      <pre class="code-block">{{
        JSON.stringify(profile.write_preflight.argument_map, null, 2)
      }}</pre>
    </template>
  </article>
</template>

<style scoped>
.profile-details {
  color: var(--el-text-color-primary);
  line-height: 1.7;
}
dl {
  display: grid;
  grid-template-columns: minmax(140px, 1fr) minmax(0, 2fr);
  gap: 12px 20px;
}
dt {
  color: var(--el-text-color-secondary);
}
dd {
  margin: 0;
  overflow-wrap: anywhere;
}
h3 {
  margin-top: 28px;
}
@media (max-width: 480px) {
  dl {
    grid-template-columns: 1fr;
    gap: 4px;
  }
  dd {
    margin-bottom: 12px;
  }
}
</style>
