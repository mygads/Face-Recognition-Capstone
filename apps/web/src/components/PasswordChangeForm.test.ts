import { createPinia } from 'pinia'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import PasswordChangeForm from './PasswordChangeForm.vue'

const { changePassword } = vi.hoisted(() => ({
  changePassword: vi.fn(),
}))

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return { ...actual, changePassword }
})

describe('PasswordChangeForm', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('rejects mismatched confirmation before calling the API', async () => {
    const wrapper = mount(PasswordChangeForm, {
      global: { plugins: [createPinia()] },
    })
    await wrapper.get('#profile-current-password').setValue('temporary-password')
    await wrapper.get('#profile-new-password').setValue('new-password-123')
    await wrapper.get('#profile-confirm-password').setValue('different-password')
    await wrapper.get('form').trigger('submit')

    expect(wrapper.get('[role="alert"]').text()).toContain('belum sama')
    expect(changePassword).not.toHaveBeenCalled()
  })

  it('submits matching passwords and emits saved', async () => {
    changePassword.mockResolvedValue({ password_changed: true, sign_in_again: true })
    const wrapper = mount(PasswordChangeForm, {
      global: { plugins: [createPinia()] },
    })
    await wrapper.get('#profile-current-password').setValue('temporary-password')
    await wrapper.get('#profile-new-password').setValue('new-password-123')
    await wrapper.get('#profile-confirm-password').setValue('new-password-123')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(changePassword).toHaveBeenCalledWith({
      current_password: 'temporary-password',
      new_password: 'new-password-123',
    })
    expect(wrapper.emitted('saved')).toHaveLength(1)
  })
})
