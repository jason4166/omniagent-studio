import { test, expect, type Page } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
const credentialDir =
  process.env.OMNIAGENT_CREDENTIAL_DIR ??
  resolve(
    '../../.local/deployments/' +
      (process.env.COMPOSE_PROJECT_NAME ?? 'omniagent-test-public-fake'),
  )
async function loginPage(page: Page, role = 'member') {
  const account = JSON.parse(readFileSync(resolve(credentialDir, role + '.json'), 'utf8'))
  await page.getByRole('textbox', { name: '账号', exact: true }).fill(account.username)
  await page.getByLabel('密码', { exact: true }).fill(account.password)
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await expect(page.locator('.profile-card')).toHaveCount(3)
}
async function mutationHeaders(page: Page) {
  const me = await page.request.get('/api/auth/me')
  return { 'X-CSRF-Token': (await me.json()).csrf_token, Origin: new URL(page.url()).origin }
}

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
  await loginPage(page)
})
test.afterEach(async ({ page }) => {
  const request = page.request
  for (const id of created.splice(0)) {
    const response = await request.delete(`/api/sessions/${id}`, {
      headers: await mutationHeaders(page),
    })
    expect([204, 404]).toContain(response.status())
  }
})

test('HR citations, locator and abstention render in the actual browser', async ({ page }) => {
  await expect(page.locator('.workspace')).not.toContainText(/真实模型|真实\s*API|向量检索：/)
  await choose(page, 'HR 制度助手')
  await send(page, '年假 leave allowance')
  await expect(page.locator('.citation-chip')).toHaveCount(1)
  await expect(page.locator('.message-row.assistant')).toContainText('10')
  await expect(page.locator('.composer-footer')).toContainText(/\d+\s+(?:模拟 )?token/)
  await page.locator('.citation-chip').click()
  await expect(page.getByRole('heading', { name: '引用原文' })).toBeVisible()
  await expect(page.locator('.citation-content')).toContainText('10')
  await expect(page.getByLabel('引用资料')).toContainText('年假')
  await expect(page.getByLabel('引用资料')).not.toContainText('chunk_size')
  await expect(page.getByLabel('引用资料')).not.toContainText('checksum')
  await expect(page.getByLabel('引用资料')).not.toContainText('Chunk:')
  await page.keyboard.press('Escape')
  await send(page, '银河联邦总统薪酬')
  await expect(page.locator('.message-row.assistant')).toHaveCount(2)
  await expect(page.locator('.message-row.assistant').last()).toContainText('没有足够依据')
  await expect(page.locator('.citation-chip')).toHaveCount(1)
  const session = await page.locator('.session-item.active').getAttribute('data-session-id')
  await page.reload()
  await page.locator(`.session-item[data-session-id="${session}"]`).click()
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
  context,
}) => {
  const request = page.request
  await choose(page, '销售运营助手')
  await send(page, '为客户 C-100 创建回访，备注：确认续约需求')
  await expect(page.getByLabel('审批请求')).toBeVisible()
  const id = created.at(-1)!
  await page.screenshot({ path: 'test-results/approval.png', fullPage: true })
  await page.reload()
  await choose(page, '销售运营助手')
  await page.locator(`.session-item[data-session-id="${id}"]`).click()
  await expect(page.getByLabel('审批请求')).toBeVisible()
  await page.getByRole('button', { name: '编辑参数', exact: true }).click()
  await expect(page.getByRole('textbox', { name: '审批参数 JSON' })).toHaveCount(0)
  await page.getByRole('textbox', { name: '备注', exact: true }).fill('Browser verified follow-up')
  const decision = page.waitForRequest(
    (r) => r.method() === 'POST' && r.url().includes('/approvals/'),
  )
  await page.getByRole('button', { name: '保存编辑并批准' }).click()
  const first = await decision
  await expect(page.locator('.message-row.assistant')).toContainText('记录状态：已创建')
  await expect(page.getByLabel('审批请求')).toContainText('Browser verified follow-up')
  const repeat = await request.post(first.url(), {
    headers: await mutationHeaders(page),
    data: first.postDataJSON(),
  })
  expect(repeat.status()).toBe(200)
  const repeated = await repeat.json()
  expect(repeated.usage.tool_calls).toBe(1)
  expect(repeated.result.tool_result.data.status).toBe('created')
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
    headers: await mutationHeaders(page),
  })
  expect((await result.json()).usage.tool_calls).toBe(1)
})

test('administrator can validate configuration and inspect connector risk', async ({ page }) => {
  await page.getByRole('button', { name: '退出登录', exact: true }).click()
  await loginPage(page, 'admin')
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

test('browser identity comes from the server and logout revokes access', async ({ page }) => {
  await expect(page.getByRole('combobox', { name: '开发身份' })).toHaveCount(0)
  await page.evaluate(() => localStorage.setItem('role', 'admin'))
  await page.reload()
  await expect(page.locator('.profile-card')).toHaveCount(3)
  await expect(page.getByRole('button', { name: '账号与访问' })).toHaveCount(0)
  expect(
    (
      await page.request.get('/api/accounts', {
        headers: { Authorization: 'Bearer local-demo-admin' },
      })
    ).status(),
  ).toBe(403)
  await page.getByRole('button', { name: '退出登录', exact: true }).click()
  await expect(page.getByRole('button', { name: '登录', exact: true })).toBeVisible()
  expect((await page.request.get('/api/sessions')).status()).toBe(401)
})
