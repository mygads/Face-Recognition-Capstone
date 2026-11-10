import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useAuthStore } from '../stores/auth'
import MyClassesView from './MyClassesView.vue'

const api = vi.hoisted(() => ({
  listMyClasses: vi.fn(),
  getMyClass: vi.fn(),
  listTeacherAssignments: vi.fn(),
}))

vi.mock('../api/client', () => ({
  ApiError: class ApiError extends Error {},
  ...api,
}))

const kelas = {
  id: 'class-1',
  code: 'XI IPA 1',
  name: 'Kelas XI IPA 1',
  grade: 11,
  academic_year: '2026/2027',
  is_active: true,
}
const detail = {
  ...kelas,
  students: [
    { id: 's-1', student_number: '2401', full_name: 'Raka Pratama', is_active: true },
    { id: 's-2', student_number: '2402', full_name: 'Sinta Aulia', is_active: true },
  ],
}

function testRouter() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/app/my-classes', name: 'my-classes', component: { template: '<div />' } },
      {
        path: '/app/my-classes/:classId',
        name: 'my-class-detail',
        component: { template: '<div />' },
      },
    ],
  })
  return router
}

async function readyRouter(path: string) {
  const router = testRouter()
  router.push(path)
  await router.isReady()
  return router
}

function piniaTeacher() {
  const pinia = createPinia()
  useAuthStore(pinia).$patch({
    accessToken: 't',
    expiresAt: Date.now() + 60_000,
    account: {
      id: 'teacher-1',
      email: 'guru@sekolah.test',
      full_name: 'Bu Rani',
      roles: ['TEACHER'],
      must_change_password: false,
    },
  })
  return pinia
}

beforeEach(() => {
  vi.clearAllMocks()
  api.listMyClasses.mockResolvedValue({
    items: [kelas, { ...kelas, id: 'class-2', code: 'XI IPA 2' }],
    pagination: { total: 2 },
  })
  api.getMyClass.mockResolvedValue(detail)
  api.listTeacherAssignments.mockResolvedValue({
    items: [
      { class_id: 'class-1', starts_on: '2026-07-01', ends_on: '2027-06-30', is_substitute: false },
    ],
  })
})

describe('my classes view (Stitch B02-07/08)', () => {
  it('menampilkan kartu penugasan dengan jumlah siswa dan masa penugasan', async () => {
    const wrapper = mount(MyClassesView, {
      global: { plugins: [piniaTeacher(), await readyRouter('/app/my-classes')] },
    })
    await flushPromises()
    expect(wrapper.text()).toContain('Kelas Saya')
    expect(wrapper.text()).toContain('Buka Roster Siswa')
    expect(wrapper.text()).toContain('Aktif sampai 2027-06-30')
    expect(api.listMyClasses).toHaveBeenCalled()
    wrapper.unmount()
  })

  it('membuka roster baca dengan tabel siswa', async () => {
    const wrapper = mount(MyClassesView, {
      global: { plugins: [piniaTeacher(), await readyRouter('/app/my-classes/class-1')] },
    })
    await flushPromises()
    expect(api.getMyClass).toHaveBeenCalledWith('class-1')
    expect(wrapper.text()).toContain('Roster Siswa')
    expect(wrapper.text()).toContain('Raka Pratama')
    expect(wrapper.text()).toContain('Terdaftar Aktif')
    expect(wrapper.text()).toContain('Mode Baca')
    wrapper.unmount()
  })
})
