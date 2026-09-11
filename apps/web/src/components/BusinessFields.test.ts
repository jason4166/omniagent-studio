import { mount } from '@vue/test-utils'
import { expect, it } from 'vitest'
import { toolLabel } from '../api/businessPresentation'
import type { Json } from '../api/types'
import BusinessFields from './BusinessFields.vue'

it.each<{ values: Record<string, Json>; expected: string[] }>([
  {
    values: { serial_number: 'SN-200', covered: false, months: 0 },
    expected: ['设备序列号', 'SN-200', '保修状态', '未在保', '记录保修月数', '0'],
  },
  {
    values: { sku: 'P-200', name: 'Orbit Chair', price: 800, currency: 'CNY' },
    expected: ['产品编号', 'P-200', '名称', 'Orbit Chair', '价格', '800', '人民币（CNY）'],
  },
  {
    values: { customer_id: 'C-200', tier: 'partner' },
    expected: ['客户编号', 'C-200', '客户类型', '合作伙伴'],
  },
])('labels business values without fabricating information: $values', ({ values, expected }) => {
  const wrapper = mount(BusinessFields, { props: { values } })
  for (const text of expected) expect(wrapper.find('dl').text()).toContain(text)
  expect(wrapper.find('dl').text()).not.toMatch(/到期日|剩余保修|保证/)
  expect(wrapper.find('pre').text()).toBe(JSON.stringify(values, null, 2))
  expect((wrapper.find('details').element as HTMLDetailsElement).open).toBe(false)
  wrapper.unmount()
})

it('renders untrusted field names and values as text and keeps unknown data', () => {
  const values = { '<script>key</script>': '<img src=x onerror=alert(1)>', custom_field: false }
  const wrapper = mount(BusinessFields, { props: { values } })
  expect(wrapper.find('dl').text()).toContain('<script>key</script>')
  expect(wrapper.find('dl').text()).toContain('<img src=x onerror=alert(1)>')
  expect(wrapper.find('dl').text()).toContain('custom_field')
  expect(wrapper.find('dl').text()).toContain('否')
  expect(wrapper.find('img').exists()).toBe(false)
  expect(wrapper.find('script').exists()).toBe(false)
  expect(toolLabel('create_followup')).toBe('拟定客户回访记录')
  expect(toolLabel('<script>tool</script>')).toBe('业务操作')
  expect(toolLabel('toString')).toBe('业务操作')
  wrapper.unmount()
})

it('handles empty and nested values while retaining complete raw data', async () => {
  const wrapper = mount(BusinessFields, { props: { values: {} } })
  expect(wrapper.text()).toContain('没有需要展示的信息')
  const values = {
    note: null,
    extra: [{ customer_id: 'C-100' }],
    records: Array.from({ length: 21 }, (_, i) => i),
  }
  await wrapper.setProps({ values })
  expect(wrapper.find('dl').text()).toContain('未提供')
  expect(wrapper.find('dl').text()).toContain('第 1 项：客户编号：C-100')
  expect(wrapper.find('dl').text()).toContain('另有 1 项')
  expect(wrapper.find('pre').text()).toBe(JSON.stringify(values, null, 2))
  wrapper.unmount()
})
