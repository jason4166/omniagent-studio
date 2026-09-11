import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { afterEach, expect, it, vi } from 'vitest'
import { ApiClient, ApiError } from '../api/client'
import { citationPresentation } from '../api/citationPresentation'
import type { AgentProfile, ResolvedCitation, Session } from '../api/types'
import ChatWorkspace from './ChatWorkspace.vue'

const source: ResolvedCitation = {
  chunk_id: 'internal-chunk-id',
  source_id: 'internal-source-id',
  knowledge_base_id: 'internal-kb-id',
  content: '每周最多 2 天。\n<script>untrusted()</script>',
  metadata: {
    section: '远程办公',
    source_name: 'remote.md',
    checksum: 'internal-checksum',
    chunk_size: 500,
    parser_version: 'internal-parser',
    page_number: null,
  },
}

function setup() {
  const api = new ApiClient(vi.fn())
  const session = {
    thread_id: 'session-identifier',
    profile_id: 'hr',
    status: 'completed',
    approval_id: null,
    message: '可以远程办公吗？',
    history: [
      {
        role: 'assistant',
        content: '每周最多 2 天。',
        citations: [
          {
            citation_label: 'C1',
            ...source,
            source_locator: source.metadata,
          },
        ],
      },
    ],
    result: null,
    usage: { model_calls: 2, tool_calls: 0, total_tokens: 500, cost_microusd: null },
  } as unknown as Session
  vi.spyOn(api, 'profiles').mockResolvedValue([
    {
      profile_id: 'hr',
      name: 'HR 制度助手',
      description: '员工制度查询',
      provider_id: 'primary',
      model: 'private-model-version',
      knowledge_base_ids: ['internal-kb-id'],
      tool_ids: [],
    } as unknown as AgentProfile,
  ])
  vi.spyOn(api, 'runtimeInfo').mockResolvedValue({
    embedding: {
      model: 'private-embedding-version',
      provider: 'primary',
      dimension: 1024,
      version: 'v1',
    },
    business_tools: 'local-sandbox',
  })
  vi.spyOn(api, 'sessions').mockResolvedValue([session])
  vi.spyOn(api, 'session').mockResolvedValue(session)
  vi.spyOn(api, 'events').mockResolvedValue(undefined)
  const citation = vi.spyOn(api, 'citation').mockResolvedValue(source)
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  )
  HTMLElement.prototype.scrollTo = vi.fn()
  const wrapper = mount(ChatWorkspace, {
    props: { api },
    attachTo: document.body,
    global: { plugins: [ElementPlus] },
  })
  return { wrapper, citation }
}

afterEach(() => {
  vi.unstubAllGlobals()
  document.body.innerHTML = ''
})

it('presents cited text and location without internal metadata or rendering document HTML', async () => {
  const { wrapper, citation } = setup()
  try {
    await flushPromises()
    expect(wrapper.text()).not.toMatch(
      /真实模型|真实 API|private-model|private-embedding|session-identifier|成本 unknown/,
    )
    await wrapper.find('.session-item').trigger('click')
    await flushPromises()
    expect(wrapper.find('.composer-footer .usage-summary').text()).toContain('500 token')
    expect(wrapper.find('.composer-footer .usage-summary').text()).toContain('成本未知')
    expect(wrapper.find('.citation-chip').text()).toContain('C1 · 远程办公')
    await wrapper.find('.citation-chip').trigger('click')
    await flushPromises()
    const article = document.querySelector('.citation-document')!
    expect(article.textContent).toContain('remote.md')
    expect(article.textContent).toContain(source.content)
    expect(article.textContent).not.toMatch(/internal-|chunk_size|checksum|parser_version|Chunk:/)
    expect(article.querySelector('script')).toBeNull()
    expect(citation).toHaveBeenCalledWith('session-identifier', 'internal-chunk-id')
  } finally {
    wrapper.unmount()
  }
})

it('shows loading and retry, and discards a late citation after switching conversation', async () => {
  const { wrapper, citation } = setup()
  try {
    await flushPromises()
    await wrapper.find('.session-item').trigger('click')
    await flushPromises()
    citation.mockRejectedValueOnce(new ApiError('not_found', 404))
    await wrapper.find('.citation-chip').trigger('click')
    await flushPromises()
    expect(document.querySelector('.citation-error')?.textContent).toContain('暂时无法打开原文')
    let resolve!: (value: ResolvedCitation) => void
    citation.mockImplementationOnce(
      () =>
        new Promise((done) => {
          resolve = done
        }),
    )
    ;(document.querySelector('.citation-error button') as HTMLButtonElement).click()
    await flushPromises()
    expect(document.querySelector('[aria-label="正在加载原文"]')).not.toBeNull()
    await wrapper.find('.profile-card').trigger('click')
    resolve(source)
    await flushPromises()
    expect(document.querySelector('.citation-document')).toBeNull()
    expect(wrapper.findAll('.citation-chip')).toHaveLength(0)
  } finally {
    wrapper.unmount()
  }
})

it('uses only available document locations and never falls back to private paths or IDs', () => {
  expect(citationPresentation({ source_name: 'C:\\private\\policy.pdf', page_number: 3 })).toEqual({
    title: 'policy',
    filename: 'policy.pdf',
    page: 3,
  })
  expect(citationPresentation({ source_id: 'private-id', section: {}, page_number: -1 })).toEqual({
    title: '引用资料',
    filename: null,
    page: null,
  })
})
