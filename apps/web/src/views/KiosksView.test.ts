import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useAuthStore } from '../stores/auth'
import KiosksView from './KiosksView.vue'

const api = vi.hoisted(() => ({
  createKiosk: vi.fn(),
  listDevices: vi.fn(),
  listKiosks: vi.fn(),
  listLaboratories: vi.fn(),
  resetKioskPin: vi.fn(),
  revokeKiosk: vi.fn(),
  updateKiosk: vi.fn(),
}))

vi.mock('../api/client', () => ({
  ApiError: class ApiError extends Error {},
  ...api,
}))

function adminPinia() {
  const pinia = createPinia()
  useAuthStore(pinia).$patch({
    accessToken: 'unit-test-token',
    expiresAt: Date.now() + 60_000,
    account: {
      id: 'admin-1',
      email: 'admin@example.test',
      full_name: 'Test Admin',
      roles: ['ADMIN'],
      must_change_password: false,
      permissions: [],
    },
  })
  return pinia
}

const kiosk = {
  id: 'kiosk-1',
  device_id: 'device-1',
  laboratory_id: 'lab-1',
  display_name: 'Kiosk Uji',
  camera_label: null,
  token_ttl_hours: null,
  has_pin: true,
  is_active: true,
  last_seen_at: null,
  created_at: '2026-11-06T00:00:00Z',
  updated_at: '2026-11-06T00:00:00Z',
}

describe('kiosks view ttl', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.listKiosks.mockResolvedValue({ items: [kiosk], pagination: { total: 1 } })
    api.listDevices.mockResolvedValue({ items: [], pagination: { total: 0 } })
    api.listLaboratories.mockResolvedValue({ items: [], pagination: { total: 0 } })
  })

  it('menampilkan TTL Default untuk kiosk tanpa TTL dan mengirim 8 jam saat diubah', async () => {
    const wrapper = mount(KiosksView, { global: { plugins: [adminPinia()] } })
    await flushPromises()
    const selects = wrapper.findAll('[data-testid="kiosk-ttl-row"]')
    expect(selects).toHaveLength(1)
    expect((selects[0].element as HTMLSelectElement).value).toBe('')
    api.updateKiosk.mockResolvedValueOnce({ ...kiosk, token_ttl_hours: 8 })
    await selects[0].setValue('8')
    await flushPromises()
    expect(api.updateKiosk).toHaveBeenCalledWith('kiosk-1', { token_ttl_hours: 8 })
  })

  it('form pendaftaran mengirim TTL yang dipilih', async () => {
    const wrapper = mount(KiosksView, { global: { plugins: [adminPinia()] } })
    await flushPromises()
    await wrapper.find('[data-testid="kiosk-name"]').setValue('Kiosk Baru')
    await wrapper.find('[data-testid="kiosk-ttl"]').setValue('2')
    api.createKiosk.mockResolvedValueOnce({ ...kiosk, id: 'kiosk-2' })
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()
    expect(api.createKiosk).toHaveBeenCalledWith(
      expect.objectContaining({ display_name: 'Kiosk Baru', token_ttl_hours: 2 }),
    )
  })
})
