import { expect, it, vi } from 'vitest'
import { ApiClient, ApiError } from './client'
import { EventCursor } from './events'
it('uses the identical caller-owned idempotency key after a lost POST response', async () => {
  const transport = vi
    .fn<typeof fetch>()
    .mockRejectedValueOnce(new TypeError('offline'))
    .mockResolvedValueOnce(Response.json({ thread_id: 't' }))
  const api = new ApiClient('member', transport)
  await expect(api.send('t', 'hello', 'stable-operation')).rejects.toBeInstanceOf(ApiError)
  await api.send('t', 'hello', 'stable-operation')
  expect(transport.mock.calls[0][1]?.body).toBe(transport.mock.calls[1][1]?.body)
  expect(transport.mock.calls[0][0]).toBe('/api/sessions/t/messages')
  expect(transport.mock.calls[0][1]?.headers).toEqual({
    Authorization: 'Bearer local-demo-member',
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
  await new ApiClient('member', transport).events(cursor, controller.signal, receive, () =>
    controller.abort(),
  )
  expect(transport).toHaveBeenCalledOnce()
  expect(transport.mock.calls[0][0]).toBe('/api/sessions/thread/events?after=1')
  expect(transport.mock.calls[0][1]?.body).toBeUndefined()
  expect(receive).not.toHaveBeenCalled()
})
