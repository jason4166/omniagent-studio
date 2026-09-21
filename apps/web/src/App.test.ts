import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { expect, it, vi } from 'vitest'
import App from './App.vue'
import type { Role } from './api/types'

it.each([
  { authenticated: false, recordNumber: undefined },
  { authenticated: true, recordNumber: undefined },
  { authenticated: false, recordNumber: '津ICP备2026013554号-1' },
  { authenticated: true, recordNumber: '津ICP备2026013554号-1' },
])(
  'shows only the configured ICP record ($authenticated, $recordNumber)',
  async ({ authenticated, recordNumber }) => {
    vi.stubEnv('VITE_ICP_RECORD_NUMBER', recordNumber)
    vi.stubGlobal(
      'fetch',
      vi.fn<typeof fetch>().mockResolvedValue(
        Response.json({
          user: authenticated
            ? { user_id: 'synthetic-user', role: 'member', profile_ids: ['hr'] }
            : null,
          csrf_token: 'test-csrf',
        }),
      ),
    )
    const wrapper = mount(App, {
      global: {
        plugins: [ElementPlus],
        stubs: {
          LoginPanel: true,
          ChatWorkspace: true,
          AccountManager: true,
          PasswordDialog: true,
          AdminWorkspace: true,
        },
      },
    })
    try {
      await flushPromises()
      const shell = wrapper.get(authenticated ? '.main-shell' : '.login-page')
      if (recordNumber) {
        const link = shell.get('footer a')
        expect(link.text()).toBe(recordNumber)
        expect(link.attributes('href')).toBe('https://beian.miit.gov.cn/')
        expect(link.attributes('target')).toBe('_blank')
        expect(link.attributes('rel')).toBe('noopener noreferrer')
      } else {
        expect(shell.find('footer').exists()).toBe(false)
      }
    } finally {
      wrapper.unmount()
      vi.unstubAllEnvs()
      vi.unstubAllGlobals()
    }
  },
)

it.each<Role>(['member', 'viewer', 'admin', 'reviewer'])(
  'keeps the workspace readable and reserves management/version details for %s',
  async (role) => {
    vi.stubGlobal(
      'fetch',
      vi.fn<typeof fetch>().mockResolvedValue(
        Response.json({
          user: { user_id: 'synthetic-user', role, profile_ids: ['hr'] },
          csrf_token: 'test-csrf',
        }),
      ),
    )
    const wrapper = mount(App, {
      global: {
        plugins: [ElementPlus],
        stubs: {
          ChatWorkspace: true,
          AccountManager: true,
          PasswordDialog: true,
          AdminWorkspace: true,
        },
      },
    })
    try {
      await flushPromises()
      const navigation = wrapper.find('.rail').text()
      expect(navigation).toContain('工作台')
      expect(navigation).not.toContain('Agent 工作台')
      expect(navigation).not.toContain('WORKSPACE')
      if (role === 'admin') {
        expect(navigation).toContain('配置与管理')
        expect(navigation).toContain('账号与访问')
        expect(navigation).toContain('v1.0 RC')
      } else if (role === 'reviewer') {
        expect(navigation).toContain('配置与管理')
        expect(navigation).not.toContain('账号与访问')
        expect(wrapper.text()).toContain('管理只读')
        expect(wrapper.find('.mobile-nav').exists()).toBe(true)
        expect(wrapper.find('password-dialog-stub').exists()).toBe(true)
        await wrapper
          .findAll('.nav-item')
          .find((button) => button.text().includes('配置与管理'))!
          .trigger('click')
        await flushPromises()
        expect(wrapper.find('admin-workspace-stub').attributes()).toHaveProperty('readonly')
      } else {
        expect(navigation).not.toContain('配置与管理')
        expect(navigation).not.toContain('账号与访问')
        expect(navigation).not.toContain('v1.0 RC')
      }
    } finally {
      wrapper.unmount()
      vi.unstubAllGlobals()
    }
  },
)

it('hides password changes only for a public guest identity', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn<typeof fetch>().mockResolvedValue(
      Response.json({
        user: { user_id: 'guest', role: 'reviewer', profile_ids: ['hr'], is_public_guest: true },
        csrf_token: 'test-csrf',
      }),
    ),
  )
  const wrapper = mount(App, {
    global: {
      plugins: [ElementPlus],
      stubs: {
        ChatWorkspace: true,
        AccountManager: true,
        PasswordDialog: true,
        AdminWorkspace: true,
      },
    },
  })
  try {
    await flushPromises()
    expect(wrapper.find('password-dialog-stub').exists()).toBe(false)
    expect(wrapper.text()).toContain('退出登录')
    expect(wrapper.find('.rail').text()).toContain('配置与管理')
    expect(wrapper.find('.rail').text()).not.toContain('账号与访问')
  } finally {
    wrapper.unmount()
    vi.unstubAllGlobals()
  }
})
