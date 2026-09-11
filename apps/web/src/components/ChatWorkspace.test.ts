import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { describe, expect, it, vi } from 'vitest'
import { ApiClient } from '../api/client'
import type { AgentProfile, Session } from '../api/types'
import ChatWorkspace from './ChatWorkspace.vue'

describe('running cancellation', () => {
  it('can cancel an outstanding send and cannot replace cancellation with a stale response', async () => {
    const api = new ApiClient(vi.fn())
    const session = {
      schema_version: 1,
      thread_id: 'thread',
      user_id: 'user',
      profile_id: 'hr',
      profile_version: 1,
      status: 'ready',
      run_id: null,
      approval_id: null,
      message: '',
      error: null,
      history: [],
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
      result: null,
    } as Session
    vi.spyOn(api, 'profiles').mockResolvedValue([
      {
        profile_id: 'hr',
        name: 'HR',
        description: 'Policies',
        provider_id: 'fake',
        model: 'fake-v1',
        knowledge_base_ids: ['hr-kb'],
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
      } as AgentProfile,
    ])
    vi.spyOn(api, 'runtimeInfo').mockResolvedValue({
      embedding: { model: 'fake', provider: 'fake', dimension: 1024, version: 'v1' },
      business_tools: 'local-sandbox',
    })
    vi.spyOn(api, 'sessions').mockResolvedValue([])
    vi.spyOn(api, 'createSession').mockResolvedValue(session)
    vi.spyOn(api, 'events').mockResolvedValue(undefined)
    let complete: (s: Session) => void = () => undefined
    const send = vi.spyOn(api, 'send').mockImplementation(
      () =>
        new Promise((resolve) => {
          complete = resolve
        }),
    )
    const cancel = vi.spyOn(api, 'cancel').mockResolvedValue({ ...session, status: 'cancelled' })
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
    try {
      await flushPromises()
      await wrapper.find('textarea').setValue('policy')
      const button = (label: string) => {
        const found = wrapper.findAll('button').find((b) => b.text().includes(label))
        if (!found) throw new Error('Missing button: ' + label)
        return found
      }
      await button('发送').trigger('click')
      await flushPromises()
      expect(send).toHaveBeenCalledOnce()
      expect(button('取消会话').attributes('disabled')).toBeUndefined()
      await button('取消会话').trigger('click')
      await flushPromises()
      expect(cancel).toHaveBeenCalledWith('thread')
      complete({ ...session, status: 'running' })
      await flushPromises()
      expect(wrapper.text()).toContain('已取消')
      expect(send).toHaveBeenCalledOnce()
    } finally {
      wrapper.unmount()
      vi.unstubAllGlobals()
    }
  })
})
