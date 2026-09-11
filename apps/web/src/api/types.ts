export type Json = null | boolean | number | string | Json[] | { [key: string]: Json }
export type Role = 'admin' | 'member' | 'viewer'
export interface UserIdentity {
  user_id: string
  role: Role
  profile_ids: string[]
}
export interface AuthSession {
  user: UserIdentity
  csrf_token: string
}
export interface Account extends UserIdentity {
  username: string
  enabled: boolean
  version: number
}
export interface ContextPolicy {
  last_n: number
  max_characters: number
  max_tokens: number
  summarize: boolean
  summary_characters: number
  ttl_seconds: number
}
export interface RunBudget {
  max_steps: number
  max_model_calls: number
  max_tool_calls: number
  max_tokens: number
  max_cost_microusd: number | null
  deadline_seconds: number
}
export interface AgentProfile {
  write_preflight?: {
    write_tool: string
    read_tool: string
    argument_map: Record<string, string>
    policy_query: string
  } | null
  profile_id: string
  name: string
  description: string
  version: number
  enabled: boolean
  provider_id: string
  model: string
  temperature: number
  allowed_roles: Role[]
  auto_approve_read: boolean
  require_evidence: boolean
  context_policy: ContextPolicy
  budgets: RunBudget
  tool_ids: string[]
  knowledge_base_ids: string[]
  prompt_version_id: string
  budget_policy_id: string
  approval_policy_id: string
}
export interface KnowledgeBase {
  knowledge_base_id: string
  name: string
}
export interface Source {
  source_id: string
  source_name: string
  title: string
  status: string
  checksum: string
}
export interface ImportResult {
  status: string
  source_id: string | null
  chunk_count: number
  message: string
}
export interface ToolDefinition {
  name: string
  description: string
  version: number
  enabled: boolean
  adapter_id: string
  effect: 'read' | 'write'
  risk: 'low' | 'medium' | 'high'
  requires_approval: boolean
  timeout_seconds: number
  parameters_schema: Record<string, Json>
  output_schema: Record<string, Json>
  allowed_roles: Role[]
  tags: string[]
}
export interface PromptVersion {
  prompt_version_id: string
  content: string
  content_hash: string
  variables: string[]
  created_at: string
}
export interface Provider {
  provider_id: string
  configured: boolean
  model: string
}
export interface RuntimeInfo {
  embedding: { provider: 'fake' | 'primary'; model: string; dimension: number; version: string }
  business_tools: 'local-sandbox'
}
export interface Usage {
  steps: number
  model_calls: number
  retrieval_calls: number
  tool_calls: number
  reserved_tokens: number
  input_tokens: number
  output_tokens: number
  total_tokens: number
  cost_microusd: number | null
}
export interface Citation {
  citation_label: string
  chunk_id: string
  source_id: string
  knowledge_base_id: string
  source_locator: Record<string, Json>
}
export interface RunResult {
  degraded?: boolean
  cache_hit?: boolean
  status: string
  route: string
  output_text: string | null
  citations?: Citation[]
  tool_name?: string
  arguments?: Record<string, Json>
  tool_result?: {
    status: 'succeeded' | 'rejected' | 'failed'
    data: Json
  }
  error?: Json
}
export interface Session {
  schema_version: 1
  thread_id: string
  user_id: string
  profile_id: string
  profile_version: number
  status: 'ready' | 'running' | 'awaiting_approval' | 'completed' | 'failed' | 'cancelled'
  run_id: string | null
  approval_id: string | null
  message: string
  error: string | null
  history: { role: 'user' | 'assistant'; content: string; citations?: Citation[] }[]
  usage: Usage
  result: RunResult | null
}
export interface Approval {
  preflight?: {
    read_tool: string
    read_arguments: Record<string, Json>
    read_result: Record<string, Json>
    policy_context: {
      evidence: { citation_label: string; content: string; source_locator: Record<string, Json> }[]
    } | null
  } | null
  approval_id: string
  thread_id: string
  run_id: string
  tool_name: string
  arguments: Record<string, Json>
  risk: string
  reason: string
  status: 'pending' | 'approved' | 'executed' | 'rejected' | 'expired' | 'failed'
  version: number
  expires_at: string
  decision_by: string | null
  idempotency_key: string
}
export interface ApprovalDecision {
  action: 'approve' | 'edit' | 'reject'
  expected_version: number
  decision_key: string
  arguments?: Record<string, Json>
}
export interface EventEnvelope {
  schema_version: 1
  event_id: string
  sequence: number
  thread_id: string
  run_id: string | null
  kind: string
  data: Record<string, Json>
  created_at: string
}
export interface ResolvedCitation {
  chunk_id: string
  source_id: string
  knowledge_base_id: string
  content: string
  metadata: Record<string, Json>
}
export interface AuditEvent {
  audit_id: string
  actor_hash: string
  thread_id: string
  run_id: string | null
  action: string
  created_at: string
  details: Record<string, Json>
}
