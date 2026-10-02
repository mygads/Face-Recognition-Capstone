import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useAuthStore } from '../stores/auth'
import DevicesView from './DevicesView.vue'

const api = vi.hoisted(() => ({
  listDevices: vi.fn(),
  listLaboratories: vi.fn(),
  getAiReadiness: vi.fn(),
  provisionDeviceCredential: vi.fn(),
  rotateDeviceCredential: vi.fn(),
  createDevice: vi.fn(),
  updateDevice: vi.fn(),
  deleteDevice: vi.fn(),
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
    api.getAiReadiness.mockResolvedValue({
      deployment_profile: 'AI_EDGE',
      enrollment_models_ready: true,
      enrollment_model_version: 'opencv-zoo-sface-2021dec',
      enrollment_quality_revision: 0,
      central_ai_status: 'disabled',
      central_ai_models_ready: null,
      central_ai_model_version: null,
      central_ai_thresholds_configured: null,
      central_ai_recognition_ready: null,
      central_ai_config_desired_revision: null,
      central_ai_config_applied_revision: null,
      central_ai_config_sync_status: null,
    })
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
    api.deleteDevice.mockImplementation(async () => {
      api.listDevices.mockResolvedValue({
        items: [],
        pagination: { total: 0, limit: 10, offset: 0 },
      })
    })
  })

  it('auto-fills local AI_EDGE setup and hides STB-only controls', async () => {
    const wrapper = mount(DevicesView, { global: { plugins: [adminPinia()] } })
    await flushPromises()
    expect(wrapper.find('.devices-view__profile-note').text()).toContain('satu PC kamera')
    expect(wrapper.find('#device-central-ai-url').exists()).toBe(false)
    expect(wrapper.find('#device-connection-mode').exists()).toBe(false)
    expect(wrapper.get('#device-default-model-version').attributes('readonly')).toBeDefined()
    expect(
      wrapper.findAll('button').some((button) => button.text().trim() === 'Daftarkan perangkat'),
    ).toBe(false)
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

    expect(wrapper.find('#device-connection-mode').exists()).toBe(false)
    expect((wrapper.get('#device-core-api-url').element as HTMLInputElement).value).toBe(
      'http://127.0.0.1:8000',
    )
    expect(wrapper.get('#device-model-version').attributes('readonly')).toBeDefined()
    wrapper.unmount()
  })

  it('requires confirmation, then deactivates the edge device from the registry', async () => {
    const wrapper = mount(DevicesView, { global: { plugins: [adminPinia()] } })
    await flushPromises()
    await wrapper
      .findAll('button')
      .find((button) => button.text().trim() === 'Hapus')!
      .trigger('click')

    expect(wrapper.get('[data-testid="device-delete-dialog"]').text()).toContain(
      'Data presensi dan audit lama tetap tersimpan',
    )
    expect(api.deleteDevice).not.toHaveBeenCalled()
    await wrapper.get('[data-testid="device-delete-dialog"] .button--danger').trigger('click')
    await flushPromises()

    expect(api.deleteDevice).toHaveBeenCalledWith(device.device_id)
    expect(wrapper.text()).toContain('Belum ada perangkat yang cocok.')
    expect(
      wrapper.findAll('button').some((button) => button.text().trim() === 'Daftarkan perangkat'),
    ).toBe(true)
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
    api.getAiReadiness.mockResolvedValue({
      deployment_profile: 'AI_CENTRAL',
      enrollment_models_ready: true,
      enrollment_model_version: 'opencv-zoo-sface-2021dec',
      enrollment_quality_revision: 0,
      central_ai_status: 'degraded',
      central_ai_models_ready: true,
      central_ai_model_version: 'opencv-zoo-sface-2021dec',
      central_ai_thresholds_configured: false,
      central_ai_recognition_ready: false,
      central_ai_config_desired_revision: 0,
      central_ai_config_applied_revision: 0,
      central_ai_config_sync_status: 'pending',
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
      'same-host',
    )
    expect((wrapper.get('#device-core-api-url').element as HTMLInputElement).value).toBe(
      'http://127.0.0.1:8000',
    )
    await wrapper.get('#device-connection-mode').setValue('private-network')
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
