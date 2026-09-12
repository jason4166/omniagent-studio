import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiClient } from '../api/client'
import type { AgentProfile, ToolDefinition } from '../api/types'
import AdminWorkspace from './AdminWorkspace.vue'
import ProfileEditor from './ProfileEditor.vue'

const profile: AgentProfile = {
  profile_id: 'sales',
  name: '销售助手',
  description: '查询政策与创建回访',
  version: 3,
  enabled: true,
  provider_id: 'primary',
  model: 'chat-model',
  temperature: 0.2,
  allowed_roles: ['admin', 'member'],
  auto_approve_read: true,
  require_evidence: true,
  tool_ids: ['followup'],
  knowledge_base_ids: ['sales-kb'],
  prompt_version_id: 'sales-v2',
  budget_policy_id: 'standard',
  approval_policy_id: 'safe-default',
  context_policy: {
    last_n: 8,
    max_characters: 12000,
    max_tokens: 16000,
    summarize: true,
    summary_characters: 500,
    ttl_seconds: 86400,
  },
  budgets: {
    max_steps: 24,
    max_model_calls: 4,
    max_tool_calls: 4,
    max_tokens: 64000,
    max_cost_microusd: null,
    deadline_seconds: 120,
  },
  write_preflight: {
    write_tool: 'followup',
    read_tool: 'customer',
    argument_map: { customer_id: 'customer_id' },
    policy_query: '回访政策',
  },
}
const tool: ToolDefinition = {
  name: 'followup',
  description: '创建客户回访',
  version: 2,
  enabled: true,
  adapter_id: 'sandbox',
  effect: 'write',
  risk: 'high',
  requires_approval: true,
  timeout_seconds: 5,
  parameters_schema: { type: 'object', properties: { customer_id: { type: 'string' } } },
  output_schema: { type: 'object', properties: { followup_id: { type: 'string' } } },
  allowed_roles: ['admin', 'member'],
  tags: ['sales'],
}
const mutations = [
  'createProfile',
  'saveProfile',
  'validateProfile',
  'importProfile',
  'createKnowledgeBase',
  'upload',
  'saveTool',
  'importOpenAPI',
  'createPrompt',
] as const

function setup(readonly = false) {
  const api = new ApiClient(vi.fn())
  vi.spyOn(api, 'profiles').mockResolvedValue([structuredClone(profile)])
  vi.spyOn(api, 'knowledgeBases').mockResolvedValue([
    { knowledge_base_id: 'sales-kb', name: '销售政策' },
  ])
  vi.spyOn(api, 'tools').mockResolvedValue([structuredClone(tool)])
  vi.spyOn(api, 'prompts').mockResolvedValue([
    {
      prompt_version_id: 'sales-v2',
      content: '根据销售政策提供帮助',
      content_hash: 'synthetic-hash',
      variables: [],
      created_at: '2026-09-12',
    },
  ])
  vi.spyOn(api, 'providers').mockResolvedValue([
    { provider_id: 'primary', model: 'chat-model', configured: true },
  ])
  const audit = vi.spyOn(api, 'audit').mockResolvedValue([])
  vi.spyOn(api, 'sources').mockResolvedValue([
    {
      source_id: 'policy',
      source_name: 'discount.md',
      title: '折扣政策',
      status: 'ready',
      checksum: 'synthetic-checksum',
    },
  ])
  vi.spyOn(api, 'exportProfile').mockResolvedValue({ schema_version: 1, profile })
  const mutationSpies = mutations.map((name) => vi.spyOn(api, name))
  const wrapper = mount(AdminWorkspace, {
    props: { api, readonly },
    global: {
      plugins: [ElementPlus],
      stubs: {
        ElDrawer: {
          props: ['modelValue', 'title'],
          template: '<section v-if="modelValue"><h2>{{ title }}</h2><slot /></section>',
        },
        ElDialog: {
          props: ['modelValue', 'title'],
          template:
            '<section v-if="modelValue"><h2>{{ title }}</h2><slot /><slot name="footer" /></section>',
        },
      },
    },
  })
  return { api, audit, wrapper, mutationSpies }
}

beforeEach(() => {
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  )
})
afterEach(() => {
  vi.unstubAllGlobals()
})

describe('management access', () => {
  it('shows complete read-only configuration without auditing or mutation controls', async () => {
    const { api, wrapper, audit, mutationSpies } = setup(true)
    try {
      await flushPromises()
      expect(audit).not.toHaveBeenCalled()
      expect(wrapper.text()).not.toContain('审计')
      const actions = wrapper.findAll('button').map((button) => button.text())
      for (const label of [
        '创建助手',
        '创建知识库',
        '创建版本',
        '编辑',
        '保存工具',
        '导入 JSON',
        '导入 OpenAPI 子集',
      ])
        expect(actions).not.toContain(label)
      expect(wrapper.find('input[type="file"]').exists()).toBe(false)
      expect(wrapper.text()).toContain('根据销售政策提供帮助')
      expect(wrapper.text()).toContain('chat-model')
      const profileView = wrapper.findAll('button').find((button) => button.text() === '查看')!
      await profileView.trigger('click')
      await flushPromises()
      const details = wrapper.get('.profile-details')
      for (const text of [
        '销售政策',
        'followup',
        'safe-default',
        'sales-v2',
        '86400',
        '64000',
        '回访政策',
      ])
        expect(details.text()).toContain(text)
      expect(wrapper.findComponent(ProfileEditor).exists()).toBe(false)
      expect(details.find('input').exists()).toBe(false)
      const controller = wrapper.vm as unknown as {
        editTool: (tool: ToolDefinition) => void
        activeKB: string
        loadSources: () => Promise<void>
        exportProfile: (id: string) => Promise<void>
        importData: () => Promise<void>
        createKB: () => Promise<void>
        upload: (event: Event) => Promise<void>
        saveTool: () => Promise<void>
        createPrompt: () => Promise<void>
      }
      controller.editTool(tool)
      await flushPromises()
      const toolDetails = wrapper.get('.tool-details').text()
      for (const text of ['需要审批', 'high', 'customer_id', 'followup_id'])
        expect(toolDetails).toContain(text)
      controller.activeKB = 'sales-kb'
      await controller.loadSources()
      await flushPromises()
      expect(api.sources).toHaveBeenCalledWith('sales-kb')
      expect(wrapper.text()).toContain('discount.md')
      await controller.exportProfile('sales')
      expect(api.exportProfile).toHaveBeenCalledWith('sales')
      await controller.importData()
      await controller.createKB()
      await controller.upload(new Event('change'))
      await controller.saveTool()
      await controller.createPrompt()
      for (const spy of mutationSpies) expect(spy).not.toHaveBeenCalled()
    } finally {
      wrapper.unmount()
    }
  })

  it('preserves administrator editing, validation and audit access', async () => {
    const { api, wrapper, audit } = setup()
    vi.spyOn(api, 'saveProfile').mockResolvedValue(profile)
    try {
      await flushPromises()
      expect(audit).toHaveBeenCalledOnce()
      expect(wrapper.text()).toContain('审计')
      expect(wrapper.text()).toContain('创建助手')
      expect(wrapper.find('input[type="file"]').exists()).toBe(true)
      await wrapper
        .findAll('button')
        .find((button) => button.text() === '编辑')!
        .trigger('click')
      await flushPromises()
      expect(wrapper.findComponent(ProfileEditor).exists()).toBe(true)
      expect(wrapper.text()).toContain('保存助手')
      await wrapper.findComponent(ProfileEditor).get('form').trigger('submit')
      await flushPromises()
      expect(api.saveProfile).toHaveBeenCalledWith(profile)
    } finally {
      wrapper.unmount()
    }
  })
})
