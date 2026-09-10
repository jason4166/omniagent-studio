import { EventCursor, SSEDecoder } from './events'
import type {
  AgentProfile,
  Approval,
  ApprovalDecision,
  AuditEvent,
  EventEnvelope,
  ImportResult,
  KnowledgeBase,
  PromptVersion,
  Provider,
  ResolvedCitation,
  Role,
  RuntimeInfo,
  Session,
  Source,
  ToolDefinition,
} from './types'

export class ApiError extends Error {
  constructor(
    readonly code: string,
    message: string,
    readonly status: number,
  ) {
    super(message)
  }
}
const path = encodeURIComponent

export class ApiClient {
  constructor(
    private readonly role: Role,
    private readonly transport: typeof fetch = globalThis.fetch.bind(globalThis),
  ) {}
  private headers(): Record<string, string> {
    return { Authorization: `Bearer local-demo-${this.role}` }
  }
  private async request<T>(url: string, method = 'GET', data?: unknown): Promise<T> {
    const multipart = data instanceof FormData
    const headers = this.headers()
    if (data !== undefined && !multipart) headers['Content-Type'] = 'application/json'
    let response: Response
    try {
      response = await this.transport(`/api${url}`, {
        method,
        headers,
        body: data === undefined ? undefined : multipart ? data : JSON.stringify(data),
        signal: AbortSignal.timeout(130000),
      })
    } catch {
      throw new ApiError('network_error', '连接中断。可恢复会话，或使用原请求重试。', 0)
    }
    if (!response.ok) {
      const body = await response.json().catch(() => null)
      throw new ApiError(
        body?.error?.code ?? 'http_error',
        body?.error?.message ?? `请求失败 (${response.status})`,
        response.status,
      )
    }
    return response.status === 204 ? (undefined as T) : ((await response.json()) as T)
  }
  profiles = () => this.request<AgentProfile[]>('/profiles')
  runtimeInfo = () => this.request<RuntimeInfo>('/runtime-info')
  createProfile = (profile: AgentProfile) =>
    this.request<AgentProfile>('/profiles', 'POST', profile)
  saveProfile = (profile: AgentProfile) =>
    this.request<AgentProfile>(`/profiles/${path(profile.profile_id)}`, 'PUT', {
      expected_version: profile.version,
      profile,
    })
  validateProfile = (profile: AgentProfile) =>
    this.request<{ valid: boolean }>('/profiles/validate', 'POST', profile)
  importProfile = (bundle: unknown) =>
    this.request<AgentProfile>('/profiles/import', 'POST', bundle)
  exportProfile = (id: string) =>
    this.request<{ schema_version: 1; profile: AgentProfile }>(`/profiles/${path(id)}/export`)
  knowledgeBases = () => this.request<KnowledgeBase[]>('/knowledge-bases')
  createKnowledgeBase = (kb: KnowledgeBase) =>
    this.request<KnowledgeBase>('/knowledge-bases', 'POST', kb)
  sources = (kb: string) => this.request<Source[]>(`/knowledge-bases/${path(kb)}/sources`)
  upload = (kb: string, file: File) => {
    const data = new FormData()
    data.append('file', file)
    return this.request<ImportResult>(`/knowledge-bases/${path(kb)}/sources`, 'POST', data)
  }
  tools = () => this.request<ToolDefinition[]>('/tools')
  saveTool = (tool: ToolDefinition) =>
    this.request<ToolDefinition>(`/tools/${path(tool.name)}`, 'PUT', tool)
  importOpenAPI = (document: unknown) =>
    this.request<ToolDefinition[]>('/tools/import-openapi', 'POST', document)
  prompts = () => this.request<PromptVersion[]>('/prompts')
  createPrompt = (prompt_version_id: string, content: string) =>
    this.request<PromptVersion>('/prompts', 'POST', { prompt_version_id, content })
  providers = () => this.request<Provider[]>('/providers')
  audit = () => this.request<AuditEvent[]>('/audit')
  sessions = () => this.request<Session[]>('/sessions')
  createSession = (profile_id: string) => this.request<Session>('/sessions', 'POST', { profile_id })
  session = (id: string) => this.request<Session>(`/sessions/${path(id)}`)
  send = (id: string, message: string, request_key: string) =>
    this.request<Session>(`/sessions/${path(id)}/messages`, 'POST', { message, request_key })
  resume = (id: string) => this.request<Session>(`/sessions/${path(id)}/resume`, 'POST')
  cancel = (id: string) => this.request<Session>(`/sessions/${path(id)}/cancel`, 'POST')
  deleteSession = (id: string) => this.request<void>(`/sessions/${path(id)}`, 'DELETE')
  approval = (id: string, approval: string) =>
    this.request<Approval>(`/sessions/${path(id)}/approvals/${path(approval)}`)
  decide = (id: string, approval: string, decision: ApprovalDecision) =>
    this.request<Session>(`/sessions/${path(id)}/approvals/${path(approval)}`, 'POST', decision)
  citation = (id: string, chunk: string) =>
    this.request<ResolvedCitation>(`/sessions/${path(id)}/citations/${path(chunk)}`)

  async events(
    cursor: EventCursor,
    signal: AbortSignal,
    receive: (event: EventEnvelope) => void,
    status: (value: string) => void,
  ): Promise<void> {
    let failures = 0
    while (!signal.aborted) {
      try {
        const response = await this.transport(
          `/api/sessions/${path(cursor.threadId)}/events?after=${cursor.sequence}`,
          { headers: this.headers(), signal },
        )
        if (!response.ok || !response.body)
          throw new ApiError('stream_error', '事件连接失败', response.status)
        status('已连接')
        const reader = response.body.getReader()
        const text = new TextDecoder()
        const decoder = new SSEDecoder()
        try {
          while (!signal.aborted) {
            const result = await reader.read()
            if (result.done) break
            for (const frame of decoder.push(text.decode(result.value, { stream: true }))) {
              if (frame.event === 'stream.closed')
                throw new ApiError('stream_closed', '会话已过期或不可访问', 403)
              const event = cursor.accept(JSON.parse(frame.data))
              if (event) receive(event)
            }
          }
        } finally {
          await reader.cancel().catch(() => undefined)
          reader.releaseLock()
        }
        failures = 0
      } catch (error) {
        if (signal.aborted) return
        if (error instanceof ApiError && [401, 403, 404, 410, 422].includes(error.status)) {
          status(error.message)
          return
        }
        if (++failures > 3) {
          status('连接失败，请重新连接')
          return
        }
      }
      if (signal.aborted) return
      status('重连中')
      await new Promise<void>((resolve) => {
        const done = () => {
          clearTimeout(timer)
          signal.removeEventListener('abort', done)
          resolve()
        }
        const timer = setTimeout(done, Math.min(500 * 2 ** failures, 4000))
        signal.addEventListener('abort', done, { once: true })
      })
    }
  }
}
