<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import type { ApiClient } from '../api/client'
import type { AgentProfile, DailyUsage, Session } from '../api/types'

const props = defineProps<{ api: ApiClient; session: Session | null; profile?: AgentProfile }>()
const daily = shallowRef<DailyUsage | null>(null)
const failed = ref(false)
const loading = ref(false)
let disposed = false
let timer: ReturnType<typeof setInterval> | undefined
const labels = { user: '个人', public: '访客共享', global: '平台共享' }
const primary = computed(
  () => daily.value?.scopes.find((s) => s.scope === 'public') ?? daily.value?.scopes[0],
)
const number = (value: number | undefined) =>
  value === undefined ? '—' : value.toLocaleString('zh-CN')
const localTime = (value: string) => new Date(value).toLocaleString('zh-CN', { hour12: false })
const tokenHint = computed(
  () =>
    `本轮模型已返回的输入与输出 token 合计；不含向量检索。预算占用 ${number(props.session?.usage.reserved_tokens)} / ${number(props.profile?.budgets?.max_tokens)} token，包含调用预留。`,
)

async function refresh() {
  if (loading.value || disposed) return
  loading.value = true
  try {
    const result = await props.api.dailyUsage()
    if (!disposed) {
      daily.value = result
      failed.value = false
    }
  } catch {
    if (!disposed) failed.value = true
  } finally {
    loading.value = false
  }
}
function refreshVisible() {
  if (document.visibilityState === 'visible') void refresh()
}
watch(
  () => [props.session?.run_id, props.session?.status, props.session?.usage.total_tokens],
  () => void refresh(),
)
onMounted(() => {
  void refresh()
  timer = setInterval(refreshVisible, 30000)
  document.addEventListener('visibilitychange', refreshVisible)
  window.addEventListener('focus', refreshVisible)
})
onBeforeUnmount(() => {
  disposed = true
  clearInterval(timer)
  document.removeEventListener('visibilitychange', refreshVisible)
  window.removeEventListener('focus', refreshVisible)
})
</script>

<template>
  <div class="usage-summary" aria-label="用量与额度">
    <div v-if="session" class="usage-line">
      <span title="最近一轮请求的已用量 / 上限；不是会话累计提问次数">本轮</span>
      <span title="按调用尝试计数，包含意图判断、生成回答及失败重试，一次提问可能调用多次模型">
        模型调用 {{ number(session.usage.model_calls) }} /
        {{ number(profile?.budgets?.max_model_calls) }} 次
      </span>
      <span>
        工具调用 {{ number(session.usage.tool_calls) }} /
        {{ number(profile?.budgets?.max_tool_calls) }} 次
      </span>
      <span :title="tokenHint">
        {{ number(session.usage.total_tokens) }}
        {{ profile?.provider_id === 'fake' ? '模拟 token' : 'token' }}
      </span>
      <span :title="tokenHint">
        token 预算占用 {{ number(session.usage.reserved_tokens) }} /
        {{ number(profile?.budgets?.max_tokens) }}
      </span>
      <span
        v-if="session.usage.cost_microusd !== null && session.usage.cost_microusd !== undefined"
      >
        ${{ (session.usage.cost_microusd / 1000000).toFixed(4) }}
      </span>
    </div>
    <div v-if="failed" class="usage-line" role="status">
      <span>每日额度暂不可用</span>
      <el-button link size="small" :loading="loading" @click="refresh">重试</el-button>
    </div>
    <div v-else-if="daily?.enabled && primary" class="usage-line">
      <span>今日{{ labels[primary.scope] }}</span>
      <span
        >模型 {{ number(primary.model_calls.used) }} /
        {{ number(primary.model_calls.limit) }} 次</span
      >
      <span title="已结算用量与未结算预留的合计，以此判断剩余额度">
        {{ number(primary.tokens.used) }} / {{ number(primary.tokens.limit) }} token
      </span>
      <el-popover
        placement="top-end"
        width="min(380px, calc(100vw - 32px))"
        trigger="click"
        @show="refresh"
      >
        <template #reference>
          <el-button link size="small" aria-label="查看每日额度详情">额度详情</el-button>
        </template>
        <div class="daily-usage-detail">
          <strong>每日额度 · 已用 / 上限</strong>
          <table>
            <thead>
              <tr>
                <th>范围</th>
                <th>模型调用</th>
                <th>token</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="scope in daily.scopes" :key="scope.scope">
                <th>{{ labels[scope.scope] }}</th>
                <td>
                  {{ number(scope.model_calls.used) }} / {{ number(scope.model_calls.limit) }}
                </td>
                <td>{{ number(scope.tokens.used) }} / {{ number(scope.tokens.limit) }}</td>
              </tr>
            </tbody>
          </table>
          <p>
            模型按调用尝试计数，包含失败重试；一次提问可能调用多次。token
            额度含未结算预留，返回用量后结算。
          </p>
          <p>共享额度由对应范围内的所有用户共同使用；任一额度不足都会限制新调用。</p>
          <p>刷新时间：{{ localTime(daily.measured_at) }}</p>
          <p>重置时间：{{ localTime(daily.resets_at) }}（本地时间）</p>
          <el-button link size="small" :loading="loading" @click="refresh">刷新额度</el-button>
        </div>
      </el-popover>
    </div>
    <div v-else-if="loading && !daily" class="usage-line">正在读取每日额度…</div>
  </div>
</template>

<style scoped>
.usage-summary {
  display: grid;
  gap: 6px;
  margin-left: auto;
  max-width: 100%;
}
.usage-line {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px 12px;
  font-variant-numeric: tabular-nums;
}
.usage-line .el-button {
  font-size: inherit;
  padding: 0;
  height: auto;
}
.daily-usage-detail {
  font-size: 12px;
  line-height: 1.6;
}
.daily-usage-detail table {
  width: 100%;
  margin-top: 12px;
  border-collapse: collapse;
  font-variant-numeric: tabular-nums;
}
.daily-usage-detail th,
.daily-usage-detail td {
  padding: 6px 2px;
  text-align: left;
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.daily-usage-detail p {
  margin: 10px 0 0;
}
</style>
