import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useAuthStore } from '../stores/auth'
import DashboardView from './DashboardView.vue'

const api = vi.hoisted(() => ({
  listAttendanceSessions: vi.fn(),
  getSessionDashboardSnapshot: vi.fn(),
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
