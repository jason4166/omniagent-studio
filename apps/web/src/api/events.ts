import type { EventEnvelope } from './types'

export class EventCursor {
  sequence = 0
  constructor(readonly threadId: string) {}
  accept(value: unknown): EventEnvelope | null {
    if (!value || typeof value !== 'object') throw new Error('无效的事件数据')
    const e = value as EventEnvelope
    if (
      e.schema_version !== 1 ||
      e.thread_id !== this.threadId ||
      !Number.isSafeInteger(e.sequence) ||
      e.sequence <= 0 ||
      e.event_id !== `${this.threadId}:${e.sequence}` ||
      typeof e.kind !== 'string' ||
      !e.data ||
      typeof e.data !== 'object' ||
      Array.isArray(e.data)
    )
      throw new Error('事件身份或版本无效')
    if (e.sequence <= this.sequence) return null
    if (e.sequence !== this.sequence + 1) throw new Error('事件序列存在缺口')
    this.sequence = e.sequence
    return e
  }
}

export class SSEDecoder {
  private buffer = ''
  push(chunk: string): { event: string; data: string }[] {
    this.buffer += chunk
    const frames = this.buffer.split(/\r?\n\r?\n/)
    this.buffer = frames.pop() ?? ''
    if ([this.buffer, ...frames].some((frame) => frame.length > 131072))
      throw new Error('事件超过大小限制')
    return frames
      .map((frame) => {
        let event = 'message'
        const data: string[] = []
        for (const line of frame.split(/\r?\n/)) {
          if (line.startsWith('event:')) event = line.slice(6).trimStart()
          if (line.startsWith('data:')) data.push(line.slice(5).trimStart())
        }
        return { event, data: data.join('\n') }
      })
      .filter((frame) => frame.data.length > 0)
  }
}
