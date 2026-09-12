import { expect, it, vi } from 'vitest'
import { ApiClient, ApiError } from './client'
import { EventCursor } from './events'
it('loads public login options through the typed same-origin client', async () => {
  const transport = vi.fn<typeof fetch>().mockResolvedValue(Response.json({ public_login: null }))
  expect(await new ApiClient(transport).authOptions()).toEqual({ public_login: null })
  expect(transport.mock.calls[0][0]).toBe('/api/auth/options')
  expect(transport.mock.calls[0][1]).toMatchObject({
    method: 'GET',
    credentials: 'same-origin',
    redirect: 'error',
  })
})
it.each([
  ['invalid_dependency_response', '暂时无法处理本次回复'],
  ['unknown_internal_error', '暂时无法完成此操作'],
])('maps API %s without exposing server exception messages', async (code, title) => {
  const transport = vi
    .fn<typeof fetch>()
    .mockResolvedValue(
      Response.json(
        { error: { code, message: 'Private upstream exception body' } },
        { status: 503 },
      ),
    )
  try {
    await new ApiClient(transport).profiles()
    expect.fail('Failed API response must reject')
  } catch (error) {
    expect(error).toBeInstanceOf(ApiError)
    expect((error as Error).message).toContain(title)
    expect((error as Error).message).not.toContain(code)
    expect((error as Error).message).not.toContain('Private upstream')
  }
})
it('keeps session tokens in HttpOnly cookies and restores CSRF only in memory', async () => {
  const transport = vi
    .fn<typeof fetch>()
    .mockResolvedValueOnce(
      Response.json({
        user: { user_id: 'alice', role: 'member', profile_ids: ['hr'] },
        csrf_token: 'csrf-value',
      }),
    )
    .mockResolvedValueOnce(Response.json({ thread_id: 't' }))
    .mockResolvedValueOnce(new Response(null, { status: 204 }))
  const api = new ApiClient(transport)
  await api.me()
  await api.createSession('hr')
  expect(transport.mock.calls[1][1]?.credentials).toBe('same-origin')
  expect(transport.mock.calls[1][1]?.headers).toMatchObject({ 'X-CSRF-Token': 'csrf-value' })
  expect(transport.mock.calls[1][1]?.headers).not.toHaveProperty('Authorization')
  await api.logout()
})
it('notifies the application when a login is expired or revoked', async () => {
  const unauthorized = vi.fn()
  const transport = vi
    .fn<typeof fetch>()
    .mockResolvedValue(
      Response.json(
        { error: { code: 'authentication_required', message: 'Login required' } },
        { status: 401 },
      ),
    )
  await expect(new ApiClient(transport, unauthorized).profiles()).rejects.toBeInstanceOf(ApiError)
  expect(unauthorized).toHaveBeenCalledOnce()
})
it('uses the identical caller-owned idempotency key after a lost POST response', async () => {
  const transport = vi
    .fn<typeof fetch>()
    .mockRejectedValueOnce(new TypeError('offline'))
    .mockResolvedValueOnce(Response.json({ thread_id: 't' }))
  const api = new ApiClient(transport)
  await expect(api.send('t', 'hello', 'stable-operation')).rejects.toBeInstanceOf(ApiError)
  await api.send('t', 'hello', 'stable-operation')
  expect(transport.mock.calls[0][1]?.body).toBe(transport.mock.calls[1][1]?.body)
  expect(transport.mock.calls[0][0]).toBe('/api/sessions/t/messages')
  expect(transport.mock.calls[0][1]?.headers).toEqual({
    'Content-Type': 'application/json',
  })
})
it('a reconnect sends a read cursor and cannot send a tool action', async () => {
  const controller = new AbortController()
  const cursor = new EventCursor('thread')
  const e = {
    schema_version: 1,
    event_id: 'thread:1',
    sequence: 1,
    thread_id: 'thread',
    kind: 'run.completed',
    data: {},
  }
  cursor.accept(e)
  const transport = vi.fn<typeof fetch>().mockResolvedValue(
    new Response(
      new ReadableStream({
        start(writer) {
          writer.enqueue(new TextEncoder().encode(`data: ${JSON.stringify(e)}\n\n`))
          writer.close()
        },
      }),
    ),
  )
  const receive = vi.fn()
  await new ApiClient(transport).events(cursor, controller.signal, receive, () =>
    controller.abort(),
  )
  expect(transport).toHaveBeenCalledOnce()
  expect(transport.mock.calls[0][0]).toBe('/api/sessions/thread/events?after=1')
  expect(transport.mock.calls[0][1]?.body).toBeUndefined()
  expect(receive).not.toHaveBeenCalled()
})
