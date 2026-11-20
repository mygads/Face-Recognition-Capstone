import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useAuthStore } from '../stores/auth'
import DevicesView from './DevicesView.vue'

const api = vi.hoisted(() => ({
  listDevices: vi.fn(),
  listLaboratories: vi.fn(),
  getAiReadiness: vi.fn(),
  getDeviceRuntimeConfiguration: vi.fn(),
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
    window.localStorage.clear()
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
    api.getDeviceRuntimeConfiguration.mockResolvedValue({
      device_id: device.device_id,
      deployment_profile: 'AI_EDGE',
      camera_enabled: true,
      revision: 1,
      settings: {
        min_top1_similarity: null,
        min_top1_top2_margin: null,
        calibration_reference: null,
      },
      applied_revision: 0,
      apply_status: 'not_configured',
      error_code: null,
      updated_at: null,
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
    expect(wrapper.text()).not.toContain('PIN layar per lab')
    expect(wrapper.find('[data-testid="laboratory-display-pin-table"]').exists()).toBe(false)
    expect(wrapper.find('.devices-view__profile-note').text()).toContain('satu PC kamera')
    expect(wrapper.find('#device-central-ai-url').exists()).toBe(false)
    expect(wrapper.find('#device-connection-mode').exists()).toBe(false)
    expect(wrapper.find('[data-testid="device-setup-defaults-card"]').text()).toContain(
      'http://127.0.0.1:8000',
    )
    expect(wrapper.find('#device-default-model-version').exists()).toBe(false)
    await wrapper.get('.devices-view__advanced-defaults > summary').trigger('click')
    await wrapper.get('[data-testid="edit-device-setup-defaults"]').trigger('click')
    expect(
      wrapper.get('[data-testid="device-setup-defaults-dialog"]').text().toLowerCase(),
    ).toContain('token perangkat tidak disimpan')
    await wrapper.get('#device-default-core-api-url').setValue('https://unsaved.school.test')
    await wrapper.get('.st-modal__foot button').trigger('click')
    expect(wrapper.find('[data-testid="device-setup-defaults-dialog"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="device-setup-defaults-card"]').text()).toContain(
      'http://127.0.0.1:8000',
    )
    await wrapper.get('[data-testid="edit-device-setup-defaults"]').trigger('click')
    expect((wrapper.get('#device-default-core-api-url').element as HTMLInputElement).value).toBe(
      'http://127.0.0.1:8000',
    )
    expect(wrapper.get('#device-default-model-version').attributes('disabled')).toBeDefined()
    expect((wrapper.get('#device-default-model-version').element as HTMLInputElement).value).toBe(
      'opencv-zoo-sface-2021dec',
    )
    await wrapper.get('[data-testid="save-device-setup-defaults"]').trigger('click')
    expect(wrapper.find('[data-testid="device-setup-defaults-dialog"]').exists()).toBe(false)
    const savedDefaults = JSON.parse(
      window.localStorage.getItem('presensi.device-setup-defaults.v1') ?? '{}',
    ) as { coreApiUrl?: string; modelVersion?: string }
    expect(savedDefaults.coreApiUrl).toBe('http://127.0.0.1:8000')
    expect(savedDefaults.modelVersion).toBe('opencv-zoo-sface-2021dec')
    expect(
      wrapper.findAll('button').some((button) => button.text().trim() === 'Daftarkan perangkat'),
    ).toBe(false)
    const credentialButton = wrapper
      .findAll('button')
      .find((button) => button.text().trim() === 'Lanjutkan setup')
    expect(credentialButton).toBeDefined()
    await credentialButton!.trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-testid="device-credential-dialog"]').text()).toContain(
      'Buat akses agent satu kali',
    )
    expect(api.provisionDeviceCredential).not.toHaveBeenCalled()
    await wrapper.get('[data-testid="edge-wizard-provision"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-testid="device-credential-dialog"]').text()).toContain(
      'Jalankan setup di PC kamera',
    )
    await wrapper.get('#device-install-platform').setValue('windows')

    expect(wrapper.get('[data-testid="device-install-command"]').text()).toContain(
      '-UseWorkingCopy',
    )
    expect(wrapper.get('[data-testid="device-install-command"]').text()).toContain(device.device_id)
    expect(api.provisionDeviceCredential).toHaveBeenCalledWith(device.device_id)

    expect(wrapper.find('#device-connection-mode').exists()).toBe(false)
    expect((wrapper.get('#device-core-api-url').element as HTMLInputElement).value).toBe(
      'http://127.0.0.1:8000',
    )
    expect(wrapper.get('#device-install-platform').element).toBeDefined()
    expect(wrapper.text()).toContain('Paket setup berisi token rahasia')
    wrapper.unmount()
  })

  it('shows camera read latency when reported and removes duplicate preview actions', async () => {
    api.listDevices.mockResolvedValue({
      items: [
        {
          ...device,
          latency_summary: { p50_ms: 18.4, p95_ms: 42.7 },
        },
      ],
      pagination: { total: 1, limit: 10, offset: 0 },
    })
    const wrapper = mount(DevicesView, { global: { plugins: [adminPinia()] } })
    await flushPromises()

    expect(wrapper.get('[data-label="Baca kamera p50 / p95"]').text()).toContain('18.4 / 42.7 ms')
    expect(wrapper.text()).not.toContain('Uji kamera')
    expect(wrapper.text()).not.toContain('Uji wajah di preview AI_EDGE')
    wrapper.unmount()
  })

  it('explains when the agent has not reported camera read latency yet', async () => {
    const wrapper = mount(DevicesView, { global: { plugins: [adminPinia()] } })
    await flushPromises()

    expect(wrapper.get('[data-label="Baca kamera p50 / p95"]').text()).toBe('Belum ada sampel')
    wrapper.unmount()
  })

  it('opens device registration and edit forms in modals', async () => {
    const createdDevice = {
      ...device,
      device_id: 'new-device-id',
      name: 'Camera PC 2',
      last_seen_at: null,
    }
    api.listDevices.mockResolvedValue({
      items: [],
      pagination: { total: 0, limit: 10, offset: 0 },
    })
    api.listLaboratories.mockResolvedValue({
      items: [
        {
          id: 'lab-1',
          code: 'LAB-1',
          name: 'Laboratory 1',
          location: null,
          is_active: true,
          created_at: '2026-11-01T00:00:00Z',
          updated_at: '2026-11-01T00:00:00Z',
          has_display_pin: false,
        },
      ],
      pagination: { total: 1, limit: 100, offset: 0 },
    })
    api.createDevice.mockResolvedValue(createdDevice)
    const wrapper = mount(DevicesView, { global: { plugins: [adminPinia()] } })
    await flushPromises()

    const addButton = wrapper
      .findAll('button')
      .find((button) => button.text().trim() === 'Siapkan kamera')
    expect(addButton).toBeDefined()
    await addButton!.trigger('click')
    expect(wrapper.get('.st-modal[role="dialog"]').attributes('aria-label')).toBe(
      'Siapkan PC kamera',
    )
    await wrapper.get('[data-testid="register-device-name"]').setValue('Camera PC 2')
    await wrapper.get('[data-testid="register-device-lab"]').setValue('lab-1')
    await wrapper.get('[data-testid="submit-device-registration"]').trigger('click')
    await flushPromises()

    expect(api.createDevice).toHaveBeenCalledWith({
      name: 'Camera PC 2',
      laboratory_id: 'lab-1',
      deployment_profile: 'AI_EDGE',
      device_type: 'edge_pc',
    })
    expect(wrapper.find('[data-testid="device-credential-dialog"]').exists()).toBe(true)
    expect(api.provisionDeviceCredential).toHaveBeenCalledWith(createdDevice.device_id)
    wrapper.unmount()

    api.listDevices.mockResolvedValue({
      items: [device],
      pagination: { total: 1, limit: 10, offset: 0 },
    })
    const editWrapper = mount(DevicesView, { global: { plugins: [adminPinia()] } })
    await flushPromises()
    const editButton = editWrapper
      .findAll('button')
      .find((button) => button.text().trim() === 'Ubah')
    expect(editButton).toBeDefined()
    await editButton!.trigger('click')
    expect(editWrapper.get('.st-modal[role="dialog"]').attributes('aria-label')).toBe(
      'Ubah perangkat',
    )
    expect(editWrapper.get('[data-testid="submit-device-registration"]').text()).toContain(
      'Simpan perubahan',
    )
    editWrapper.unmount()
  })

  it('explains why a newly registered device is active in the registry but offline', async () => {
    const wrapper = mount(DevicesView, { global: { plugins: [adminPinia()] } })
    await flushPromises()

    expect(wrapper.text()).toContain('Terdaftar aktif; agent belum mengirim heartbeat.')
    expect(
      wrapper.findAll('button').some((button) => button.text().trim() === 'Lanjutkan setup'),
    ).toBe(true)
    expect(wrapper.find('button[aria-label="Jeda kamera"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('Timeout 60 detik')
    wrapper.unmount()
  })

  it('explains a warning caused by the admin pausing the camera', async () => {
    api.listDevices.mockResolvedValue({
      items: [
        {
          ...device,
          camera_enabled: false,
          camera_status: 'disabled',
          health_status: 'warning',
          last_seen_at: '2026-11-19T01:00:00Z',
        },
      ],
      pagination: { total: 1, limit: 10, offset: 0 },
    })
    const wrapper = mount(DevicesView, { global: { plugins: [adminPinia()] } })
    await flushPromises()

    expect(wrapper.get('[data-label="Status"]').text()).toContain('Kamera dijeda admin.')
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
    await wrapper.get('[data-testid="device-delete-dialog"] .st-btn--danger').trigger('click')
    await flushPromises()

    expect(api.deleteDevice).toHaveBeenCalledWith(device.device_id, { permanent: false })
    expect(wrapper.text()).toContain('Belum ada perangkat yang cocok.')
    expect(
      wrapper.findAll('button').some((button) => button.text().trim() === 'Siapkan kamera'),
    ).toBe(true)
    wrapper.unmount()
  })

  it('allows editing and permanently removing an inactive device', async () => {
    const inactiveDevice = { ...device, is_active: false }
    api.listDevices.mockImplementation(async (query: { is_active?: boolean }) =>
      query.is_active === true
        ? { items: [], pagination: { total: 0, limit: 10, offset: 0 } }
        : { items: [inactiveDevice], pagination: { total: 1, limit: 10, offset: 0 } },
    )
    const wrapper = mount(DevicesView, { global: { plugins: [adminPinia()] } })
    await flushPromises()

    await wrapper.get('input[type="checkbox"]').setValue(true)
    await flushPromises()
    const editButton = wrapper.findAll('button').find((button) => button.text().trim() === 'Ubah')
    expect(editButton?.attributes('disabled')).toBeUndefined()
    await editButton!.trigger('click')
    expect(wrapper.get('.st-modal[role="dialog"]').attributes('aria-label')).toBe('Ubah perangkat')
    await wrapper.get('.st-modal__foot button').trigger('click')
    await flushPromises()

    const permanentDeleteButton = wrapper
      .findAll('button')
      .find((button) => button.text().trim() === 'Hapus permanen')
    expect(permanentDeleteButton?.attributes('disabled')).toBeUndefined()
    await permanentDeleteButton!.trigger('click')
    expect(wrapper.get('[data-testid="device-delete-dialog"]').text()).toContain('Hapus permanen')
    expect(api.deleteDevice).not.toHaveBeenCalled()
    await wrapper.get('[data-testid="device-delete-dialog"] .st-btn--danger').trigger('click')
    await flushPromises()

    expect(api.deleteDevice).toHaveBeenCalledWith(device.device_id, { permanent: true })
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
      .find((button) => button.text().trim() === 'Siapkan agent')
    expect(credentialButton).toBeDefined()
    await credentialButton!.trigger('click')
    await wrapper.get('[data-testid="device-credential-dialog"] .st-btn--primary').trigger('click')
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
