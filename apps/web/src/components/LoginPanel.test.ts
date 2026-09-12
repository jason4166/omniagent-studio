import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { describe, expect, it, vi } from 'vitest'
import { ApiClient } from '../api/client'
import type { AuthOptions, AuthSession } from '../api/types'
import LoginPanel from './LoginPanel.vue'

const publicLogin = { username: 'review', password: 'published-access-passphrase' }
const session: AuthSession = {
  user: { user_id: 'guest-one', role: 'reviewer', profile_ids: ['hr'], is_public_guest: true },
  csrf_token: 'synthetic-csrf',
}
const render = (api: ApiClient) =>
  mount(LoginPanel, { props: { api }, global: { plugins: [ElementPlus] } })

describe('login entry', () => {
  it('prefills only the advertised account and supports a click and retry after failure', async () => {
    const api = new ApiClient(vi.fn())
    vi.spyOn(api, 'authOptions').mockResolvedValue({ public_login: publicLogin })
    const login = vi
      .spyOn(api, 'login')
      .mockRejectedValueOnce(new Error('temporary'))
      .mockResolvedValueOnce(session)
    const wrapper = render(api)
    try {
      await flushPromises()
      expect((wrapper.get('input[aria-label="账号"]').element as HTMLInputElement).value).toBe(
        publicLogin.username,
      )
      expect((wrapper.get('input[aria-label="密码"]').element as HTMLInputElement).value).toBe(
        publicLogin.password,
      )
      expect(wrapper.text()).toContain('体验账号已填入')
      await wrapper.get('form').trigger('submit')
      await flushPromises()
      expect(wrapper.text()).toContain('登录失败')
      expect((wrapper.get('input[aria-label="密码"]').element as HTMLInputElement).value).toBe(
        publicLogin.password,
      )
      await wrapper.get('form').trigger('submit')
      await flushPromises()
      expect(login).toHaveBeenNthCalledWith(2, publicLogin.username, publicLogin.password)
      expect(wrapper.emitted('authenticated')).toEqual([[session.user]])
    } finally {
      wrapper.unmount()
    }
  })

  it.each(['账号', '密码'])(
    'does not overwrite %s input even if cleared before options arrive',
    async (field) => {
      const api = new ApiClient(vi.fn())
      let complete!: (options: AuthOptions) => void
      vi.spyOn(api, 'authOptions').mockReturnValue(
        new Promise((resolve) => {
          complete = resolve
        }),
      )
      const wrapper = render(api)
      try {
        await wrapper.get(`input[aria-label="${field}"]`).setValue('my-account-value')
        await wrapper.get(`input[aria-label="${field}"]`).setValue('')
        complete({ public_login: publicLogin })
        await flushPromises()
        expect(
          wrapper
            .findAll('input')
            .every((input) => (input.element as HTMLInputElement).value === ''),
        ).toBe(true)
        expect(wrapper.text()).not.toContain('体验账号已填入')
      } finally {
        wrapper.unmount()
      }
    },
  )

  it.each(['disabled', 'offline'])(
    'retains ordinary login when public entry is %s',
    async (mode) => {
      const api = new ApiClient(vi.fn())
      const options = vi.spyOn(api, 'authOptions')
      if (mode === 'offline') options.mockRejectedValue(new Error('offline'))
      else options.mockResolvedValue({ public_login: null })
      const login = vi.spyOn(api, 'login').mockResolvedValue(session)
      const wrapper = render(api)
      try {
        await flushPromises()
        expect(wrapper.find('[role="alert"]').exists()).toBe(false)
        await wrapper.get('input[aria-label="账号"]').setValue('owner')
        await wrapper.get('input[aria-label="密码"]').setValue('my-private-passphrase')
        await wrapper.get('form').trigger('submit')
        await flushPromises()
        expect(login).toHaveBeenCalledWith('owner', 'my-private-passphrase')
        expect((wrapper.get('input[aria-label="密码"]').element as HTMLInputElement).value).toBe('')
      } finally {
        wrapper.unmount()
      }
    },
  )

  it('lets the visitor replace public defaults with an existing account', async () => {
    const api = new ApiClient(vi.fn())
    vi.spyOn(api, 'authOptions').mockResolvedValue({ public_login: publicLogin })
    const login = vi.spyOn(api, 'login').mockResolvedValue(session)
    const wrapper = render(api)
    try {
      await flushPromises()
      await wrapper.get('input[aria-label="账号"]').setValue('owner')
      await wrapper.get('input[aria-label="密码"]').setValue('my-private-passphrase')
      await wrapper.get('form').trigger('submit')
      await flushPromises()
      expect(login).toHaveBeenCalledWith('owner', 'my-private-passphrase')
      expect(wrapper.text()).not.toContain('体验账号已填入')
    } finally {
      wrapper.unmount()
    }
  })
})
