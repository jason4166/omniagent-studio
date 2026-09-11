import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { expect, it, vi } from 'vitest'
import App from './App.vue'
import type { Role } from './api/types'

it.each<Role>(['member', 'viewer', 'admin'])(
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
