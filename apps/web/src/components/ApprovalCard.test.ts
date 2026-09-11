import { mount, flushPromises } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { describe, expect, it, vi } from 'vitest'
import { ApiClient, ApiError } from '../api/client'
import type { Approval, Session } from '../api/types'
import ApprovalCard from './ApprovalCard.vue'
const approval: Approval = {
  approval_id: 'a',
  thread_id: 't',
  run_id: 'r',
  tool_name: 'create_followup',
  arguments: { note: '<img src=x onerror=alert(1)>', customer_id: 'C-100' },
  risk: 'medium',
  reason: 'approval',
  status: 'pending',
  version: 1,
  expires_at: '2030-01-01T00:00:00Z',
  decision_by: null,
  idempotency_key: 'a',
}
function setup() {
  const api = new ApiClient(vi.fn())
  const action = vi.spyOn(api, 'decide')
  const wrapper = mount(ApprovalCard, {
    props: { api, approval },
    global: { plugins: [ElementPlus] },
  })
  const button = (text: string) => {
    const found = wrapper.findAll('button').find((b) => b.text() === text)
    if (!found) throw new Error(text)
    return found
  }
  return { action, wrapper, button }
}
describe('approval interaction', () => {
  it('renders prerequisite results and policy text as untrusted text', async () => {
    const { wrapper } = setup()
    await wrapper.setProps({
      approval: {
        ...approval,
        preflight: {
          read_tool: 'lookup_customer',
          read_arguments: { customer_id: 'C-100' },
          read_result: { customer_id: 'C-100', name: '<img src=x onerror=alert(1)>' },
          policy_context: {
            evidence: [
              { citation_label: 'E1', content: '<script>policy</script>', source_locator: {} },
            ],
          },
        },
      },
    })
    expect(wrapper.find('details').text()).toContain('修改关联对象需要重新提案')
    expect(wrapper.find('details').text()).toContain('<script>policy</script>')
    expect(wrapper.find('img').exists()).toBe(false)
    expect(wrapper.find('script').exists()).toBe(false)
    wrapper.unmount()
  })
  it('renders untrusted business text without interpreting HTML', () => {
    const { wrapper } = setup()
    expect(wrapper.find('.tool-name').text()).toContain('拟定客户回访记录')
    expect(wrapper.find('.tool-name').text()).not.toContain('create_followup')
    expect(wrapper.find('.tool-name').text()).not.toContain('v1')
    expect(wrapper.find('.business-field-list').text()).toContain('客户编号')
    expect(wrapper.find('.business-field-list').text()).toContain('C-100')
    expect(wrapper.find('.approval-details').text()).toContain('create_followup')
    expect((wrapper.find('.approval-details').element as HTMLDetailsElement).open).toBe(false)
    expect(wrapper.find('img').exists()).toBe(false)
    expect(wrapper.text()).toContain('<img')
    wrapper.unmount()
  })
  it('rejects invalid edited JSON before sending, then submits edited parameters', async () => {
    const { wrapper, action, button } = setup()
    action.mockResolvedValue({ thread_id: 't' } as Session)
    await button('编辑参数').trigger('click')
    const advanced = wrapper.find('.advanced-editor')
    expect(wrapper.find('[aria-label="审批参数 JSON"]').exists()).toBe(false)
    ;(advanced.element as HTMLDetailsElement).open = true
    await advanced.trigger('toggle')
    await wrapper.find('[aria-label="审批参数 JSON"]').setValue('[]')
    await button('保存编辑并批准').trigger('click')
    await flushPromises()
    expect(action).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('JSON 对象')
    await wrapper
      .find('[aria-label="审批参数 JSON"]')
      .setValue('{"customer_id":"C-100","note":"edited"}')
    await button('保存编辑并批准').trigger('click')
    await flushPromises()
    expect(action.mock.calls[0][2]).toMatchObject({ action: 'edit', arguments: { note: 'edited' } })
    expect(wrapper.emitted('completed')).toHaveLength(1)
    wrapper.unmount()
  })
  it('blocks repeated clicks while pending and preserves the key after response loss', async () => {
    const { wrapper, action, button } = setup()
    let reject: (reason: Error) => void = () => undefined
    action.mockImplementationOnce(
      () =>
        new Promise((_resolve, fail) => {
          reject = fail
        }),
    )
    await button('批准执行').trigger('click')
    await button('批准执行').trigger('click')
    expect(action).toHaveBeenCalledOnce()
    reject(new Error('response lost'))
    await flushPromises()
    action.mockResolvedValue({ thread_id: 't' } as Session)
    await button('批准执行').trigger('click')
    await flushPromises()
    expect(action.mock.calls[0][2]).toEqual(action.mock.calls[1][2])
    wrapper.unmount()
  })
  it.each([false, true])(
    'preserves a draft during refresh; changed version = %s',
    async (changed) => {
      const { wrapper, action, button } = setup()
      action.mockResolvedValue({ thread_id: 't' } as Session)
      await button('编辑参数').trigger('click')
      await wrapper.find('input[aria-label="客户编号"]').setValue('C-200')
      await wrapper.find('textarea[aria-label="备注"]').setValue('draft survives')
      await wrapper.setProps({ approval: { ...approval, version: changed ? 2 : 1 } })
      expect(wrapper.find('textarea').element.value).toContain('draft survives')
      await button('保存编辑并批准').trigger('click')
      await flushPromises()
      if (changed) {
        expect(action).not.toHaveBeenCalled()
        expect(wrapper.text()).toContain('审批版本已变化')
      } else {
        expect(action.mock.calls[0][2]).toMatchObject({
          action: 'edit',
          expected_version: 1,
          arguments: { customer_id: 'C-200', note: 'draft survives' },
        })
      }
      wrapper.unmount()
    },
  )
  it('edits readable fields and preserves zero, false, null and unknown values on submission', async () => {
    const { wrapper, action, button } = setup()
    const arguments_ = {
      customer_id: 'C-100',
      note: 'original',
      percent: 0,
      approved: false,
      extra: null,
      empty: '',
    }
    await wrapper.setProps({ approval: { ...approval, arguments: arguments_ } })
    action.mockRejectedValueOnce(new ApiError('validation_error', 422))
    await button('编辑参数').trigger('click')
    expect(wrapper.find<HTMLInputElement>('input[aria-label="客户编号"]').element.value).toBe(
      'C-100',
    )
    expect(wrapper.find('.el-input-number').exists()).toBe(true)
    expect(wrapper.find('input[type="checkbox"]').exists()).toBe(true)
    expect(wrapper.find('[aria-label="审批参数 JSON"]').exists()).toBe(false)
    await wrapper.find('textarea[aria-label="备注"]').setValue('updated')
    await button('保存编辑并批准').trigger('click')
    await flushPromises()
    const first = action.mock.calls[0][2]
    expect(first).toMatchObject({
      action: 'edit',
      expected_version: 1,
      arguments: { ...arguments_, note: 'updated' },
    })
    expect(wrapper.text()).toContain('输入内容未通过检查')
    expect(wrapper.find<HTMLTextAreaElement>('textarea[aria-label="备注"]').element.value).toBe(
      'updated',
    )
    action.mockResolvedValue({ thread_id: 't' } as Session)
    await button('保存编辑并批准').trigger('click')
    await flushPromises()
    expect(action.mock.calls[1][2]).toEqual(first)
    wrapper.unmount()
  })
  it('keeps nested advanced edits when returning to the form or saving', async () => {
    const { wrapper, action, button } = setup()
    await wrapper.setProps({
      approval: { ...approval, arguments: { customer_id: 'C-100', extra: { flag: false } } },
    })
    await button('编辑参数').trigger('click')
    expect(wrapper.find('[aria-label="审批参数 JSON"]').exists()).toBe(false)
    const advanced = wrapper.find('.advanced-editor')
    ;(advanced.element as HTMLDetailsElement).open = true
    await advanced.trigger('toggle')
    const args = { customer_id: 'C-100', extra: { flag: true }, note: 'nested preserved' }
    await wrapper.find('[aria-label="审批参数 JSON"]').setValue(JSON.stringify(args))
    ;(advanced.element as HTMLDetailsElement).open = false
    await advanced.trigger('toggle')
    action.mockResolvedValue({ thread_id: 't' } as Session)
    await button('保存编辑并批准').trigger('click')
    await flushPromises()
    expect(action.mock.calls[0][2].arguments).toEqual(args)
    wrapper.unmount()
  })
  it.each([
    ['approved', '审批已通过，执行结果待确认', '已批准'],
    ['expired', '审批已过期', '已过期'],
    ['executed', '操作已执行', '已执行'],
    ['rejected', '此操作已拒绝', '已拒绝'],
    ['failed', '操作未返回成功结果', '执行失败'],
  ] as const)(
    'shows the actual %s state without another approval prompt or decision',
    async (status, title, label) => {
      const { wrapper, action } = setup()
      await wrapper.setProps({ approval: { ...approval, status } })
      expect(wrapper.find('h3').text()).toBe(title)
      expect(wrapper.find('.tool-name').text()).toContain(label)
      expect(wrapper.text()).not.toContain('此操作需要你的审批')
      expect(wrapper.text()).not.toContain(status)
      expect(wrapper.findAll('button')).toHaveLength(0)
      expect(action).not.toHaveBeenCalled()
      wrapper.unmount()
    },
  )
  it('replaces pending copy after a rejection without executing or resubmitting it', async () => {
    const { wrapper, action, button } = setup()
    const result = { thread_id: 't', status: 'completed' } as Session
    action.mockResolvedValue(result)
    expect(wrapper.find('h3').text()).toBe('此操作需要你的审批')
    expect(wrapper.find('.tool-name').text()).toContain('待审批')
    expect(wrapper.text()).toContain('中风险')
    await button('拒绝').trigger('click')
    await flushPromises()
    expect(action.mock.calls[0][2]).toMatchObject({ action: 'reject', expected_version: 1 })
    expect(wrapper.emitted('completed')).toEqual([[result]])
    await wrapper.setProps({ approval: { ...approval, status: 'rejected', version: 2 } })
    expect(wrapper.find('h3').text()).toBe('此操作已拒绝')
    expect(wrapper.text()).toContain('不会按此提案执行')
    expect(wrapper.text()).not.toContain('需要你的审批')
    expect(wrapper.findAll('button')).toHaveLength(0)
    expect(action).toHaveBeenCalledOnce()
    wrapper.unmount()
  })
})
