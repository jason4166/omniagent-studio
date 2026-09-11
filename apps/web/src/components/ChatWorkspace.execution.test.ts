import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { expect, it, vi } from 'vitest'
import { ApiClient } from '../api/client'
import type { AgentProfile, Approval, Json, Session } from '../api/types'
import ChatWorkspace from './ChatWorkspace.vue'

const operationId = '12345678-1234-4321-8765-123456789abc'
function setup({
  pending = false,
  failed = false,
  data = { operation_id: operationId, status: 'created' },
}: { pending?: boolean; failed?: boolean; data?: Json } = {}) {
  const api = new ApiClient(vi.fn())
  const session: Session = {
    schema_version: 1,
    thread_id: 'execution-session',
    user_id: 'user',
    profile_id: 'sales',
    profile_version: 1,
    status: pending ? 'awaiting_approval' : 'completed',
    run_id: 'run-one',
    approval_id: 'approval-one',
    message: '记录客户回访',
    error: null,
    history: [
      { role: 'assistant', content: pending ? '请检查待审批的内容。' : '本次操作的结果已记录。' },
    ],
    result: {
      route: 'tool',
      status: failed ? 'failed' : 'succeeded',
      output_text: '本次操作的结果已记录。',
      tool_name: 'create_followup',
      arguments: { customer_id: 'C-100', note: '确认续约需求' },
      tool_result: { status: failed ? 'failed' : 'succeeded', data },
    },
    usage: {
      steps: 1,
      model_calls: 1,
      retrieval_calls: 0,
      tool_calls: pending ? 0 : 1,
      reserved_tokens: 0,
      input_tokens: 10,
      output_tokens: 20,
      total_tokens: 30,
      cost_microusd: null,
    },
  }
  const approval: Approval = {
    approval_id: 'approval-one',
    thread_id: session.thread_id,
    run_id: 'run-one',
    tool_name: 'create_followup',
    arguments: session.result!.arguments!,
    risk: 'medium',
    reason: 'approval',
    status: pending ? 'pending' : failed ? 'failed' : 'executed',
    version: 2,
    expires_at: '2030-01-01T00:00:00Z',
    decision_by: 'user',
    idempotency_key: 'approval-one',
  }
  vi.spyOn(api, 'profiles').mockResolvedValue([
    {
      profile_id: 'sales',
      name: '销售运营助手',
      description: '客户与销售业务',
      provider_id: 'primary',
      model: 'unit-model',
      knowledge_base_ids: [],
      tool_ids: ['create_followup'],
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
      prompt_version_id: 'unit-prompt',
      budget_policy_id: 'standard',
      approval_policy_id: 'safe-default',
    } satisfies AgentProfile,
  ])
  vi.spyOn(api, 'runtimeInfo').mockResolvedValue({
    embedding: { provider: 'primary', model: 'unit-embedding', dimension: 1024, version: 'v1' },
    business_tools: 'local-sandbox',
  })
  vi.spyOn(api, 'sessions').mockResolvedValue([session])
  vi.spyOn(api, 'session').mockResolvedValue(session)
  vi.spyOn(api, 'approval').mockResolvedValue(approval)
  vi.spyOn(api, 'events').mockResolvedValue(undefined)
  const decide = vi.spyOn(api, 'decide')
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
  return { wrapper, decide }
}

it.each([false, true])(
  'keeps full write results in a collapsed execution record; failed=%s',
  async (failed) => {
    const { wrapper, decide } = setup({ failed })
    try {
      await flushPromises()
      await wrapper.find('.session-item').trigger('click')
      await flushPromises()
      const record = wrapper.find('.execution-record')
      expect(record.find('summary').text()).toContain('执行记录')
      expect((record.element as HTMLDetailsElement).open).toBe(false)
      expect(record.text()).toContain(failed ? '执行状态：执行失败' : '执行状态：已完成')
      expect(record.text()).toContain('记录编号')
      expect(record.text()).toContain(operationId)
      expect(record.text()).toContain('C-100')
      expect(record.text()).toContain('确认续约需求')
      expect(wrapper.find('.message-text').text()).not.toContain(operationId)
      expect(wrapper.find('[aria-label="审批请求"]').exists()).toBe(true)
      expect(decide).not.toHaveBeenCalled()
    } finally {
      wrapper.unmount()
      vi.unstubAllGlobals()
    }
  },
)

it('does not show an execution receipt while approval is pending, even with stale result data', async () => {
  const { wrapper, decide } = setup({ pending: true })
  try {
    await flushPromises()
    await wrapper.find('.session-item').trigger('click')
    await flushPromises()
    expect(wrapper.find('.execution-record').exists()).toBe(false)
    expect(wrapper.text()).not.toContain(operationId)
    expect(wrapper.find('[aria-label="审批请求"]').text()).toContain('需要你的审批')
    expect(decide).not.toHaveBeenCalled()
  } finally {
    wrapper.unmount()
    vi.unstubAllGlobals()
  }
})

it('retains non-object JSON data in the execution record', async () => {
  const data: Json = [false, 0, null, '<script>data only</script>']
  const { wrapper } = setup({ data })
  try {
    await flushPromises()
    await wrapper.find('.session-item').trigger('click')
    await flushPromises()
    const record = wrapper.find('.execution-record')
    expect(record.find('pre').text()).toBe(JSON.stringify({ content: data }, null, 2))
    expect(record.find('script').exists()).toBe(false)
  } finally {
    wrapper.unmount()
    vi.unstubAllGlobals()
  }
})
