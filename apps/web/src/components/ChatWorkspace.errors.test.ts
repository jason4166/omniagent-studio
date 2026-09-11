import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { expect, it, vi } from 'vitest'
import { ApiClient, ApiError } from '../api/client'
import type { AgentProfile, Session } from '../api/types'
import ChatWorkspace from './ChatWorkspace.vue'

const profile: AgentProfile = {
  profile_id: 'hr',
  name: 'HR 制度助手',
  description: '制度问答',
  provider_id: 'fake',
  model: 'fake',
  knowledge_base_ids: [],
  tool_ids: [],
  version: 1,
  enabled: true,
  temperature: 0,
  allowed_roles: ['member'],
  auto_approve_read: true,
  require_evidence: true,
  context_policy: {
    last_n: 6,
    max_characters: 8000,
    max_tokens: 8000,
    summarize: true,
    summary_characters: 1000,
    ttl_seconds: 3600,
  },
  budgets: {
    max_steps: 24,
    max_model_calls: 4,
    max_tool_calls: 4,
    max_tokens: 64000,
    max_cost_microusd: null,
    deadline_seconds: 120,
  },
  prompt_version_id: 'hr-v1',
  budget_policy_id: 'standard',
  approval_policy_id: 'safe-default',
}

function setup(code: string, failRequest = false) {
  const api = new ApiClient(vi.fn())
  const session: Session = {
    schema_version: 1,
    thread_id: 'failed-thread',
    user_id: 'user',
    profile_id: 'hr',
    profile_version: 1,
    status: 'failed',
    run_id: 'run',
    approval_id: null,
    message: '差旅报销标准',
    error: code,
    history: [],
    result: null,
    usage: {
      steps: 0,
      model_calls: 0,
      retrieval_calls: 0,
      tool_calls: 0,
      reserved_tokens: 0,
      input_tokens: 0,
      output_tokens: 0,
      total_tokens: 0,
      cost_microusd: 0,
    },
  }
  const profiles = vi.spyOn(api, 'profiles').mockResolvedValue([profile])
  if (failRequest) profiles.mockRejectedValue(new ApiError(code, 503))
  vi.spyOn(api, 'sessions').mockResolvedValue([session])
  vi.spyOn(api, 'session').mockResolvedValue(session)
  vi.spyOn(api, 'events').mockResolvedValue(undefined)
  const resume = vi.spyOn(api, 'resume')
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  )
  HTMLElement.prototype.scrollTo = vi.fn()
  const wrapper = mount(ChatWorkspace, { props: { api }, global: { plugins: [ElementPlus] } })
  return { wrapper, resume }
}

it.each([
  ['invalid_dependency_response', '暂时无法处理本次回复', '恢复会话'],
  ['dependency_timeout', '服务响应超时', '恢复会话'],
  ['budget_exhausted', '本次运行的额度或时限已用尽', '缩小请求范围'],
  ['permission_denied', '当前账号无法执行此操作', '检查访问权限'],
  ['raw_exception_private_detail', '暂时无法完成此操作', '检查当前状态'],
])(
  'renders persisted %s with readable guidance and collapsed known-code details',
  async (code, title, guidance) => {
    const { wrapper, resume } = setup(code)
    try {
      await flushPromises()
      await wrapper.find('.session-item').trigger('click')
      await flushPromises()
      const alert = wrapper.find('.run-error')
      expect(alert.find('.el-alert__title').text()).toBe(title)
      expect(alert.text()).toContain(guidance)
      expect(alert.find('.el-alert__title').text()).not.toContain(code)
      if (code === 'raw_exception_private_detail') {
        expect(alert.text()).not.toContain(code)
        expect(alert.find('details').exists()).toBe(false)
      } else {
        expect(alert.find('details code').text()).toBe(code)
        expect((alert.find('details').element as HTMLDetailsElement).open).toBe(false)
      }
      expect(resume).not.toHaveBeenCalled()
    } finally {
      wrapper.unmount()
      vi.unstubAllGlobals()
    }
  },
)

it('uses the same friendly mapping for request failures', async () => {
  const { wrapper } = setup('invalid_dependency_response', true)
  try {
    await flushPromises()
    const alert = wrapper.find('.error-banner')
    expect(alert.find('.el-alert__title').text()).toBe('暂时无法处理本次回复')
    expect(alert.text()).toContain('请稍后重试')
    expect((alert.find('details').element as HTMLDetailsElement).open).toBe(false)
  } finally {
    wrapper.unmount()
    vi.unstubAllGlobals()
  }
})
