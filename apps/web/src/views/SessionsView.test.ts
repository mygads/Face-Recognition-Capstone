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
})
