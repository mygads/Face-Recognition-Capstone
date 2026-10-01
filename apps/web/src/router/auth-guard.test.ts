import { createPinia } from 'pinia'
import { defineComponent } from 'vue'
import { createMemoryHistory } from 'vue-router'
import { describe, expect, it } from 'vitest'
import { useAuthStore } from '../stores/auth'
import { createAppRouter, installAuthGuard } from './index'

describe('route authorization', () => {
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
})
