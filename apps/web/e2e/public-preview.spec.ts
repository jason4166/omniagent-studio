import { test as base, expect, type Page, type Response } from '@playwright/test'

interface Visitor {
  page: Page
  created: Set<string>
  userId: string
  stopTracking: () => void
}

async function mutationHeaders(page: Page) {
  const response = await page.request.get('/api/auth/me')
  expect(response.status()).toBe(200)
  return { 'X-CSRF-Token': (await response.json()).csrf_token, Origin: new URL(page.url()).origin }
}

async function enter(page: Page): Promise<Visitor> {
  const created = new Set<string>()
  const track = async (response: Response) => {
    if (
      response.request().method() === 'POST' &&
      new URL(response.url()).pathname === '/api/sessions' &&
      response.status() === 201
    )
      created.add((await response.json()).thread_id)
  }
  page.on('response', track)
  await page.goto('/')
  await expect(page.getByRole('textbox', { name: '账号', exact: true })).toHaveValue(/\S+/)
  await expect(page.getByLabel('密码', { exact: true })).toHaveValue(/\S+/)
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await expect(page.locator('.profile-card')).toHaveCount(3)
  const identity = await page.request.get('/api/auth/me')
  expect(identity.status()).toBe(200)
  const { user } = await identity.json()
  expect(user.role).toBe('reviewer')
  expect(user.is_public_guest).toBe(true)
  return { page, created, userId: user.user_id, stopTracking: () => page.off('response', track) }
}

async function leave(visitor: Visitor) {
  visitor.stopTracking()
  const headers = await mutationHeaders(visitor.page)
  for (const id of visitor.created) {
    const response = await visitor.page.request.delete(`/api/sessions/${id}`, { headers })
    expect([204, 404]).toContain(response.status())
  }
  expect((await visitor.page.request.post('/api/auth/logout', { headers })).status()).toBe(204)
}

const test = base.extend<{ visitor: Visitor; otherVisitor: Visitor }>({
  visitor: async ({ page }, use) => {
    const visitor = await enter(page)
    try {
      await use(visitor)
    } finally {
      await leave(visitor)
    }
  },
  otherVisitor: async ({ browser, baseURL }, use) => {
    const context = await browser.newContext({ baseURL })
    try {
      const visitor = await enter(await context.newPage())
      try {
        await use(visitor)
      } finally {
        await leave(visitor)
      }
    } finally {
      await context.close()
    }
  },
})

async function choose(page: Page, name: string) {
  await page.locator('.profile-card').filter({ hasText: name }).click()
}
async function send(page: Page, message: string) {
  await page.getByRole('textbox', { name: '消息', exact: true }).fill(message)
  await page.getByRole('button', { name: '发送 ↗', exact: true }).click()
}

test('public login opens complete read-only management without privileged controls', async ({
  visitor,
}) => {
  const { page } = visitor
  await expect(page.locator('.environment-badge')).toHaveText('管理只读')
  await expect(page.getByRole('button', { name: '修改密码', exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '账号与访问', exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: '配置与管理' }).click()
  await expect(page.getByRole('heading', { name: '助手列表', exact: true })).toBeVisible()
  await expect(page.getByRole('tab', { name: '审计', exact: true })).toHaveCount(0)
  for (const name of [
    '创建助手',
    '导入 JSON',
    '创建知识库',
    '导入 OpenAPI 子集',
    '创建版本',
    '保存助手',
    '保存工具',
  ]) {
    await expect(page.getByRole('button', { name, exact: true })).toHaveCount(0)
  }
  await expect(page.getByLabel('上传文档', { exact: true })).toHaveCount(0)

  const hr = page.getByRole('row').filter({ hasText: 'HR 制度助手' })
  await hr.getByRole('button', { name: '查看', exact: true }).click()
  await expect(page.getByRole('heading', { name: '助手详情', exact: true })).toBeVisible()
  await expect(page.locator('.profile-details')).toContainText('员工制度')
  await expect(page.locator('.profile-details')).toContainText('上下文与保留期限')
  await expect(page.locator('.profile-details')).toContainText('每次运行的预算')
  await expect(page.locator('.profile-details input')).toHaveCount(0)
  await page.keyboard.press('Escape')
  await hr.getByRole('button', { name: '导出', exact: true }).click()
  await expect(page.getByRole('heading', { name: '导出助手配置', exact: true })).toBeVisible()
  await expect(page.getByRole('dialog').locator('.code-block')).toContainText('knowledge_base_ids')
  await page.keyboard.press('Escape')

  await page.getByRole('tab', { name: '知识库', exact: true }).click()
  await page
    .locator('.el-select')
    .filter({ has: page.getByRole('combobox', { name: '选择知识库', exact: true }) })
    .click()
  await page.getByRole('option', { name: '员工制度', exact: true }).click()
  await expect(page.getByRole('row').filter({ hasText: 'leave.md' })).toContainText('indexed')
  await page.getByRole('tab', { name: '工具与连接器', exact: true }).click()
  const discount = page.getByRole('row').filter({ hasText: 'request_discount' })
  await expect(discount).toContainText('需要审批')
  await discount.getByRole('button', { name: '查看', exact: true }).click()
  await expect(page.locator('.tool-details')).toContainText('high')
  await expect(page.locator('.tool-details')).toContainText('业务参数 Schema')
  await expect(page.locator('.tool-details')).toContainText('返回结果 Schema')
  await expect(page.locator('.tool-details')).toContainText('customer_id')
  await page.keyboard.press('Escape')
  await page.getByRole('tab', { name: '提示词版本', exact: true }).click()
  await page.locator('.el-collapse-item__header').first().click()
  await expect(
    page.locator('.el-collapse-item__wrap:visible .citation-content').first(),
  ).not.toHaveText('')
  await page.getByRole('tab', { name: '模型服务', exact: true }).click()
  const profilesResponse = await page.request.get('/api/profiles')
  expect(profilesResponse.status()).toBe(200)
  const profiles: { provider_id: string; model: string }[] = await profilesResponse.json()
  expect(profiles.length).toBeGreaterThan(0)
  for (const { provider_id, model } of profiles) {
    const provider = page
      .getByRole('row')
      .filter({ has: page.getByRole('cell', { name: provider_id, exact: true }) })
      .filter({ has: page.getByRole('cell', { name: model, exact: true }) })
    await expect(provider.getByRole('cell', { name: '已配置', exact: true })).toBeVisible()
  }
  expect((await page.request.get('/api/accounts')).status()).toBe(403)
  expect((await page.request.get('/api/audit')).status()).toBe(403)
  const forbidden = await page.request.post('/api/knowledge-bases', {
    headers: await mutationHeaders(page),
    data: { knowledge_base_id: 'forbidden-public-creation', name: 'Forbidden public creation' },
  })
  expect(forbidden.status()).toBe(403)
})

test('the same public entry creates independent visitors and isolates their sessions', async ({
  visitor,
  otherVisitor,
}) => {
  expect(visitor.userId).not.toBe(otherVisitor.userId)
  const create = async (owner: Visitor) => {
    const response = await owner.page.request.post('/api/sessions', {
      headers: await mutationHeaders(owner.page),
      data: { profile_id: 'hr' },
    })
    expect(response.status()).toBe(201)
    const session = await response.json()
    owner.created.add(session.thread_id)
    expect(session.user_id).toBe(owner.userId)
    return session.thread_id as string
  }
  const first = await create(visitor)
  const second = await create(otherVisitor)
  expect((await visitor.page.request.get(`/api/sessions/${second}`)).status()).toBe(404)
  expect((await otherVisitor.page.request.get(`/api/sessions/${first}`)).status()).toBe(404)
  for (const [owner, ownId, otherId] of [
    [visitor, first, second],
    [otherVisitor, second, first],
  ] as const) {
    const response = await owner.page.request.get('/api/sessions')
    expect(response.status()).toBe(200)
    const ids = (await response.json()).map((session: { thread_id: string }) => session.thread_id)
    expect(ids).toContain(ownId)
    expect(ids).not.toContain(otherId)
    await owner.page.reload()
    const me = await owner.page.request.get('/api/auth/me')
    expect((await me.json()).user.user_id).toBe(owner.userId)
  }
})

test('public visitor can read HR citations and call HTTP and MCP tools', async ({ visitor }) => {
  const { page } = visitor
  await choose(page, 'HR 制度助手')
  await send(page, '年假 leave allowance')
  const leaveCitation = page.locator('.citation-chip').filter({ hasText: '年假 Leave' })
  await expect(leaveCitation).toBeVisible()
  await leaveCitation.click()
  await expect(page.getByLabel('引用资料')).toContainText('年假')
  await expect(page.locator('.citation-content')).toContainText('10')
  await expect(page.getByLabel('引用资料')).not.toContainText('chunk_size')
  await page.keyboard.press('Escape')
  await choose(page, '产品支持助手')
  await send(page, '产品查询 P-100')
  await expect(page.locator('.message-row.assistant').last()).toContainText('Atlas Desk')
  await expect(page.getByLabel('审批请求')).toHaveCount(0)
  await send(page, 'MCP 查询 P-200')
  await expect(page.locator('.message-row.assistant').last()).toContainText('Orbit Chair')
  await expect(page.getByLabel('审批请求')).toHaveCount(0)
})

test('public visitor can edit and approve an own proposal without replaying the write', async ({
  visitor,
  otherVisitor,
}) => {
  const { page } = visitor
  await choose(page, '销售运营助手')
  await send(page, '为客户 C-100 创建回访，备注：确认续约需求')
  await expect(page.getByLabel('审批请求')).toBeVisible()
  const id = await page.locator('.session-item.active').getAttribute('data-session-id')
  expect(id).toBeTruthy()
  const pending = await page.request.get(`/api/sessions/${id}`)
  expect(pending.status()).toBe(200)
  const approvalId = (await pending.json()).approval_id
  const approvalPath = `/api/sessions/${id}/approvals/${approvalId}`
  const ownApproval = await page.request.get(approvalPath)
  expect(ownApproval.status()).toBe(200)
  const approval = await ownApproval.json()
  expect((await otherVisitor.page.request.get(approvalPath)).status()).toBe(404)
  const forged = await otherVisitor.page.request.post(approvalPath, {
    headers: await mutationHeaders(otherVisitor.page),
    data: {
      action: 'approve',
      expected_version: approval.version,
      decision_key: crypto.randomUUID(),
    },
  })
  expect(forged.status()).toBe(404)
  expect(await (await page.request.get(approvalPath)).json()).toEqual(approval)
  await page.reload()
  await choose(page, '销售运营助手')
  await page.locator(`.session-item[data-session-id="${id}"]`).click()
  await expect(page.getByLabel('审批请求')).toBeVisible()
  await page.getByRole('button', { name: '编辑参数', exact: true }).click()
  await page
    .getByRole('textbox', { name: '备注', exact: true })
    .fill('Public visitor verified follow-up')
  const decision = page.waitForRequest(
    (request) => request.method() === 'POST' && request.url().includes('/approvals/'),
  )
  await page.getByRole('button', { name: '保存编辑并批准', exact: true }).click()
  const first = await decision
  await expect(page.locator('.message-row.assistant')).toContainText('记录状态：已创建')
  await expect(page.getByLabel('审批请求')).toContainText('Public visitor verified follow-up')
  const before = await page.request.get(`/api/sessions/${id}`)
  expect(before.status()).toBe(200)
  const executed = await before.json()
  const beforeEvents = await page.request.get(`/api/sessions/${id}/events?follow=false`)
  expect(beforeEvents.status()).toBe(200)
  const originalEvents = await beforeEvents.text()
  const repeat = await page.request.post(first.url(), {
    headers: await mutationHeaders(page),
    data: first.postDataJSON(),
  })
  expect(repeat.status()).toBe(200)
  const repeated = await repeat.json()
  expect(repeated.usage.tool_calls).toBe(1)
  expect(repeated.result.tool_result).toEqual(executed.result.tool_result)
  expect(repeated.result.tool_result.data.status).toBe('created')
  const afterEvents = await page.request.get(`/api/sessions/${id}/events?follow=false`)
  expect(afterEvents.status()).toBe(200)
  expect(await afterEvents.text()).toBe(originalEvents)
})
