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
  revokeLaboratoryDisplayPin: vi.fn(),
  revokeKiosk: vi.fn(),
  setLaboratoryDisplayPin: vi.fn(),
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

const device = {
  device_id: 'device-1',
  laboratory_id: 'lab-1',
  name: 'PClab Uji',
  laboratory_name: 'Lab Kimia 1',
}

describe('kiosks view ttl', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.listKiosks.mockResolvedValue({ items: [kiosk], pagination: { total: 1 } })
    api.listDevices.mockResolvedValue({ items: [device], pagination: { total: 1 } })
    api.listLaboratories.mockResolvedValue({ items: [], pagination: { total: 0 } })
    api.setLaboratoryDisplayPin.mockResolvedValue(undefined)
    api.revokeLaboratoryDisplayPin.mockResolvedValue(undefined)
  })

  it('menampilkan masa sesi default dan mengubahnya lewat modal edit layar', async () => {
    const wrapper = mount(KiosksView, { global: { plugins: [adminPinia()] } })
    await flushPromises()
    expect(wrapper.find('[data-testid="kiosk-row"]').text()).toContain('Default server')
    await wrapper.get('[data-testid="edit-kiosk-kiosk-1"]').trigger('click')
    expect(wrapper.find('[data-testid="kiosk-edit-dialog"]').exists()).toBe(true)
    api.updateKiosk.mockResolvedValueOnce({ ...kiosk, token_ttl_hours: 8 })
    await wrapper.get('[data-testid="edit-kiosk-ttl"]').setValue('8')
    await wrapper.find('#kiosk-edit-form').trigger('submit.prevent')
    await flushPromises()
    expect(api.updateKiosk).toHaveBeenCalledWith(
      'kiosk-1',
      expect.objectContaining({ token_ttl_hours: 8 }),
    )
    expect(wrapper.find('[data-testid="kiosk-edit-dialog"]').exists()).toBe(false)
  })

  it('menampilkan Buat PIN jika layar belum memiliki PIN', async () => {
    api.listKiosks.mockResolvedValue({
      items: [{ ...kiosk, has_pin: false }],
      pagination: { total: 1 },
    })
    const wrapper = mount(KiosksView, { global: { plugins: [adminPinia()] } })
    await flushPromises()

    expect(wrapper.get('[data-testid="kiosk-pin-action-kiosk-1"]').text()).toBe('Buat PIN')
    wrapper.unmount()
  })

  it('tombol pendaftaran membuka modal dan memilih lab dari perangkat', async () => {
    const wrapper = mount(KiosksView, { global: { plugins: [adminPinia()] } })
    await flushPromises()
    expect(wrapper.find('[data-testid="kiosk-registration-dialog"]').exists()).toBe(false)
    await wrapper.get('[data-testid="open-kiosk-registration"]').trigger('click')
    expect(wrapper.find('[data-testid="kiosk-registration-dialog"]').exists()).toBe(true)
    expect(wrapper.get('[data-testid="selected-kiosk-lab"]').text()).toContain('Lab Kimia 1')
    await wrapper.find('[data-testid="kiosk-name"]').setValue('Kiosk Baru')
    await wrapper.find('[data-testid="kiosk-ttl"]').setValue('2')
    api.createKiosk.mockResolvedValueOnce({ ...kiosk, id: 'kiosk-2' })
    await wrapper.find('#kiosk-registration-form').trigger('submit.prevent')
    await flushPromises()
    expect(api.createKiosk).toHaveBeenCalledWith(
      expect.objectContaining({
        display_name: 'Kiosk Baru',
        device_id: 'device-1',
        laboratory_id: 'lab-1',
        token_ttl_hours: 2,
      }),
    )
    expect(wrapper.find('[data-testid="kiosk-registration-dialog"]').exists()).toBe(false)
  })

  it('membuka layar kiosk di tab baru', async () => {
    const wrapper = mount(KiosksView, { global: { plugins: [adminPinia()] } })
    await flushPromises()

    const link = wrapper.get('[data-testid="open-kiosk-new-tab"]')
    expect(link.attributes('href')).toBe('/presensi')
    expect(link.attributes('target')).toBe('_blank')
    expect(link.attributes('rel')).toContain('noopener')
    expect(link.text()).toContain('Buka kiosk di tab baru')
    wrapper.unmount()
  })

  it('mengelola PIN publik lab dari halaman kiosk dan hanya menerima angka', async () => {
    api.listLaboratories.mockResolvedValue({
      items: [
        {
          id: 'lab-1',
          code: 'LAB-1',
          name: 'Lab Kimia 1',
          location: null,
          is_active: true,
          created_at: '2026-11-06T00:00:00Z',
          updated_at: '2026-11-06T00:00:00Z',
          has_display_pin: false,
        },
      ],
      pagination: { total: 1 },
    })
    const wrapper = mount(KiosksView, { global: { plugins: [adminPinia()] } })
    await flushPromises()

    expect(wrapper.find('[data-testid="laboratory-display-pin-table"]').text()).toContain(
      'Belum diatur',
    )
    await wrapper.get('button[aria-label="Atur PIN untuk Lab Kimia 1"]').trigger('click')
    expect(wrapper.find('[data-testid="laboratory-display-pin-dialog"]').exists()).toBe(true)
    const input = wrapper.get('[data-testid="laboratory-display-pin-input"]')
    await input.setValue('12a34')
    expect((input.element as HTMLInputElement).value).toBe('1234')
    await wrapper.get('[data-testid="save-laboratory-display-pin"]').trigger('click')
    await flushPromises()

    expect(api.setLaboratoryDisplayPin).toHaveBeenCalledWith('lab-1', '1234')
    expect(wrapper.find('[data-testid="laboratory-display-pin-table"]').text()).toContain(
      'Sudah diatur',
    )
    expect(wrapper.find('[data-testid="laboratory-display-pin-dialog"]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('menghapus PIN publik lewat konfirmasi dan mencabut sesi layar aktif', async () => {
    api.listLaboratories.mockResolvedValue({
      items: [
        {
          id: 'lab-1',
          code: 'LAB-1',
          name: 'Lab Kimia 1',
          location: null,
          is_active: true,
          created_at: '2026-11-06T00:00:00Z',
          updated_at: '2026-11-06T00:00:00Z',
          has_display_pin: true,
        },
      ],
      pagination: { total: 1 },
    })
    const wrapper = mount(KiosksView, { global: { plugins: [adminPinia()] } })
    await flushPromises()

    await wrapper.get('[data-testid="delete-public-pin-lab-1"]').trigger('click')
    expect(wrapper.find('[data-testid="delete-public-pin-dialog"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="delete-public-pin-dialog"]').text().toLowerCase()).toContain(
      'sesi layar publik yang sedang aktif juga akan dicabut',
    )
    await wrapper.get('[data-testid="confirm-delete-public-pin"]').trigger('click')
    await flushPromises()

    expect(api.revokeLaboratoryDisplayPin).toHaveBeenCalledWith('lab-1')
    expect(wrapper.find('[data-testid="delete-public-pin-dialog"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="laboratory-display-pin-table"]').text()).toContain(
      'Belum diatur',
    )
  })
})
