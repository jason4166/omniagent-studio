import type { Json } from './types'

const toolLabels: Record<string, string> = {
  lookup_product: '查询产品资料',
  check_warranty: '查询保修状态',
  'catalog.lookup_product': '通过产品目录查询资料',
  'catalog.resource': '查看产品目录说明',
  lookup_customer: '查询客户资料',
  create_followup: '拟定客户回访记录',
  request_discount: '发起折扣申请',
}
const fieldLabels: Record<string, string> = {
  sku: '产品编号',
  serial_number: '设备序列号',
  name: '名称',
  price: '价格',
  currency: '币种',
  covered: '保修状态',
  months: '记录保修月数',
  customer_id: '客户编号',
  tier: '客户类型',
  operation_id: '记录编号',
  tool: '操作',
  status: '记录状态',
  note: '备注',
  reason: '申请原因',
  percent: '申请折扣（%）',
  content: '内容',
  uri: '资源地址',
  mimeType: '内容格式',
}
const valueLabels: Record<string, Record<string, string>> = {
  currency: { CNY: '人民币（CNY）' },
  covered: { true: '在保', false: '未在保' },
  tier: { standard: '标准客户', partner: '合作伙伴' },
  status: { created: '已创建' },
}

export function toolLabel(name: string): string {
  return Object.hasOwn(toolLabels, name) ? toolLabels[name] : '业务操作'
}

export function fieldLabel(name: string): string {
  return Object.hasOwn(fieldLabels, name) ? fieldLabels[name] : name
}

export function businessValue(value: Json, field = '', depth = 0): string {
  if (value === null) return '未提供'
  if (typeof value !== 'object') {
    if (field === 'tool' && typeof value === 'string') return toolLabel(value)
    const labels = Object.hasOwn(valueLabels, field) ? valueLabels[field] : undefined
    const key = String(value)
    if (labels && Object.hasOwn(labels, key)) return labels[key]
    if (typeof value === 'boolean') return value ? '是' : '否'
    return key || '未填写'
  }
  const entries = Array.isArray(value)
    ? value.map((item, index) => [String(index + 1), item] as const)
    : Object.entries(value)
  if (!entries.length) return '暂无内容'
  if (depth >= 3) return '内容较多，请展开原始数据查看。'
  const lines = entries
    .slice(0, 20)
    .map(
      ([key, item]) =>
        `${Array.isArray(value) ? `第 ${key} 项` : fieldLabel(key)}：${businessValue(item, key, depth + 1)}`,
    )
  if (entries.length > 20) lines.push(`另有 ${entries.length - 20} 项，请展开原始数据查看。`)
  return lines.join('\n')
}
