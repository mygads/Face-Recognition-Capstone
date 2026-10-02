import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, changePassword, getCurrentAccount, loginWithPassword } from '../api/client'
import { useAuthStore } from './auth'

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return {
    ...actual,
    changePassword: vi.fn(),
    getCurrentAccount: vi.fn(),
    loginWithPassword: vi.fn(),
  }
})

const accountFixture = {
  id: '9c6c68d0-9b70-4c80-a9bd-15c2a55ecb27',
  email: 'teacher@example.test',
  full_name: 'Test Teacher',
  roles: ['TEACHER'],
  must_change_password: false,
}

describe('auth store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    localStorage.clear()
  })

  afterEach(() => {
    useAuthStore().logout()
  })

  it('keeps a successful session in memory and loads the current account', async () => {
    vi.mocked(loginWithPassword).mockResolvedValue({
      access_token: 'unit-fixture-access-token',
      token_type: 'bearer',
      expires_in_seconds: 60,
      password_change_required: false,
    })
    vi.mocked(getCurrentAccount).mockResolvedValue(accountFixture)
    const auth = useAuthStore()

    await auth.login('teacher@example.test', 'unit-fixture-password')

    expect(auth.account?.roles).toEqual(['TEACHER'])
    expect(auth.hasActiveSession()).toBe(true)
    expect(Boolean(auth.getValidAccessToken())).toBe(true)
    expect(localStorage.length).toBe(0)
  })

  it('keeps the bootstrap token limited to the forced password-change flow', async () => {
    vi.mocked(loginWithPassword).mockResolvedValue({
      access_token: 'unit-fixture-bootstrap-token',
      token_type: 'bearer',
      expires_in_seconds: 60,
      password_change_required: true,
    })
    const auth = useAuthStore()

    await auth.login('admin@local.test', 'unit-fixture-temporary-password')

    expect(auth.passwordChangeRequired).toBe(true)
    expect(auth.account).toBeNull()
    expect(auth.hasActiveSession()).toBe(true)
    expect(getCurrentAccount).not.toHaveBeenCalled()
  })

  it('changes the password through the API then clears the current session', async () => {
    vi.mocked(changePassword).mockResolvedValue({
      password_changed: true,
      sign_in_again: true,
    })
    const auth = useAuthStore()
    auth.$patch({
      accessToken: 'unit-fixture-access-token',
      expiresAt: Date.now() + 60_000,
      account: accountFixture,
    })

    await auth.updatePassword('old-unit-password', 'new-unit-password-123')

    expect(changePassword).toHaveBeenCalledWith({
      current_password: 'old-unit-password',
      new_password: 'new-unit-password-123',
    })
    expect(auth.hasActiveSession()).toBe(false)
    expect(auth.account).toBeNull()
  })

  it('clears session state and shows a safe message after failed login', async () => {
    vi.mocked(loginWithPassword).mockRejectedValue(
      new ApiError(401, 'unauthorized', 'Authentication is required.'),
    )
    const auth = useAuthStore()

    await expect(
      auth.login('teacher@example.test', 'invalid-unit-password'),
    ).rejects.toBeInstanceOf(ApiError)

    expect(auth.hasActiveSession()).toBe(false)
    expect(auth.errorMessage).toBe('Email atau kata sandi tidak valid.')
    expect(Boolean(auth.accessToken)).toBe(false)
  })
})
