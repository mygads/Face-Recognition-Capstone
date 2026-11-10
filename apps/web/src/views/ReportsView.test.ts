import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useAuthStore } from '../stores/auth'
import ReportsView from './ReportsView.vue'

vi.mock('vue-router', async (importOriginal) => {
  const actual = await importOriginal<typeof import('vue-router')>()
  return { ...actual, useRoute: () => ({ query: {} }) }
})

const api = vi.hoisted(() => ({
  downloadAttendanceReport: vi.fn(),
  getAttendanceReportSummary: vi.fn(),
  listAttendanceReportRows: vi.fn(),
  listAttendanceSessions: vi.fn(),
  listSchedules: vi.fn(),
}))

vi.mock('../api/client', () => ({
  ApiError: class ApiError extends Error {
    code?: string
    details?: { field: string; message: string }[]
  },
  ...api,
}))

const summary = {
  starts_on: '2026-09-01',
  ends_on: '2026-09-30',
  total_rows: 2,
  present_count: 1,
  late_count: 0,
  absent_count: 0,
  excused_count: 1,
  not_recorded_count: 0,
  generated_at: '2026-09-30T10:00:00Z',
}

function reportRow(note: string | null) {
  return {
    attendance_record_id: 'aaaaaaaa-0000-4000-8000-000000000001',
    session_id: 'bbbbbbbb-0000-4000-8000-000000000002',
    student_id: 'cccccccc-0000-4000-8000-000000000003',
    student_number: 'S-001',
    student_name: 'Siswa Satu',
    class_id: 'dddddddd-0000-4000-8000-000000000004',
    class_code: 'X-A',
    class_name: 'Kelas X A',
    laboratory_id: 'eeeeeeee-0000-4000-8000-000000000005',
    laboratory_code: 'LAB-A',
    laboratory_name: 'Lab A',
    subject: 'Praktikum Sintetis',
    teacher_name: 'Guru Uji',
    status: 'excused',
    source: 'manual',
    session_opened_at: '2026-09-15T02:00:00Z',
    recorded_at: '2026-09-15T02:10:00Z',
    note,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  api.listSchedules.mockResolvedValue({
    items: [],
    pagination: { total: 0, limit: 100, offset: 0 },
  })
  api.listAttendanceSessions.mockResolvedValue({
    items: [],
    pagination: { total: 0, limit: 100, offset: 0 },
  })
  api.getAttendanceReportSummary.mockResolvedValue(summary)
  api.listAttendanceReportRows.mockResolvedValue({
    items: [reportRow('Surat dokter dari TU'), reportRow(null)],
    pagination: { total: 2, limit: 20, offset: 0 },
  })
})

function adminPinia() {
  const pinia = createPinia()
  useAuthStore(pinia).$patch({
    accessToken: 'unit-test-token',
    expiresAt: Date.now() + 60_000,
    account: {
      id: 'admin-1',
      email: 'admin@example.test',
      full_name: 'Admin Uji',
      roles: ['ADMIN'],
      must_change_password: false,
      permissions: [],
    },
  })
  return pinia
}

describe('reports view teacher notes', () => {
  it('shows the manual-mark note in the recap table', async () => {
    const wrapper = mount(ReportsView, { global: { plugins: [adminPinia()] } })
    await flushPromises()
    const table = wrapper.find('table.reports__table')
    expect(table.exists()).toBe(true)
    const headers = table.findAll('thead th').map((th) => th.text())
    expect(headers).toContain('Catatan')
    expect(table.text()).toContain('Surat dokter dari TU')
    expect(table.text()).toContain('–')
  })
})
