import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import DisplayView from './DisplayView.vue'

const api = vi.hoisted(() => ({
  getKioskDisplay: vi.fn(),
  getPublicDisplay: vi.fn(),
  listPublicKioskScreens: vi.fn(async () => []),
  listPublicLaboratories: vi.fn(async () => [{ id: 'lab-1', code: 'LAB-1', name: 'Lab Kimia 1' }]),
  openKioskDisplaySession: vi.fn(),
  openPublicDisplaySession: vi.fn(),
}))

vi.mock('../api/client', () => ({
  ApiError: class ApiError extends Error {},
  ...api,
}))

const snapshot = {
  laboratory_name: 'Lab Kimia 1',
  subject: 'Uji Larutan',
  status: 'active',
  present_count: 1,
  late_count: 1,
  total_roster: 3,
  students: [
    {
      student_number: 'S-001',
      full_name: 'Raka Pratama',
      status: 'late',
      recorded_at: '2026-11-06T06:18:00+07:00',
    },
    {
      student_number: 'S-002',
      full_name: 'Sinta Anggraini',
      status: 'present',
      recorded_at: '2026-11-06T06:05:00+07:00',
    },
    { student_number: 'S-003', full_name: 'Budi Santoso', status: 'absent', recorded_at: null },
  ],
}

describe('DisplayView ala Stitch', () => {
  it('menampilkan nama singkat tanpa NIS dan sorotan hasil terakhir', async () => {
    api.openPublicDisplaySession.mockResolvedValueOnce({
      display_token: 'tok',
      snapshot,
    })
    const w = mount(DisplayView)
    await flushPromises()
    await w.find('[data-testid="display-pin-input"]').setValue('1234')
    await w.find('form').trigger('submit.prevent')
    await flushPromises()
    const board = w.find('[data-testid="display-board"]')
    expect(board.exists()).toBe(true)
    // nama singkat ala Stitch, bukan NIS penuh
    expect(board.text()).toContain('Raka P.')
    expect(board.text()).not.toContain('S-001')
    // sorotan hasil terakhir = Raka (terbaru) dengan badge TERLAMBAT
    const spotlight = w.find('[data-testid="display-spotlight"]')
    expect(spotlight.exists()).toBe(true)
    expect(spotlight.text()).toContain('Raka P.')
    expect(spotlight.text()).toContain('TERLAMBAT')
  })
})
