import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useAuthStore } from '../stores/auth'
import DevicesView from './DevicesView.vue'

const api = vi.hoisted(() => ({
  listDevices: vi.fn(),
  listLaboratories: vi.fn(),
  provisionDeviceCredential: vi.fn(),
  rotateDeviceCredential: vi.fn(),
  createDevice: vi.fn(),
  updateDevice: vi.fn(),
}))

vi.mock('../api/client', () => ({
  ApiError: class ApiError extends Error {
    code?: string
    details?: { field: string; message: string }[]
  },
  ...api,
}))

const device = {
  device_id: '76f1f10d-df24-4ffc-a5bc-6ff273dc8e2b',
  name: 'Lab camera',
  device_type: 'edge_pc',
  deployment_profile: 'AI_EDGE',
  laboratory_id: 'lab-1',
  laboratory_code: 'LAB-1',
  laboratory_name: 'Laboratory 1',
  is_active: true,
  app_version: null,
  model_version: null,
  camera_status: 'unknown',
  last_seen_at: null,
  heartbeat_timeout_seconds: 60,
  latency_summary: null,
  health_status: 'offline',
}

function adminPinia() {
  const pinia = createPinia()
  useAuthStore(pinia).$patch({
    accessToken: 'test-token',
    expiresAt: Date.now() + 60_000,
    account: {
      id: 'admin-1',
      email: 'admin@example.test',
      full_name: 'Test Admin',
      roles: ['ADMIN'],
      must_change_password: false,
    },
  })
  return pinia
}

describe('device installation setup', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.listDevices.mockResolvedValue({
      items: [device],
      pagination: { total: 1, limit: 10, offset: 0 },
    })
    api.listLaboratories.mockResolvedValue({
      items: [],
      pagination: { total: 0, limit: 100, offset: 0 },
    })
    api.provisionDeviceCredential.mockResolvedValue({
      device_id: device.device_id,
      token: 'a'.repeat(48),
      expires_at: '2026-11-01T00:00:00Z',
      previous_token_valid_until: null,
    })
  })

  it('shows a local working-copy command and disables public setup routes', async () => {
    const wrapper = mount(DevicesView, { global: { plugins: [adminPinia()] } })
    await flushPromises()
    const credentialButton = wrapper
      .findAll('button')
      .find((button) => button.text().trim() === 'Kredensial')
    expect(credentialButton).toBeDefined()
    await credentialButton!.trigger('click')
    await wrapper
      .get('[data-testid="device-credential-dialog"] button.button--primary')
      .trigger('click')
    await flushPromises()

    expect(wrapper.get('[data-testid="device-install-command"]').text()).toContain(
      '-UseWorkingCopy',
    )
    expect(wrapper.get('[data-testid="device-install-command"]').text()).toContain(device.device_id)

    await wrapper.get('#device-connection-mode').setValue('public-domain')
    await flushPromises()
    expect(wrapper.find('[data-testid="device-install-command"]').exists()).toBe(false)
    const copyCommandButton = wrapper
      .findAll('button')
      .find((button) => button.text().includes('Salin perintah instalasi perangkat'))
    expect(copyCommandButton?.attributes('disabled')).toBeDefined()
    wrapper.unmount()
  })

  it('requires private API origins for an Armbian STB gateway', async () => {
    const gateway = {
      ...device,
      device_type: 'camera_gateway',
      deployment_profile: 'STB_GATEWAY',
    }
    api.listDevices.mockResolvedValue({
      items: [gateway],
      pagination: { total: 1, limit: 10, offset: 0 },
    })
    const wrapper = mount(DevicesView, { global: { plugins: [adminPinia()] } })
    await flushPromises()
    const credentialButton = wrapper
      .findAll('button')
      .find((button) => button.text().trim() === 'Kredensial')
    expect(credentialButton).toBeDefined()
    await credentialButton!.trigger('click')
    await wrapper
      .get('[data-testid="device-credential-dialog"] button.button--primary')
      .trigger('click')
    await flushPromises()

    expect((wrapper.get('#device-install-platform').element as HTMLSelectElement).value).toBe(
      'armbian',
    )
    expect((wrapper.get('#device-connection-mode').element as HTMLSelectElement).value).toBe(
      'private-network',
    )
    await wrapper.get('#device-core-api-url').setValue('https://core.school.test')
    await wrapper.get('#device-central-ai-url').setValue('https://ai.school.test')

    const command = wrapper.get('[data-testid="device-install-command"]').text()
    expect(command).toContain('curl -fsSL')
    expect(command).toContain('https://core.school.test')
    expect(command).toContain('https://ai.school.test')
    expect(command).toContain(gateway.device_id)
    expect(command).not.toContain('a'.repeat(48))
    wrapper.unmount()
  })
})
