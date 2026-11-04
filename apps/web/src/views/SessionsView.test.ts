import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../api/client'
import { useAuthStore } from '../stores/auth'
import SessionsView from './SessionsView.vue'

const api = vi.hoisted(() => ({
  listOpenableSchedules: vi.fn(),
  listAttendanceSessions: vi.fn(),
  getSessionOpeningPolicy: vi.fn(),
  saveSessionOpeningPolicy: vi.fn(),
  getOpeningPreference: vi.fn(),
  saveOpeningPreference: vi.fn(),
  openAttendanceSession: vi.fn(),
  closeAttendanceSession: vi.fn(),
  getAttendanceSessionStatus: vi.fn(),
  getSessionRoster: vi.fn(),
  markManualAttendance: vi.fn(),
}))

vi.mock('../api/client', () => ({
  ApiError: class ApiError extends Error {
    code?: string
    details?: { field: string; message: string }[]
    constructor(_status?: number, code?: string, message?: string) {
      super(message)
      if (code !== undefined) this.code = code
    }
  },
  ...api,
}))

const schedule = {
  id: 'schedule-1',
  subject: 'Praktikum Sintetis',
  class_name: 'Kelas X A',
  laboratory_name: 'Lab Biologi',
  teacher_name: 'Test Teacher',
  weekday: 0,
  start_time: '09:00:00',
  end_time: '11:00:00',
  timezone_name: 'Asia/Jakarta',
}

const overrideSession = {
  id: 'session-1',
  practicum_schedule_id: 'schedule-1',
  status: 'manual_override',
  opened_automatically: false,
  opened_at: '2026-10-05T02:05:00Z',
  closed_at: null,
  grace_period_minutes: 15,
  student_count: 2,
  subject: 'Praktikum Sintetis',
  class_name: 'Kelas X A',
  laboratory_name: 'Lab Biologi',
  teacher_name: 'Test Teacher',
  weekday: 0,
  start_time: '09:00:00',
  end_time: '11:00:00',
  timezone_name: 'Asia/Jakarta',
  scheduled_end_at: '2026-10-05T04:00:00Z',
}

const policy = {
  mode: 'manual',
  auto_open_minutes_before: 0,
  auto_open_minutes_after: 15,
  default_grace_period_minutes: 15,
  revision: 0,
  updated_at: null,
}

function teacherPinia() {
  const pinia = createPinia()
  useAuthStore(pinia).$patch({
    accessToken: 'unit-test-token',
    expiresAt: Date.now() + 60_000,
    account: {
      id: 'teacher-1',
      email: 'teacher@example.test',
      full_name: 'Test Teacher',
      roles: ['TEACHER'],
      must_change_password: false,
    },
  })
  return pinia
}

describe('sessions view', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.listOpenableSchedules.mockResolvedValue([schedule])
    api.listAttendanceSessions.mockResolvedValue({
      items: [overrideSession],
      pagination: { total: 1, limit: 50, offset: 0 },
    })
    api.getSessionOpeningPolicy.mockResolvedValue(policy)
    api.getOpeningPreference.mockResolvedValue({
      opening_mode: 'manual',
      updated_at: null,
    })
  })

  it('keeps manual open visible and marks override sessions with a badge', async () => {
    const wrapper = mount(SessionsView, { global: { plugins: [teacherPinia()] } })
    await flushPromises()

    expect(wrapper.find('[data-testid="open-session-schedule-1"]').exists()).toBe(true)
    const badge = wrapper.get('[data-testid="session-status-override"]')
    expect(badge.text()).toBe('Override manual')
    expect(badge.classes()).toContain('status-badge--warning')
    expect(wrapper.find('[data-testid="teacher-opening-preference"]').exists()).toBe(true)
  })

  it('saves the teacher opening preference without a global mode select', async () => {
    const wrapper = mount(SessionsView, { global: { plugins: [teacherPinia()] } })
    await flushPromises()

    expect(wrapper.find('select[data-testid="opening-mode"]').exists()).toBe(false)
    api.saveOpeningPreference.mockResolvedValue({
      opening_mode: 'automatic',
      updated_at: '2026-10-05T02:00:00Z',
    })
    await wrapper.get('[data-testid="opening-mode-automatic"]').setValue()
    await wrapper.get('[data-testid="teacher-opening-preference"] form').trigger('submit')
    await flushPromises()

    expect(api.saveOpeningPreference).toHaveBeenCalledWith({
      opening_mode: 'automatic',
    })
    expect(wrapper.text()).toContain('dibuka otomatis dalam jendela jadwal')
  })

  it('marks unmarked roster students manually and maps duplicate errors', async () => {
    const rosterEntry = {
      student_id: 'student-1',
      student_number: 'S-001',
      full_name: 'Siswa Satu',
      record_status: null,
    }
    api.getAttendanceSessionStatus.mockResolvedValue(overrideSession)
    api.getSessionRoster.mockResolvedValue([rosterEntry])
    api.markManualAttendance.mockResolvedValue({ record: {} })
    const wrapper = mount(SessionsView, { global: { plugins: [teacherPinia()] } })
    await flushPromises()

    await wrapper.get('button.button--text').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('Siswa Satu')

    await wrapper.get('[data-testid="manual-mark-student-1"]').trigger('click')
    await flushPromises()
    expect(api.markManualAttendance).toHaveBeenCalledWith('session-1', {
      student_id: 'student-1',
      status: 'present',
    })
    expect(wrapper.text()).toContain('ditandai manual')

    const duplicate = new ApiError(409, 'attendance_already_recorded', 'duplikat')
    api.markManualAttendance.mockRejectedValueOnce(duplicate)
    await wrapper.get('[data-testid="manual-mark-student-1"]').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('sudah tercatat')
  })

  it('reloads lists when opening races with another opener', async () => {
    const wrapper = mount(SessionsView, { global: { plugins: [teacherPinia()] } })
    await flushPromises()

    const opened = { ...overrideSession, id: 'session-race' }
    api.openAttendanceSession.mockRejectedValueOnce(
      new ApiError(409, 'session_already_active', 'Sesi untuk jadwal ini masih terbuka.'),
    )
    api.listOpenableSchedules.mockResolvedValue([])
    api.listAttendanceSessions.mockResolvedValue({
      items: [opened],
      pagination: { total: 1, limit: 50, offset: 0 },
    })
    const reloadCalls = api.listOpenableSchedules.mock.calls.length
    await wrapper.get('[data-testid="open-session-schedule-1"]').trigger('click')
    await flushPromises()

    expect(api.listOpenableSchedules.mock.calls.length).toBeGreaterThan(reloadCalls)
    expect(wrapper.text()).toContain('sudah dibuka. Daftar dimuat ulang.')
  })
})

describe('session roster overview', () => {
  const rosterEntries = [
    {
      student_id: 'student-1',
      student_number: 'S-001',
      full_name: 'Siswa Satu',
      record_status: 'present',
    },
    {
      student_id: 'student-2',
      student_number: 'S-002',
      full_name: 'Siswa Dua',
      record_status: null,
    },
    {
      student_id: 'student-3',
      student_number: 'S-003',
      full_name: 'Siswi Tiga',
      record_status: 'late',
    },
  ]

  async function openDetail() {
    api.getAttendanceSessionStatus.mockResolvedValue(overrideSession)
    api.getSessionRoster.mockResolvedValue(rosterEntries)
    const wrapper = mount(SessionsView, { global: { plugins: [teacherPinia()] } })
    await flushPromises()
    await wrapper.get('button.button--text').trigger('click')
    await flushPromises()
    return wrapper
  }

  it('lists every roster entry with its attendance status', async () => {
    const wrapper = await openDetail()
    const rows = wrapper.findAll('[data-testid="roster-row"]')
    expect(rows).toHaveLength(3)
    expect(wrapper.text()).toContain('Semua (3)')
    expect(wrapper.text()).toContain('Belum tercatat (1)')
    expect(wrapper.text()).toContain('Hadir')
    expect(wrapper.text()).toContain('Terlambat')
  })

  it('shows the teacher note in the roster when a manual mark has one', async () => {
    api.getAttendanceSessionStatus.mockResolvedValue(overrideSession)
    api.getSessionRoster.mockResolvedValue([
      {
        student_id: 'student-1',
        student_number: 'S-001',
        full_name: 'Siswa Satu',
        record_status: 'excused',
        record_note: 'Surat dokter dari TU',
      },
      {
        student_id: 'student-2',
        student_number: 'S-002',
        full_name: 'Siswa Dua',
        record_status: 'present',
        record_note: null,
      },
    ])
    const wrapper = mount(SessionsView, { global: { plugins: [teacherPinia()] } })
    await flushPromises()
    await wrapper.get('button.button--text').trigger('click')
    await flushPromises()
    const rows = wrapper.findAll('[data-testid="roster-row"]')
    expect(rows).toHaveLength(2)
    expect(rows[0].text()).toContain('Surat dokter dari TU')
    expect(rows[1].text()).toContain('–')
  })

  it('filters the roster by search text and status chips', async () => {
    const wrapper = await openDetail()
    await wrapper.get('[data-testid="roster-search"]').setValue('dua')
    expect(wrapper.findAll('[data-testid="roster-row"]')).toHaveLength(1)
    expect(wrapper.text()).toContain('Siswa Dua')

    await wrapper.get('[data-testid="roster-search"]').setValue('')
    await wrapper.get('[data-testid="roster-filter-unmarked"]').trigger('click')
    const rows = wrapper.findAll('[data-testid="roster-row"]')
    expect(rows).toHaveLength(1)
    expect(rows[0].text()).toContain('Siswa Dua')

    await wrapper.get('[data-testid="roster-filter-present"]').trigger('click')
    expect(wrapper.findAll('[data-testid="roster-row"]')).toHaveLength(1)
    expect(wrapper.text()).toContain('Siswa Satu')
  })
})
