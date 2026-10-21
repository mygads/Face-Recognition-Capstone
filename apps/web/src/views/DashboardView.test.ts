import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useAuthStore } from '../stores/auth'
import DashboardView from './DashboardView.vue'

const api = vi.hoisted(() => ({
  listAttendanceSessions: vi.fn(),
  getSessionDashboardSnapshot: vi.fn(),
  listAtRiskStudents: vi.fn(),
  sessionDashboardWebSocketUrl: vi.fn((sessionId: string) => `ws://test/${sessionId}`),
}))

vi.mock('../api/client', () => ({
  ApiError: class ApiError extends Error {
    code?: string
    constructor(_status?: number, code?: string, message?: string) {
      super(message)
      if (code !== undefined) this.code = code
    }
  },
  ...api,
}))

const activeSession = {
  id: 'session-active',
  practicum_schedule_id: 'schedule-1',
  status: 'active',
  opened_automatically: true,
  opened_at: '2026-10-05T02:00:00Z',
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

const overrideSession = {
  ...activeSession,
  id: 'session-override',
  status: 'manual_override',
  opened_automatically: false,
}

function snapshotFor(sessionId: string, status: 'active' | 'manual_override') {
  return {
    session_id: sessionId,
    session_status: status,
    generated_at: '2026-10-05T02:30:00Z',
    summary: { total_roster: 2, present: 1, late: 0, not_present: 1 },
    devices: [],
    recent_activity: [],
  }
}

class StubWebSocket {
  static readonly CLOSING = 2
  readonly readyState = 1
  onopen: ((event: unknown) => void) | null = null
  onmessage: ((event: unknown) => void) | null = null
  onerror: ((event: unknown) => void) | null = null
  onclose: ((event: unknown) => void) | null = null
  send = vi.fn()
  close = vi.fn()
  constructor(public readonly url: string) {}
}

function testRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/login', name: 'login', component: { template: '<div />' } }],
  })
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

describe('dashboard view running sessions', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.stubGlobal('WebSocket', StubWebSocket)
    api.listAttendanceSessions.mockImplementation(async ({ status }: { status: string }) => ({
      items: status === 'active' ? [activeSession] : [overrideSession],
      pagination: { total: 1, limit: 100, offset: 0 },
    }))
    api.getSessionDashboardSnapshot.mockImplementation(async (sessionId: string) =>
      snapshotFor(sessionId, sessionId === 'session-override' ? 'manual_override' : 'active'),
    )
  })

  it('lists active and manual_override sessions in the picker', async () => {
    const wrapper = mount(DashboardView, {
      global: { plugins: [teacherPinia(), testRouter()] },
    })
    await flushPromises()

    const calls = api.listAttendanceSessions.mock.calls.map((args) => args[0]?.status)
    expect(calls).toContain('active')
    expect(calls).toContain('manual_override')
    const options = wrapper.findAll('select option')
    expect(options).toHaveLength(2)
    expect(options[1].text()).toContain('Override manual')
  })

  it('labels a manual_override snapshot as running instead of ended', async () => {
    api.listAttendanceSessions.mockResolvedValue({
      items: [overrideSession],
      pagination: { total: 1, limit: 100, offset: 0 },
    })
    const wrapper = mount(DashboardView, {
      global: { plugins: [teacherPinia(), testRouter()] },
    })
    await flushPromises()

    expect(wrapper.find('.dashboard-view__eyebrow').text()).toContain('Override manual')
    expect(wrapper.html()).not.toContain('Sesi berakhir')
  })
})

const atRiskPayload = {
  items: [
    {
      student_id: 'student-a1',
      student_number: 'S-A1',
      full_name: 'Siswa A1',
      class_name: 'Kelas X A',
      total_sessions: 5,
      absent_count: 3,
      late_count: 0,
      absence_pct: 60,
      last_absent_at: '2026-10-05T02:00:00Z',
      reasons: ['tingkat_absen'],
    },
    {
      student_id: 'student-a2',
      student_number: 'S-A2',
      full_name: 'Siswa A2',
      class_name: 'Kelas X A',
      total_sessions: 5,
      absent_count: 0,
      late_count: 3,
      absence_pct: 0,
      last_absent_at: null,
      reasons: ['sering_terlambat'],
    },
  ],
  pagination: { total: 2, limit: 25, offset: 0 },
  effective_window_days: 30,
  effective_absence_pct_threshold: 20,
  effective_late_count_threshold: 3,
  policy_revision: 0,
  generated_at: '2026-10-05T03:00:00Z',
}

function mountWithAtRisk(atRisk: unknown) {
  api.listAtRiskStudents.mockResolvedValue(atRisk)
  return mount(DashboardView, {
    global: { plugins: [teacherPinia(), testRouter()] },
  })
}

describe('dashboard at-risk watchlist', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.stubGlobal('WebSocket', StubWebSocket)
    api.listAttendanceSessions.mockImplementation(async ({ status }: { status: string }) => ({
      items: status === 'active' ? [activeSession] : [overrideSession],
      pagination: { total: 1, limit: 100, offset: 0 },
    }))
    api.getSessionDashboardSnapshot.mockImplementation(async (sessionId: string) =>
      snapshotFor(sessionId, sessionId === 'session-override' ? 'manual_override' : 'active'),
    )
  })

  it('loads the watchlist once when the dashboard mounts', async () => {
    mountWithAtRisk(atRiskPayload)
    await flushPromises()

    expect(api.listAtRiskStudents).toHaveBeenCalledTimes(1)
    expect(api.listAtRiskStudents).toHaveBeenCalledWith({
      limit: 25,
      offset: 0,
    })
  })

  it('renders the watchlist with names, classes, and Indonesian reasons', async () => {
    const wrapper = mountWithAtRisk(atRiskPayload)
    await flushPromises()

    const panel = wrapper.find('[data-testid="at-risk-panel"]')
    expect(panel.exists()).toBe(true)
    expect(panel.text()).toContain('Siswa perlu perhatian')
    expect(wrapper.find('[data-testid="at-risk-thresholds"]').text()).toContain(
      'Jendela 30 hari · ambang absen 20% · ambang terlambat 3x',
    )
    const rows = wrapper.findAll('[data-testid="at-risk-row"]')
    expect(rows).toHaveLength(2)
    expect(rows[0].text()).toContain('Siswa A1')
    expect(rows[0].text()).toContain('Kelas X A')
    expect(rows[0].text()).toContain('Tingkat absen tinggi')
    expect(rows[1].text()).toContain('Sering terlambat')
    expect(panel.text()).toContain('bukan sanksi')
  })

  it('renders no AI scores or embeddings in the watchlist', async () => {
    const wrapper = mountWithAtRisk(atRiskPayload)
    await flushPromises()

    const html = wrapper.find('[data-testid="at-risk-panel"]').html().toLowerCase()
    expect(html).not.toContain('similarity')
    expect(html).not.toContain('embedding')
    expect(html).not.toContain('confidence')
    expect(html).not.toContain('skor')
  })

  it('renders an empty state when nobody is flagged', async () => {
    const wrapper = mountWithAtRisk({
      ...atRiskPayload,
      items: [],
      pagination: { total: 0, limit: 25, offset: 0 },
    })
    await flushPromises()

    expect(wrapper.find('[data-testid="at-risk-panel"]').text()).toContain(
      'Belum ada siswa yang perlu perhatian.',
    )
    expect(wrapper.findAll('[data-testid="at-risk-row"]')).toHaveLength(0)
  })

  it('renders a validation error without breaking the live session snapshot', async () => {
    const { ApiError } = await import('../api/client')
    api.listAtRiskStudents.mockRejectedValue(
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      new (ApiError as any)(422, 'validation_error', 'Validasi jendela gagal.'),
    )
    const wrapper = mount(DashboardView, {
      global: { plugins: [teacherPinia(), testRouter()] },
    })
    await flushPromises()

    const panel = wrapper.find('[data-testid="at-risk-panel"]')
    expect(panel.find('[role="alert"]').text()).toContain('Validasi jendela gagal.')
    expect(wrapper.find('[data-testid="realtime-status"]').exists()).toBe(true)
  })

  it('keeps the watchlist visible when no session is running', async () => {
    api.listAttendanceSessions.mockResolvedValue({
      items: [],
      pagination: { total: 0, limit: 100, offset: 0 },
    })
    const wrapper = mountWithAtRisk(atRiskPayload)
    await flushPromises()

    expect(wrapper.find('[data-testid="no-active-session"]').exists()).toBe(true)
    const panel = wrapper.find('[data-testid="at-risk-panel"]')
    expect(panel.exists()).toBe(true)
    expect(panel.text()).toContain('Siswa perlu perhatian')
    expect(wrapper.findAll('[data-testid="at-risk-row"]')).toHaveLength(2)
    // Jendela efektif datang dari respons backend (kebijakan tersimpan),
    // bukan dari nilai yang di-hardcode di frontend.
    expect(wrapper.find('[data-testid="at-risk-thresholds"]').text()).toContain(
      'Jendela 30 hari · ambang absen 20% · ambang terlambat 3x',
    )
  })
})
