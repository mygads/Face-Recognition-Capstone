import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useAuthStore } from '../stores/auth'
import CorrectionsView from './CorrectionsView.vue'

const api = vi.hoisted(() => ({
  listAttendanceCorrections: vi.fn(),
  getAttendanceCorrection: vi.fn(),
  decideAttendanceCorrection: vi.fn(),
  listAttendanceSessions: vi.fn(),
  getSessionRoster: vi.fn(),
}))

vi.mock('../api/client', () => ({
  ApiError: class ApiError extends Error {},
  ...api,
}))

const correction = {
  id: '11111111-2222-3333-4444-555555555555',
  attendance_record_id: 'rec-1',
  session_id: 'sess-1',
  student_id: 'stu-1',
  previous_status: 'absent',
  corrected_status: 'late',
  decision_status: 'pending',
  reason: 'Datang terlambat 7 menit',
  created_at: '2026-11-07T06:00:00Z',
  decided_at: null,
}

function testRouter(path: string) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/app/corrections', name: 'corrections', component: { template: '<div />' } },
      {
        path: '/app/corrections/:correctionId',
        name: 'correction-detail',
        component: { template: '<div />' },
      },
    ],
  })
  router.push(path)
  return router
}

function piniaWith(role: string) {
  const pinia = createPinia()
  useAuthStore(pinia).$patch({
    accessToken: 't',
    expiresAt: Date.now() + 60_000,
    account: {
      id: 'u-1',
      email: 'a@test.id',
      full_name: 'Admin Test',
      roles: [role],
      must_change_password: false,
    },
  })
  return pinia
}

async function mountAt(path: string, role = 'ADMIN') {
  const router = testRouter(path)
  await router.isReady()
  const wrapper = mount(CorrectionsView, { global: { plugins: [piniaWith(role), router] } })
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  vi.clearAllMocks()
  const page = (items: unknown[], total: number) => ({
    items,
    pagination: { total, limit: 50, offset: 0 },
  })
  api.listAttendanceCorrections.mockImplementation(
    ({ decision_status }: { decision_status: string }) =>
      Promise.resolve(
        page(
          decision_status === 'pending' ? [correction] : [],
          decision_status === 'pending' ? 1 : 0,
        ),
      ),
  )
  api.listAttendanceSessions.mockResolvedValue({
    items: [{ id: 'sess-1', subject: 'Praktikum Web' }],
    pagination: { total: 1 },
  })
  api.getSessionRoster.mockResolvedValue([{ student_id: 'stu-1', full_name: 'Ahmad Fauzi' }])
  api.getAttendanceCorrection.mockResolvedValue(correction)
  api.decideAttendanceCorrection.mockResolvedValue({ ...correction, decision_status: 'approved' })
})

describe('corrections view (Stitch B03-07/08/09/10)', () => {
  it('menampilkan antrean dengan nama siswa dan sesi hasil enrichment', async () => {
    const wrapper = await mountAt('/app/corrections')
    expect(wrapper.text()).toContain('Koreksi Kehadiran')
    expect(wrapper.text()).toContain('Ahmad Fauzi')
    expect(wrapper.text()).toContain('Praktikum Web')
    expect(wrapper.text()).toContain('Menunggu Keputusan (1)')
    wrapper.unmount()
  })

  it('guru melihat judul Koreksi Saya tanpa tombol keputusan', async () => {
    const wrapper = await mountAt('/app/corrections', 'TEACHER')
    expect(wrapper.text()).toContain('Koreksi Saya')
    expect(wrapper.find('[data-testid="correction-approve"]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('detail menampilkan perbandingan dan menolak tanpa catatan', async () => {
    const wrapper = await mountAt(`/app/corrections/${correction.id}`)
    expect(wrapper.text()).toContain('Perubahan Status Presensi')
    await wrapper.get('[data-testid="correction-reject"]').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('Alasan penolakan wajib diisi')
    expect(api.decideAttendanceCorrection).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('menyetujui dengan catatan keputusan', async () => {
    const wrapper = await mountAt(`/app/corrections/${correction.id}`)
    await wrapper.get('[data-testid="correction-decision-note"]').setValue('Bukti cukup')
    await wrapper.get('[data-testid="correction-approve"]').trigger('click')
    await flushPromises()
    expect(api.decideAttendanceCorrection).toHaveBeenCalledWith(correction.id, {
      decision: 'approved',
      decision_note: 'Bukti cukup',
    })
    wrapper.unmount()
  })
})
