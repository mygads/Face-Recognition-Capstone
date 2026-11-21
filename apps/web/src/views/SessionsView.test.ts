import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../api/client'
import { useAuthStore } from '../stores/auth'
import SessionsView from './SessionsView.vue'

const api = vi.hoisted(() => ({
  listOpenableSchedules: vi.fn(),
  listAttendanceSessions: vi.fn(),
  getSessionOpeningPolicy: vi.fn(async () => ({ default_grace_period_minutes: 20 })),
  getOpeningPreference: vi.fn(),
  saveOpeningPreference: vi.fn(),
  openAttendanceSession: vi.fn(),
  closeAttendanceSession: vi.fn(),
  getAttendanceSessionStatus: vi.fn(),
  getSessionDashboardSnapshot: vi.fn(),
  sessionDashboardWebSocketUrl: vi.fn(),
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

const dashboardSnapshot = {
  session_id: 'session-1',
  session_status: 'manual_override' as const,
  generated_at: '2026-10-05T02:10:00Z',
  summary: {
    total_roster: 2,
    present: 0,
    late: 0,
    excused: 0,
    absent: 0,
    not_present: 2,
  },
  devices: [],
  recent_activity: [],
}

function laboranPinia() {
  const pinia = createPinia()
  useAuthStore(pinia).$patch({
    accessToken: 'unit-test-token',
    expiresAt: Date.now() + 60_000,
    account: {
      id: 'laboran-1',
      email: 'laboran@example.test',
      full_name: 'Test Laboran',
      roles: ['LABORANT'],
      must_change_password: false,
      permissions: [],
    },
  })
  return pinia
}

function teacherPinia(extraPermissions: string[] = []) {
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
      permissions: ['schedule_read', 'session_view', 'attendance_manual', ...extraPermissions],
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
    api.getSessionDashboardSnapshot.mockResolvedValue(dashboardSnapshot)
    api.sessionDashboardWebSocketUrl.mockImplementation(
      (sessionId: string) => `ws://localhost/api/${sessionId}`,
    )
    api.getOpeningPreference.mockResolvedValue({
      opening_mode: 'manual',
      updated_at: null,
    })
  })

  it('memakai toleransi dari Kebijakan Presensi tanpa input duplikat di halaman sesi', async () => {
    const wrapper = mount(SessionsView, { global: { plugins: [teacherPinia()] } })
    await flushPromises()
    expect(wrapper.find('[data-testid="open-grace-input"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('Toleransi mengikuti Kebijakan Presensi')
    api.openAttendanceSession.mockResolvedValueOnce({
      ...overrideSession,
      status: 'active',
      grace_period_minutes: 20,
    })
    await wrapper.get('[data-testid="open-session-schedule-1"]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-testid="confirm-open-session"]').trigger('click')
    await flushPromises()
    expect(api.openAttendanceSession).toHaveBeenCalledWith('schedule-1', 20)
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

  it('links the teacher opening preference to the profile page', async () => {
    const wrapper = mount(SessionsView, { global: { plugins: [teacherPinia()] } })
    await flushPromises()

    expect(wrapper.find('select[data-testid="opening-mode"]').exists()).toBe(false)
    const panel = wrapper.get('[data-testid="teacher-opening-preference"]')
    expect(panel.text()).toContain('Profil')
    expect(api.getOpeningPreference).not.toHaveBeenCalled()
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
    const wrapper = mount(SessionsView, {
      global: { plugins: [teacherPinia(['attendance_correct_closed'])] },
    })
    await flushPromises()

    await wrapper.get('[data-testid^="show-status-"]').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('Siswa Satu')

    await wrapper.get('[data-testid="edit-attendance-student-1"]').trigger('click')
    expect(wrapper.get('[data-testid="attendance-edit-drawer"]').text()).toContain(
      'Tandai kehadiran manual',
    )
    await wrapper.get('[data-testid="submit-attendance-edit"]').trigger('click')
    await flushPromises()
    expect(api.markManualAttendance).toHaveBeenCalledWith('session-1', {
      student_id: 'student-1',
      status: 'present',
    })
    expect(wrapper.text()).toContain('ditandai manual')

    const duplicate = new ApiError(409, 'attendance_already_recorded', 'duplikat')
    api.markManualAttendance.mockRejectedValueOnce(duplicate)
    await wrapper.get('[data-testid="edit-attendance-student-1"]').trigger('click')
    await wrapper.get('[data-testid="submit-attendance-edit"]').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('sudah tercatat')
  })

  it('meminta alasan wajib saat sesi sudah ditutup (koreksi pascasesi)', async () => {
    const rosterEntry = {
      student_id: 'student-9',
      student_number: 'S-009',
      full_name: 'Siswa Sela',
      record_status: null,
    }
    api.getAttendanceSessionStatus.mockResolvedValue({ ...overrideSession, status: 'closed' })
    api.getSessionRoster.mockResolvedValue([rosterEntry])
    api.markManualAttendance.mockResolvedValue({ record: {} })
    const wrapper = mount(SessionsView, {
      global: { plugins: [teacherPinia(['attendance_correct_closed'])] },
    })
    await flushPromises()

    await wrapper.get('[data-testid^="show-status-"]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-testid="edit-attendance-student-9"]').trigger('click')
    expect(wrapper.get('[data-testid="attendance-edit-drawer"]').text()).toContain(
      'koreksi pascasesi',
    )
    await wrapper.get('[data-testid="submit-attendance-edit"]').trigger('click')
    await flushPromises()
    expect(api.markManualAttendance).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('alasan wajib diisi')

    await wrapper.get('[aria-label="Alasan atau keterangan"]').setValue('ralat TU')
    await wrapper.get('[data-testid="submit-attendance-edit"]').trigger('click')
    await flushPromises()
    expect(api.markManualAttendance).toHaveBeenCalledWith('session-1', {
      student_id: 'student-9',
      status: 'absent',
      note: 'ralat TU',
    })
  })

  it('membuka koreksi catatan roster dari tombol Edit di drawer kanan', async () => {
    const rosterEntry = {
      student_id: 'student-8',
      student_number: 'S-008',
      full_name: 'Siswa Delapan',
      record_status: 'late' as const,
    }
    api.getAttendanceSessionStatus.mockResolvedValue(overrideSession)
    api.getSessionRoster.mockResolvedValue([rosterEntry])
    api.markManualAttendance.mockResolvedValue({ record: {} })
    const wrapper = mount(SessionsView, {
      global: { plugins: [teacherPinia()] },
    })
    await flushPromises()
    await wrapper.get('[data-testid^="show-status-"]').trigger('click')
    await flushPromises()

    await wrapper.get('[data-testid="edit-attendance-student-8"]').trigger('click')
    const drawer = wrapper.get('[data-testid="attendance-edit-drawer"]')
    expect(drawer.text()).toContain('Status saat ini: Terlambat')
    expect(
      (wrapper.get('[aria-label="Status kehadiran"]').element as HTMLSelectElement).value,
    ).toBe('late')

    await wrapper.get('[data-testid="submit-attendance-edit"]').trigger('click')
    await flushPromises()
    expect(drawer.text()).toContain('Alasan perubahan wajib diisi')
    await wrapper.get('[aria-label="Alasan atau keterangan"]').setValue('ralat input guru')
    await wrapper.get('[data-testid="submit-attendance-edit"]').trigger('click')
    await flushPromises()
    expect(api.markManualAttendance).toHaveBeenCalledWith('session-1', {
      student_id: 'student-8',
      status: 'late',
      note: 'ralat input guru',
    })
  })

  it('menyembunyikan form koreksi sesi tertutup tanpa izin koreksi', async () => {
    const rosterEntry = {
      student_id: 'student-9',
      student_number: 'S-009',
      full_name: 'Siswa Sela',
      record_status: null,
    }
    api.getAttendanceSessionStatus.mockResolvedValue({ ...overrideSession, status: 'closed' })
    api.getSessionRoster.mockResolvedValue([rosterEntry])
    const wrapper = mount(SessionsView, { global: { plugins: [teacherPinia()] } })
    await flushPromises()

    await wrapper.get('[data-testid^="show-status-"]').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('Koreksi Sesi Tertutup')
    expect(wrapper.find('[data-testid="edit-attendance-student-9"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="direct-update-panel"]').exists()).toBe(false)
  })

  it('menampilkan pemberitahuan sesi dibatalkan tanpa form koreksi', async () => {
    const rosterEntry = {
      student_id: 'student-9',
      student_number: 'S-009',
      full_name: 'Siswa Sela',
      record_status: null,
    }
    api.getAttendanceSessionStatus.mockResolvedValue({
      ...overrideSession,
      status: 'cancelled',
    })
    api.getSessionRoster.mockResolvedValue([rosterEntry])
    const wrapper = mount(SessionsView, {
      global: { plugins: [teacherPinia(['attendance_correct_closed'])] },
    })
    await flushPromises()

    await wrapper.get('[data-testid^="show-status-"]').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('dibatalkan')
    expect(wrapper.find('[data-testid="edit-attendance-student-9"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="direct-update-panel"]').exists()).toBe(false)
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

    // Konfirmasi B03-02 menampilkan ringkasan sebelum membuka sesi.
    const confirmTitle = wrapper.get('[data-testid="confirm-open-session"]')
    expect(confirmTitle.text()).toContain('Buka Sesi')
    expect(wrapper.text()).toContain('Roster dikunci saat sesi')
    await confirmTitle.trigger('click')
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
    await wrapper.get('[data-testid^="show-status-"]').trigger('click')
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

  it('shows unrecorded roster members as absent after a session closes', async () => {
    const closedSession = {
      ...overrideSession,
      status: 'closed',
      closed_at: '2026-10-05T04:00:00Z',
    }
    api.listAttendanceSessions.mockResolvedValue({
      items: [closedSession],
      pagination: { total: 1, limit: 50, offset: 0 },
    })
    api.getAttendanceSessionStatus.mockResolvedValue(closedSession)
    const wrapper = mount(SessionsView, {
      global: { plugins: [teacherPinia(['attendance_correct_closed'])] },
    })
    await flushPromises()
    await wrapper.get('[data-testid^="show-status-"]').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('Absen (1)')
    expect(wrapper.text()).toContain('Belum tercatat (0)')
    expect(wrapper.text()).toContain('Absen')
  })

  it('shows a monitor-only banner for laboran without operate permission', async () => {
    api.getAttendanceSessionStatus.mockResolvedValue(overrideSession)
    api.getSessionRoster.mockResolvedValue([])
    const wrapper = mount(SessionsView, { global: { plugins: [laboranPinia()] } })
    await flushPromises()
    await wrapper.get('[data-testid^="show-status-"]').trigger('click')
    await flushPromises()
    const banner = wrapper.get('[data-testid="session-monitor-banner"]')
    expect(banner.text()).toContain('Mode Pantau Sesi Aktif')
    expect(banner.text()).toContain('Test Teacher')
    expect(banner.text()).toContain('Delegasi Laboran')
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
    await wrapper.get('[data-testid^="show-status-"]').trigger('click')
    await flushPromises()
    const rows = wrapper.findAll('[data-testid="roster-row"]')
    expect(rows).toHaveLength(2)
    expect(rows[0].text()).toContain('Surat dokter dari TU')
    expect(rows[1].text()).toContain('-')
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

describe('session detail live updates', () => {
  class FakeWebSocket {
    static instances: FakeWebSocket[] = []
    readonly send = vi.fn()
    onopen: ((event: Event) => void) | null = null
    onmessage: ((event: MessageEvent) => void) | null = null
    onclose: ((event: CloseEvent) => void) | null = null
    onerror: ((event: Event) => void) | null = null

    constructor(readonly url: string) {
      FakeWebSocket.instances.push(this)
    }

    open(): void {
      this.onopen?.(new Event('open'))
    }

    message(payload: unknown): void {
      this.onmessage?.({ data: JSON.stringify(payload) } as MessageEvent)
    }

    close(): void {
      this.onclose?.(new CloseEvent('close'))
    }
  }

  it('mengirim token sesi dan memperbarui roster saat WebSocket menerima snapshot baru', async () => {
    vi.stubGlobal('WebSocket', FakeWebSocket)
    FakeWebSocket.instances = []
    api.getAttendanceSessionStatus.mockResolvedValue(overrideSession)
    const unmarkedRoster = [
      {
        student_id: 'student-1',
        student_number: 'S-001',
        full_name: 'Siswa Satu',
        record_status: null,
      },
    ]
    const presentRoster = [
      {
        ...unmarkedRoster[0],
        record_status: 'present' as const,
      },
    ]
    api.getSessionRoster
      .mockResolvedValueOnce(unmarkedRoster)
      .mockResolvedValueOnce(unmarkedRoster)
      .mockResolvedValueOnce(presentRoster)
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/app/sessions/:sessionId', component: SessionsView }],
    })
    await router.push('/app/sessions/session-1')
    await router.isReady()
    const wrapper = mount(SessionsView, {
      global: { plugins: [teacherPinia(), router] },
    })
    try {
      await flushPromises()
      const socket = FakeWebSocket.instances[0]
      expect(socket.url).toBe('ws://localhost/api/session-1')
      socket.open()
      expect(socket.send).toHaveBeenCalledWith(
        JSON.stringify({ type: 'authenticate', access_token: 'unit-test-token' }),
      )
      await flushPromises()
      socket.message({
        type: 'snapshot',
        data: {
          ...dashboardSnapshot,
          summary: { ...dashboardSnapshot.summary, present: 1, not_present: 1 },
          recent_activity: [
            {
              id: 'event-1',
              occurred_at: '2026-10-05T02:11:00Z',
              kind: 'recognition',
              student_name: 'Siswa Satu',
              recognition_outcome: 'matched',
              attendance_status: 'present',
              decision_reason: null,
            },
          ],
        },
      })
      await flushPromises()
      expect(wrapper.get('[data-testid="session-live-status"]').text()).toContain(
        'Pembaruan langsung aktif',
      )
      expect(wrapper.get('[data-testid="roster-row"]').text()).toContain('Hadir')
    } finally {
      wrapper.unmount()
      vi.unstubAllGlobals()
    }
  })
})

describe('session close confirmation', () => {
  it('asks for confirmation showing unmarked count before closing', async () => {
    const { mount: mountView } = await import('@vue/test-utils')
    const { createPinia: makePinia } = await import('pinia')
    const pinia = makePinia()
    const { useAuthStore: useAuth } = await import('../stores/auth')
    const { default: View } = await import('./SessionsView.vue')
    useAuth(pinia).$patch({
      accessToken: 'unit-test-token',
      expiresAt: Date.now() + 60_000,
      account: {
        id: 'teacher-1',
        email: 'teacher@example.test',
        full_name: 'Test Teacher',
        roles: ['TEACHER'],
        must_change_password: false,
        permissions: ['schedule_read', 'session_view', 'attendance_manual'],
      },
    })
    api.listOpenableSchedules.mockResolvedValue([])
    api.listAttendanceSessions.mockResolvedValue({
      items: [overrideSession],
      pagination: { total: 1, limit: 50, offset: 0 },
    })
    api.getSessionRoster.mockResolvedValue([
      { student_id: 's1', student_number: 'S-1', full_name: 'Satu', record_status: null },
      {
        student_id: 's2',
        student_number: 'S-2',
        full_name: 'Dua',
        record_status: 'present',
      },
    ])
    api.getAttendanceSessionStatus.mockResolvedValue(overrideSession)
    api.closeAttendanceSession.mockResolvedValue({ ...overrideSession, status: 'closed' })
    const wrapper = mountView(View, { global: { plugins: [pinia] } })
    await flushPromises()

    const closeButton = wrapper.get('[data-testid="close-session-session-1"]')
    expect(closeButton.text()).toBe('Tutup sesi')
    await closeButton.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('belum tercatat akan menjadi absen')
    expect(wrapper.text()).toContain('Terdapat 1 siswa belum tercatat')
    const projection = wrapper
      .get('[role="dialog"]')
      .findAll('.st-kpi')
      .map((item) => item.text().replace(/\s+/g, ' ').trim())
    expect(projection).toEqual(['1 Siswa', '0 Siswa', '1 Siswa', '0 Siswa'])
    expect(
      wrapper.get('[data-testid="confirm-close-session"]').attributes('disabled'),
    ).toBeUndefined()
    expect(api.closeAttendanceSession).not.toHaveBeenCalled()

    await wrapper.get('[data-testid="confirm-close-session"]').trigger('click')
    await flushPromises()
    expect(api.closeAttendanceSession).toHaveBeenCalledWith('session-1')
  })

  it('blocks closing until the roster loads and offers a retry', async () => {
    const { mount: mountView } = await import('@vue/test-utils')
    const { createPinia: makePinia } = await import('pinia')
    const pinia = makePinia()
    const { useAuthStore: useAuth } = await import('../stores/auth')
    const { default: View } = await import('./SessionsView.vue')
    useAuth(pinia).$patch({
      accessToken: 'unit-test-token',
      expiresAt: Date.now() + 60_000,
      account: {
        id: 'teacher-1',
        email: 'teacher@example.test',
        full_name: 'Test Teacher',
        roles: ['TEACHER'],
        must_change_password: false,
        permissions: ['schedule_read', 'session_view', 'attendance_manual'],
      },
    })
    api.listOpenableSchedules.mockResolvedValue([])
    api.listAttendanceSessions.mockResolvedValue({
      items: [overrideSession],
      pagination: { total: 1, limit: 50, offset: 0 },
    })
    api.getSessionRoster.mockRejectedValueOnce(new Error('Roster unavailable'))
    api.closeAttendanceSession.mockResolvedValue({ ...overrideSession, status: 'closed' })
    const wrapper = mountView(View, { global: { plugins: [pinia] } })
    await flushPromises()

    await wrapper.get('[data-testid="close-session-session-1"]').trigger('click')
    await flushPromises()
    expect(
      wrapper.get('[data-testid="confirm-close-session"]').attributes('disabled'),
    ).toBeDefined()
    expect(wrapper.find('[data-testid="retry-close-roster"]').exists()).toBe(true)
    expect(api.closeAttendanceSession).not.toHaveBeenCalled()

    api.getSessionRoster.mockResolvedValueOnce([
      { student_id: 's1', student_number: 'S-1', full_name: 'Satu', record_status: 'present' },
    ])
    await wrapper.get('[data-testid="retry-close-roster"]').trigger('click')
    await flushPromises()
    expect(
      wrapper.get('[data-testid="confirm-close-session"]').attributes('disabled'),
    ).toBeUndefined()
    expect(wrapper.text()).toContain('Proyeksi Rekapitulasi Akhir · Total: 1 Siswa')
    expect(
      wrapper
        .get('[role="dialog"]')
        .findAll('.st-kpi')
        .map((item) => item.text().replace(/\s+/g, ' ').trim()),
    ).toEqual(['1 Siswa', '0 Siswa', '0 Siswa', '0 Siswa'])
  })
})
