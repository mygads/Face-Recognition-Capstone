import { createPinia } from 'pinia'
import { defineComponent } from 'vue'
import { createMemoryHistory } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, getCurrentAccount, refreshOperatorSession } from '../api/client'
import { useAuthStore } from '../stores/auth'
import { createAppRouter, installAuthGuard } from './index'

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return {
    ...actual,
    getCurrentAccount: vi.fn(),
    refreshOperatorSession: vi.fn(),
  }
})

describe('route authorization', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(refreshOperatorSession).mockRejectedValue(
      new ApiError(401, 'unauthorized', 'Authentication is required.'),
    )
  })

  it('redirects guests to login and preserves the requested location', async () => {
    const pinia = createPinia()
    const router = createAppRouter(createMemoryHistory())
    installAuthGuard(router, pinia)

    await router.push('/app/dashboard')

    expect(router.currentRoute.value.name).toBe('login')
    expect(router.currentRoute.value.query.redirect).toBe('/app/dashboard')
  })

  it('redirects an authenticated user without the required role to the forbidden screen', async () => {
    const pinia = createPinia()
    const auth = useAuthStore(pinia)
    auth.$patch({
      accessToken: 'unit-fixture-access-token',
      expiresAt: Date.now() + 60_000,
      account: {
        id: '9c6c68d0-9b70-4c80-a9bd-15c2a55ecb27',
        email: 'teacher@example.test',
        full_name: 'Test Teacher',
        roles: ['TEACHER'],
        must_change_password: false,
      },
    })
    const router = createAppRouter(createMemoryHistory())
    router.addRoute({
      path: '/app/admin-only',
      name: 'admin-only-test',
      component: defineComponent({ template: '<div />' }),
      meta: { requiresAuth: true, requiredRoles: ['ADMIN'] },
    })
    installAuthGuard(router, pinia)

    await router.push('/app/admin-only')

    expect(router.currentRoute.value.name).toBe('forbidden')
  })

  it('allows teachers into reports and rejects laborants', async () => {
    const pinia = createPinia()
    const auth = useAuthStore(pinia)
    auth.$patch({
      accessToken: 'unit-fixture-access-token',
      expiresAt: Date.now() + 60_000,
      account: {
        id: '9c6c68d0-9b70-4c80-a9bd-15c2a55ecb27',
        email: 'teacher@example.test',
        full_name: 'Test Teacher',
        roles: ['TEACHER'],
        must_change_password: false,
      },
    })
    const router = createAppRouter(createMemoryHistory())
    installAuthGuard(router, pinia)

    await router.push('/app/reports')

    expect(router.currentRoute.value.name).toBe('reports')
    await router.push('/app/dashboard')
    auth.account!.roles = ['LABORANT']
    await router.push('/app/reports')
    expect(router.currentRoute.value.name).toBe('forbidden')
  })

  it('keeps master data limited to administrators', async () => {
    const pinia = createPinia()
    const auth = useAuthStore(pinia)
    auth.$patch({
      accessToken: 'unit-fixture-access-token',
      expiresAt: Date.now() + 60_000,
      account: {
        id: '9c6c68d0-9b70-4c80-a9bd-15c2a55ecb27',
        email: 'teacher@example.test',
        full_name: 'Test Teacher',
        roles: ['TEACHER'],
        must_change_password: false,
      },
    })
    const router = createAppRouter(createMemoryHistory())
    installAuthGuard(router, pinia)

    await router.push('/app/master-data')

    expect(router.currentRoute.value.name).toBe('forbidden')
  })

  it('forces a bootstrap user to the password-change page', async () => {
    const pinia = createPinia()
    const auth = useAuthStore(pinia)
    auth.$patch({
      accessToken: 'unit-fixture-bootstrap-token',
      expiresAt: Date.now() + 60_000,
      passwordChangeRequired: true,
    })
    const router = createAppRouter(createMemoryHistory())
    installAuthGuard(router, pinia)

    await router.push('/app/dashboard')

    expect(router.currentRoute.value.name).toBe('change-password')
  })

  it('restores a cookie session before honoring the saved route after a reload', async () => {
    vi.mocked(refreshOperatorSession).mockResolvedValue({
      access_token: 'unit-fixture-restored-token',
      token_type: 'bearer',
      expires_in_seconds: 900,
      password_change_required: false,
    })
    vi.mocked(getCurrentAccount).mockResolvedValue({
      id: '9c6c68d0-9b70-4c80-a9bd-15c2a55ecb27',
      email: 'admin@example.test',
      full_name: 'Test Administrator',
      roles: ['ADMIN'],
      must_change_password: false,
    })
    const pinia = createPinia()
    const router = createAppRouter(createMemoryHistory())
    installAuthGuard(router, pinia)

    await router.push('/auth/login?redirect=/app/ai-setup')

    expect(refreshOperatorSession).toHaveBeenCalledOnce()
    expect(router.currentRoute.value.name).toBe('ai-setup')
    expect(useAuthStore(pinia).hasActiveSession()).toBe(true)
  })
})
