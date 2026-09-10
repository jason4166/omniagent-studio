import { test, expect, type Page } from '@playwright/test'

async function choose(page: Page, name: string) {
  await page.locator('.profile-card').filter({ hasText: name }).click()
}
async function send(page: Page, text: string) {
  await page.getByRole('textbox', { name: '消息', exact: true }).fill(text)
  await page.getByRole('button', { name: '发送 ↗', exact: true }).click()
}
const created: string[] = []
test.beforeEach(async ({ page }) => {
  page.on('response', async (response) => {
    if (
      response.request().method() === 'POST' &&
      response.url().endsWith('/api/sessions') &&
      response.status() === 201
    )
      created.push((await response.json()).thread_id)
  })
  await page.goto('/')
  await expect(page.locator('.profile-card')).toHaveCount(3)
})
test.afterEach(async ({ request }) => {
  for (const id of created.splice(0)) {
    const response = await request.delete(`/api/sessions/${id}`, {
      headers: { Authorization: 'Bearer local-demo-member' },
    })
    expect([204, 404]).toContain(response.status())
  }
})

test('HR citations, locator and abstention render in the actual browser', async ({ page }) => {
  await choose(page, 'HR 制度助手')
  await send(page, '年假 leave allowance')
  await expect(page.locator('.citation-chip')).toHaveCount(1)
  await expect(page.locator('.message-row.assistant')).toContainText('10')
  await page.locator('.citation-chip').click()
  await expect(page.getByRole('heading', { name: '引用原文' })).toBeVisible()
  await expect(page.locator('.citation-content')).toContainText('10')
  await page.keyboard.press('Escape')
  await send(page, '银河联邦总统薪酬')
  await expect(page.locator('.message-row.assistant')).toHaveCount(2)
  await expect(page.locator('.message-row.assistant').last()).toContainText('没有足够依据')
  await expect(page.locator('.citation-chip')).toHaveCount(1)
  const session = await page.locator('.session-item.active small').innerText()
  await page.reload()
  await page
    .locator('.session-item')
    .filter({ hasText: session.split('·')[1]!.trim() })
    .click()
  await expect(page.locator('.citation-chip')).toHaveCount(1)
  await page.locator('.citation-chip').click()
  await expect(page.locator('.citation-content')).toContainText('10')
  await page.keyboard.press('Escape')
  await expect(page.getByRole('heading', { name: '引用原文' })).not.toBeVisible()
  await page.screenshot({ path: 'test-results/hr.png', fullPage: true })
})

test('read-only HTTP and MCP tools execute without approval', async ({ page }) => {
  await choose(page, '产品支持助手')
  await send(page, '产品查询 P-100')
  await expect(page.locator('.message-row.assistant')).toContainText('Atlas Desk')
  await expect(page.getByLabel('审批请求')).toHaveCount(0)
  await send(page, 'MCP 查询 P-200')
  await expect(page.locator('.message-row.assistant').last()).toContainText('Orbit Chair')
})

test('sales approval survives reload, edit, duplicate decision and SSE reconnect', async ({
  page,
  request,
  context,
}) => {
  await choose(page, '销售运营助手')
  await send(page, '为客户 C-100 创建回访，备注：确认续约需求')
  await expect(page.getByLabel('审批请求')).toBeVisible()
  const id = created.at(-1)!
  await page.screenshot({ path: 'test-results/approval.png', fullPage: true })
  await page.reload()
  await choose(page, '销售运营助手')
  await page
    .locator('.session-item')
    .filter({ hasText: id.slice(0, 8) })
    .click()
  await expect(page.getByLabel('审批请求')).toBeVisible()
  await page.getByRole('button', { name: '编辑参数', exact: true }).click()
  await page
    .getByRole('textbox', { name: '审批参数 JSON' })
    .fill('{"customer_id":"C-100","note":"Browser verified follow-up"}')
  const decision = page.waitForRequest(
    (r) => r.method() === 'POST' && r.url().includes('/approvals/'),
  )
  await page.getByRole('button', { name: '保存编辑并批准' }).click()
  const first = await decision
  await expect(page.locator('.message-row.assistant')).toContainText('created')
  await expect(page.getByLabel('审批请求')).toContainText('Browser verified follow-up')
  const repeat = await request.post(first.url(), {
    headers: { Authorization: 'Bearer local-demo-member' },
    data: first.postDataJSON(),
  })
  expect(repeat.status()).toBe(200)
  expect((await repeat.json()).usage.tool_calls).toBe(1)
  const mutations: string[] = []
  page.on('request', (r) => {
    if (r.method() === 'POST') mutations.push(r.url())
  })
  await context.setOffline(true)
  await page.getByRole('button', { name: '已连接', exact: true }).click()
  await context.setOffline(false)
  await expect(page.getByRole('button', { name: '已连接', exact: true })).toBeVisible()
  expect(mutations).toEqual([])
  const result = await request.get(`/api/sessions/${id}`, {
    headers: { Authorization: 'Bearer local-demo-member' },
  })
  expect((await result.json()).usage.tool_calls).toBe(1)
})

test('administrator can validate configuration and inspect connector risk', async ({ page }) => {
  await page.getByRole('combobox', { name: '开发身份' }).press('Enter')
  await page.getByText('管理员 · Admin', { exact: true }).click()
  await page.getByRole('button', { name: '配置与管理' }).click()
  await expect(page.getByRole('heading', { name: 'Agent Profiles', exact: true })).toBeVisible()
  await page
    .getByRole('row')
    .filter({ hasText: 'HR 制度助手' })
    .getByRole('button', { name: '编辑', exact: true })
    .click()
  await page.getByRole('button', { name: '验证配置', exact: true }).click()
  await expect(page.getByText('配置验证通过', { exact: true })).toBeVisible()
  await page.keyboard.press('Escape')
  await page.getByRole('tab', { name: '工具与连接器' }).click()
  await expect(page.getByRole('row').filter({ hasText: 'request_discount' })).toContainText('high')
  await expect(page.getByRole('row').filter({ hasText: 'request_discount' })).toContainText(
    '需要审批',
  )
  await page.screenshot({ path: 'test-results/admin.png', fullPage: true })
})
