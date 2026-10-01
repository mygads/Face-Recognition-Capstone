import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { afterEach, describe, expect, it } from 'vitest'
import { createMemoryHistory } from 'vue-router'
import App from './App.vue'
import { createAppRouter } from './router'

async function mountAt(path: string) {
  const router = createAppRouter(createMemoryHistory())
  await router.push(path)
  const wrapper = mount(App, { global: { plugins: [createPinia(), router] } })
  await router.isReady()
  await flushPromises()
  return wrapper
}

afterEach(() => {
  localStorage.clear()
  document.documentElement.removeAttribute('data-theme')
})

describe('application shell', () => {
  it('opens the authenticated layout with its navigation and page header', async () => {
    const wrapper = await mountAt('/app/dashboard')

    expect(wrapper.find('[data-testid="app-shell"]').exists()).toBe(true)
    expect(wrapper.find('[aria-label="Navigasi utama"]').exists()).toBe(true)
    expect(wrapper.get('h1').text()).toBe('Ringkasan')
    wrapper.unmount()
  })

  it('opens the auth layout on the login route', async () => {
    const wrapper = await mountAt('/auth/login')

    expect(wrapper.find('[data-testid="auth-layout"]').exists()).toBe(true)
    expect(wrapper.get('h1').text()).toBe('Masuk ke akun')
    wrapper.unmount()
  })

  it('toggles and persists the selected color theme', async () => {
    localStorage.setItem('presensi.theme', 'light')
    const wrapper = await mountAt('/app/dashboard')

    await wrapper.get('[data-testid="theme-toggle"]').trigger('click')

    expect(document.documentElement.dataset.theme).toBe('dark')
    expect(localStorage.getItem('presensi.theme')).toBe('dark')
    wrapper.unmount()
  })
})
