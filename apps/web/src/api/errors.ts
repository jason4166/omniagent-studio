export type PlatformErrorCode =
  | 'authentication_required'
  | 'permission_denied'
  | 'not_found'
  | 'validation_error'
  | 'version_conflict'
  | 'expired'
  | 'cancelled'
  | 'budget_exhausted'
  | 'unsupported_schema'
  | 'dependency_timeout'
  | 'rate_limited'
  | 'dependency_unavailable'
  | 'invalid_dependency_response'
  | 'circuit_open'

interface ErrorCopy {
  title: string
  description: string
}

const messages = {
  authentication_required: {
    title: '暂时无法验证登录身份',
    description: '请检查账号和密码，或重新登录后继续。',
  },
  permission_denied: {
    title: '当前账号无法执行此操作',
    description: '请联系管理员检查访问权限或操作限制。',
  },
  not_found: {
    title: '找不到所需内容',
    description: '内容可能已删除，请刷新列表后重新选择。',
  },
  validation_error: {
    title: '输入内容未通过检查',
    description: '请检查必填项、格式和长度后再提交。',
  },
  version_conflict: {
    title: '当前内容或操作状态已变化',
    description: '请刷新并检查最新状态，再决定是否继续。',
  },
  expired: {
    title: '当前会话或审批已过期',
    description: '请重新发起请求。',
  },
  cancelled: { title: '本次操作已取消', description: '如需继续，请重新发起请求。' },
  budget_exhausted: {
    title: '本次运行的额度或时限已用尽',
    description: '请新建会话并缩小请求范围；如仍超限，请联系管理员。',
  },
  unsupported_schema: {
    title: '当前数据版本无法继续处理',
    description: '请联系管理员检查版本兼容性。',
  },
  dependency_timeout: {
    title: '服务响应超时',
    description: '请稍后重试；持续出现时请联系管理员。',
  },
  rate_limited: { title: '当前请求过于频繁', description: '请等待片刻再尝试。' },
  dependency_unavailable: {
    title: '服务暂时不可用',
    description: '请稍后重试；持续出现时请联系管理员检查服务。',
  },
  invalid_dependency_response: {
    title: '暂时无法处理本次回复',
    description: '本次请求未完成，请稍后重试；持续出现时请联系管理员。',
  },
  circuit_open: {
    title: '服务暂时不可用',
    description: '请等待服务恢复后再尝试。',
  },
  network_error: {
    title: '连接中断，尚未确认请求结果',
    description: '请检查网络和会话状态；如显示“重试原请求”，可用它重新确认结果。',
  },
  stream_error: { title: '实时连接暂时中断', description: '请重新连接以查看最新进度。' },
  stream_closed: {
    title: '当前会话已过期或无法访问',
    description: '请刷新会话列表；必要时重新登录。',
  },
  invalid_json: { title: 'JSON 格式不正确', description: '请检查括号、引号和逗号后再提交。' },
  approval_changed: { title: '审批版本已变化', description: '请取消编辑并重新检查。' },
  json_object_required: { title: '参数必须为 JSON 对象', description: '请使用大括号包围参数。' },
  import_too_large: { title: '导入内容超过 64 KiB', description: '请缩小内容后再导入。' },
  file_too_large: { title: '文件不能超过 1 MiB', description: '请缩小文件后再上传。' },
  import_incomplete: { title: '文档导入未完成', description: '请检查文档状态和格式后再尝试。' },
} satisfies Record<PlatformErrorCode, ErrorCopy> & Record<string, ErrorCopy>

type KnownErrorCode = keyof typeof messages
export interface UserError extends ErrorCopy {
  code?: KnownErrorCode
}
const unknownError: UserError = {
  title: '暂时无法完成此操作',
  description: '请检查当前状态后再尝试；持续出现时请联系管理员。',
}

export function describeError(error: unknown): UserError {
  const code =
    typeof error === 'string'
      ? error
      : error && typeof error === 'object' && 'code' in error
        ? error.code
        : undefined
  if (typeof code === 'string' && Object.hasOwn(messages, code)) {
    const known = code as KnownErrorCode
    return { ...messages[known], code: known }
  }
  return { ...unknownError }
}

export function errorMessage(error: unknown): string {
  const copy = describeError(error)
  return `${copy.title}。${copy.description}`
}

export function describeRunError(error: unknown): UserError {
  const copy = describeError(error)
  if (
    copy.code &&
    [
      'invalid_dependency_response',
      'dependency_timeout',
      'dependency_unavailable',
      'rate_limited',
      'circuit_open',
    ].includes(copy.code)
  ) {
    return {
      ...copy,
      description: '可稍后尝试“恢复会话”；若仍失败，请联系管理员。',
    }
  }
  return copy
}

type InputErrorCode =
  | 'invalid_json'
  | 'approval_changed'
  | 'json_object_required'
  | 'import_too_large'
  | 'file_too_large'
  | 'import_incomplete'
export class InputError extends Error {
  constructor(readonly code: InputErrorCode) {
    super(errorMessage(code))
  }
}

export function parseInputJson(text: string): unknown {
  try {
    return JSON.parse(text)
  } catch {
    throw new InputError('invalid_json')
  }
}
