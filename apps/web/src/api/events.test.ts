import { describe, expect, it } from 'vitest'
import { EventCursor, SSEDecoder } from './events'
const event = (sequence: number, extra = {}) => ({
  schema_version: 1,
  thread_id: 'thread',
  run_id: 'run',
  sequence,
  event_id: `thread:${sequence}`,
  kind: 'message.delta',
  data: { text: '年假' },
  created_at: '2026-09-10',
  ...extra,
})
describe('durable event stream', () => {
  it('reassembles arbitrary frame boundaries, ignores heartbeats and deduplicates replay', () => {
    const wire =
      ': heartbeat\r\n\r\nevent: message.delta\r\ndata: ' + JSON.stringify(event(1)) + '\r\n\r\n'
    const parser = new SSEDecoder()
    const frames = [...wire].flatMap((character) => parser.push(character))
    expect(frames).toHaveLength(1)
    const cursor = new EventCursor('thread')
    expect(cursor.accept(JSON.parse(frames[0].data))?.data.text).toBe('年假')
    expect(cursor.accept(event(1))).toBeNull()
    expect(cursor.accept(event(2))?.sequence).toBe(2)
  })
  it.each([
    { thread_id: 'other' },
    { event_id: 'forged' },
    { schema_version: 2 },
    { sequence: 1.5 },
    { data: [] },
  ])('rejects untrusted identity/version/shape %j', (invalid) => {
    expect(() => new EventCursor('thread').accept(event(1, invalid))).toThrow()
  })
  it('fails closed on a gap without advancing the cursor', () => {
    const cursor = new EventCursor('thread')
    expect(() => cursor.accept(event(2))).toThrow('缺口')
    expect(cursor.sequence).toBe(0)
  })
  it('bounds incomplete frames', () => {
    expect(() => new SSEDecoder().push('a'.repeat(131073))).toThrow('大小')
  })
})
