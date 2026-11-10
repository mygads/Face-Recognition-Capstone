import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useAuthStore } from '../stores/auth'
import DashboardView from './DashboardView.vue'

const api = vi.hoisted(() => ({
  listLaboratories: vi.fn(),
  listDevices: vi.fn(),
  listAttendanceSessions: vi.fn(),
  listAttendanceCorrections: vi.fn(),
  listAtRiskStudents: vi.fn(),
  listMyClasses: vi.fn(),
  listLaborantAssignments: vi.fn(),
  getSessionRoster: vi.fn(),
}))

vi.mock('../api/client', () => ({
  ApiError: class ApiError extends Error {},
  ...api,
}))

const labs = [{ id: 'lab-1', code: 'KIM1', name: 'Lab Kimia 1', is_active: true }]
const devices = [
  {
    device_id: 'dev-1',
    name: 'Pintu Masuk 01',
    laboratory_name: 'Lab Kimia 1',
    health_status: 'online',
    last_seen_at: '2026-11-06T06:20:00Z',
  },
]
const sessions = [
  {
    id: 'sess-1',
    status: 'active',
    opened_automatically: true,
    subject: 'Praktikum Kimia: Uji Larutan',
    class_name: 'XI IPA 1',
    laboratory_name: 'Lab Kimia 1',
    teacher_name: 'Bu Rani',
    student_count: 28,
  },
]
const corrections = [
  {
    id: 'corr-1',
    attendance_record_id: null,
    session_id: 'sess-1',
    student_id: 'stu-1',
    previous_status: 'absent',
    corrected_status: 'present',
    decision_status: 'pending',
    reason: 'Kamera tertutup saat masuk',
    created_at: '2026-11-06T06:00:00Z',
    decided_at: null,
  },
]
const atRisk = {
  items: [
    {
      student_id: 'stu-1',
      student_number: '2403',
      full_name: 'Tio Mahendra',
      class_name: 'XI IPA 1',
      total_sessions: 10,
      absent_count: 3,
      late_count: 1,
      absence_pct: 30,
      last_absent_at: null,
      reasons: ['tingkat_absen'],
    },
  ],
}
const roster = [{ student_id: 'stu-1', student_number: '2403', full_name: 'Tio Mahendra' }]

function testRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/app/dashboard', name: 'dashboard', component: { template: '<div />' } },
      { path: '/app/sessions/:id', name: 'session-detail', component: { template: '<div />' } },
      { path: '/app/corrections', name: 'corrections', component: { template: '<div />' } },
      { path: '/app/ews', name: 'ews', component: { template: '<div />' } },
      { path: '/app/accounts', name: 'accounts', component: { template: '<div />' } },
      { path: '/app/my-classes', name: 'my-classes', component: { template: '<div />' } },
      { path: '/app/audit', name: 'audit', component: { template: '<div />' } },
      { path: '/app/camera-preview', name: 'camera-preview', component: { template: '<div />' } },
      { path: '/app/enrollment', name: 'enrollment', component: { template: '<div />' } },
      { path: '/app/sessions', name: 'sessions', component: { template: '<div />' } },
      { path: '/app/reports', name: 'reports', component: { template: '<div />' } },
    ],
  })
}

function piniaWith(account: object) {
  const pinia = createPinia()
  useAuthStore(pinia).$patch({ accessToken: 't', expiresAt: Date.now() + 60_000, account } as never)
  return pinia
}

const adminAccount = {
  id: 'admin-1',
  email: 'a@t.test',
  full_name: 'Nadia Admin',
  roles: ['ADMIN'],
  must_change_password: false,
  permissions: [],
}
const teacherAccount = {
  id: 'teacher-1',
  email: 't@t.test',
  full_name: 'Bu Rani',
  roles: ['TEACHER'],
  must_change_password: false,
  permissions: ['roster_read', 'session_view', 'reports_read', 'ews_read'],
}
const laboranAccount = (extra: string[] = []) => ({
  id: 'lab-1',
  email: 'l@t.test',
  full_name: 'Fajar Laboran',
  roles: ['LABORANT'],
  must_change_password: false,
  permissions: ['roster_read', 'laboratory_read', 'device_operate', 'enrollment_manage', ...extra],
})

beforeEach(() => {
  vi.clearAllMocks()
  api.listLaboratories.mockResolvedValue({ items: labs })
  api.listDevices.mockResolvedValue({ items: devices, pagination: { total: 1 } })
  api.listAttendanceSessions.mockResolvedValue({ items: sessions, pagination: { total: 1 } })
  api.listAttendanceCorrections.mockResolvedValue({ items: corrections, pagination: { total: 1 } })
  api.listAtRiskStudents.mockResolvedValue(atRisk)
  api.listMyClasses.mockResolvedValue({
    items: [{ id: 'c1', name: 'XI IPA 1', academic_year: '2026/2027' }],
  })
  api.listLaborantAssignments.mockResolvedValue({
    items: [{ laboratory_id: 'lab-1', code: 'KIM1', name: 'Lab Kimia 1' }],
  })
  api.getSessionRoster.mockResolvedValue(roster)
})

describe('dashboard admin ala Stitch B01-03', () => {
  it('menampilkan KPI, kartu lab, dan antrean koreksi', async () => {
    const wrapper = mount(DashboardView, {
      global: { plugins: [piniaWith(adminAccount), testRouter()] },
    })
    await flushPromises()
    const text = wrapper.text()
    expect(text).toContain('Dashboard Admin')
    expect(text).toContain('Sesi Praktikum Aktif')
    expect(text).toContain('Kesiapan Perangkat Kamera')
    expect(text).toContain('Antrean Koreksi Kehadiran')
    expect(text).toContain('Siswa Terpantau EWS')
    expect(text).toContain('Lab Kimia 1')
    expect(text).toContain('Tinjau Koreksi')
    expect(text).toContain('Tio Mahendra')
  })
})

describe('dashboard guru ala Stitch B01-04', () => {
  it('menampilkan sapaan, sesi, kelas, dan EWS tanpa istilah AI', async () => {
    const wrapper = mount(DashboardView, {
      global: { plugins: [piniaWith(teacherAccount), testRouter()] },
    })
    await flushPromises()
    const text = wrapper.text()
    expect(text).toContain('Selamat datang, Bu')
    expect(text).toContain('Pantau Sesi')
    expect(text).toContain('XI IPA 1')
    const html = wrapper.html().toLowerCase()
    expect(html).not.toContain('embedding')
    expect(html).not.toContain('similarity')
    expect(wrapper.findAll('[data-testid="at-risk-row"]')).toHaveLength(1)
  })
})

describe('dashboard laboran ala Stitch B01-06/B01-07', () => {
  it('menampilkan banner bila tanpa penugasan lab', async () => {
    api.listLaborantAssignments.mockResolvedValue({ items: [] })
    const wrapper = mount(DashboardView, {
      global: { plugins: [piniaWith(laboranAccount()), testRouter()] },
    })
    await flushPromises()
    expect(wrapper.text()).toContain('Belum ada penugasan laboratorium')
  })

  it('menampilkan perangkat dan menu delegasi sesuai izin', async () => {
    const wrapper = mount(DashboardView, {
      global: {
        plugins: [piniaWith(laboranAccount(['session_view', 'reports_read'])), testRouter()],
      },
    })
    await flushPromises()
    const text = wrapper.text()
    expect(text).toContain('Dashboard Laboran')
    expect(text).toContain('Pintu Masuk 01')
    expect(text).toContain('Preview kamera')
    expect(text).toContain('Pantau sesi')
    expect(text).toContain('Lihat laporan')
  })
})
