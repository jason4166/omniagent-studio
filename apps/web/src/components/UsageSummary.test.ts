import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { expect, it, vi } from 'vitest'
import { ApiClient } from '../api/client'
import type { AgentProfile, DailyUsage, Session } from '../api/types'
import UsageSummary from './UsageSummary.vue'

const daily: DailyUsage = {
  enabled: true,
  measured_at: '2026-09-21T12:00:00Z',
  resets_at: '2026-09-22T00:00:00Z',
  scopes: [
    { scope: 'user', model_calls: { used: 2, limit: 100 }, tokens: { used: 7484, limit: 500000 } },
    {
      scope: 'public',
      model_calls: { used: 8, limit: 200 },
      tokens: { used: 30000, limit: 1000000 },
    },
  ],
}
const session = {
  run_id: 'first-run',
  status: 'completed',
  usage: {
    model_calls: 2,
    tool_calls: 0,
    total_tokens: 7484,
    reserved_tokens: 16000,
    cost_microusd: null,
  },
} as Session
const profile = {
  provider_id: 'primary',
  budgets: { max_model_calls: 4, max_tool_calls: 4, max_tokens: 64000 },
} as AgentProfile

it('separates per-run usage from shared daily quota and replaces the previous run count', async () => {
  const api = new ApiClient(vi.fn())
  vi.spyOn(api, 'dailyUsage').mockResolvedValue(daily)
  const wrapper = mount(UsageSummary, {
    props: { api, session, profile },
    global: { plugins: [ElementPlus] },
  })
  try {
    await flushPromises()
    expect(wrapper.text()).toContain('本轮')
    expect(wrapper.text()).toContain('模型调用 2 / 4 次')
    expect(wrapper.text()).toContain('7,484 token')
    expect(wrapper.text()).toContain('token 预算占用 16,000 / 64,000')
    expect(wrapper.text()).toContain('今日访客共享')
    expect(wrapper.text()).toContain('模型 8 / 200 次')
    expect(wrapper.text()).toContain('30,000 / 1,000,000 token')
    expect(wrapper.text()).not.toContain('成本未知')
    await wrapper.setProps({
      session: { ...session, run_id: 'next-run', usage: { ...session.usage, model_calls: 1 } },
    })
    await flushPromises()
    expect(wrapper.text()).toContain('模型调用 1 / 4 次')
    expect(wrapper.text()).not.toContain('模型调用 3 / 4 次')
    expect(wrapper.find('[title*="预算占用"]').attributes('title')).toContain('16,000 / 64,000')
  } finally {
    wrapper.unmount()
  }
})

it('does not present a stale or zero daily balance when a refresh fails', async () => {
  const api = new ApiClient(vi.fn())
  const usage = vi
    .spyOn(api, 'dailyUsage')
    .mockResolvedValueOnce(daily)
    .mockRejectedValueOnce(new Error('offline'))
  const wrapper = mount(UsageSummary, {
    props: { api, session, profile },
    global: { plugins: [ElementPlus] },
  })
  try {
    await flushPromises()
    await wrapper.setProps({ session: { ...session, run_id: 'another-run' } })
    await flushPromises()
    expect(usage).toHaveBeenCalledTimes(2)
    expect(wrapper.text()).toContain('每日额度暂不可用')
    expect(wrapper.text()).not.toContain('今日访客共享')
    expect(wrapper.text()).toContain('7,484 token')
  } finally {
    wrapper.unmount()
  }
})
