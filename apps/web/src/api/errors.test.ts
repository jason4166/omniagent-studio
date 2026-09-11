import { expect, it } from 'vitest'
import { describeError, describeRunError, errorMessage, parseInputJson } from './errors'

it.each([
  ['invalid_dependency_response', '暂时无法处理本次回复', '恢复会话'],
  ['dependency_timeout', '响应超时', '恢复会话'],
  ['budget_exhausted', '额度或时限已用尽', '缩小请求范围'],
  ['permission_denied', '当前账号无法执行此操作', '检查访问权限'],
  ['unknown_with_private_details', '暂时无法完成此操作', '检查当前状态'],
])('explains %s without exposing raw details or promising recovery', (code, title, guidance) => {
  const copy = describeRunError({ code, message: 'private dependency response' })
  expect(copy.title).toContain(title)
  expect(copy.description).toContain(guidance)
  expect(`${copy.title} ${copy.description}`).not.toContain(code)
  expect(JSON.stringify(copy)).not.toContain('private dependency response')
})

it('does not expose unknown codes, native exceptions or prototype keys', () => {
  for (const error of [
    new Error('sensitive body'),
    { code: 'sensitive body' },
    { code: {} },
    'toString',
    null,
  ]) {
    expect(describeError(error)).toEqual({
      title: '暂时无法完成此操作',
      description: '请检查当前状态后再尝试；持续出现时请联系管理员。',
    })
  }
})

it('keeps local JSON validation useful without echoing invalid input', () => {
  try {
    parseInputJson('{private input')
    expect.fail('Invalid JSON must fail')
  } catch (error) {
    expect(errorMessage(error)).toContain('JSON 格式不正确')
    expect(errorMessage(error)).not.toContain('private input')
  }
})
