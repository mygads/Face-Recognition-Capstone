import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useAuthStore } from '../stores/auth'
import ScheduleView from './ScheduleView.vue'

const api = vi.hoisted(() => ({
  listSchedules: vi.fn(),
  listClasses: vi.fn(),
  listLaboratories: vi.fn(),
  listScheduleTeachers: vi.fn(),
  createSchedule: vi.fn(),
  updateSchedule: vi.fn(),
}))

vi.mock('../api/client', () => ({
  ApiError: class ApiError extends Error {
    details?: { field: string; message: string }[]
    constructor(message: string) {
      super(message)
      this.details = []
    }
  },
  ...api,
}))

const schedule = {
  id: 'sch-1',
  subject: 'Praktikum Web',
  class_id: 'class-1',
  class_name: 'Kelas XII RPL 1',
  laboratory_id: 'lab-1',
  laboratory_name: 'Lab Komputer 1',
  teacher_user_id: 'teacher-1',
  teacher_name: 'Dewi Lestari',
  weekday: 4,
  start_time: '17:00:00',
  end_time: '20:00:00',
  timezone_name: 'Asia/Jakarta',
  effective_from: '2026-07-01',
  effective_through: null,
  is_active: true,
}

function router() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/app/schedules', name: 'schedules', component: { template: '<div />' } }],
  })
}

function piniaTeacher() {
  const pinia = createPinia()
  useAuthStore(pinia).$patch({
    accessToken: 't',
    expiresAt: Date.now() + 60_000,
    account: {
      id: 'teacher-1',
      email: 'guru@sekolah.test',
      full_name: 'Dewi Lestari',
      roles: ['TEACHER'],
      must_change_password: false,
    },
  })
  return pinia
}

beforeEach(() => {
  vi.clearAllMocks()
  api.listSchedules.mockResolvedValue({
    items: [schedule],
    pagination: { total: 1, limit: 10, offset: 0 },
  })
  api.listClasses.mockResolvedValue({
    items: [
      { id: 'class-1', code: 'XII-RPL-1', name: 'Kelas XII RPL 1', academic_year: '2026/2027' },
    ],
    pagination: { total: 1 },
  })
  api.listLaboratories.mockResolvedValue({
    items: [
      { id: 'lab-1', code: 'LAB-RPL1', name: 'Lab Komputer 1' },
      { id: 'lab-2', code: 'LAB-FIS', name: 'Lab Fisika' },
    ],
    pagination: { total: 2 },
  })
  api.listScheduleTeachers.mockResolvedValue([
    { id: 'teacher-1', full_name: 'Dewi Lestari', opening_mode: 'automatic' },
  ])
  api.createSchedule.mockResolvedValue(schedule)
})

describe('schedule view (Stitch B02-09/10)', () => {
  it('menampilkan kartu jadwal guru dengan judul Jadwal Saya', async () => {
    const r = router()
    r.push('/app/schedules')
    await r.isReady()
    const wrapper = mount(ScheduleView, { global: { plugins: [piniaTeacher(), r] } })
    await flushPromises()
    expect(wrapper.text()).toContain('Jadwal Saya')
    expect(wrapper.text()).toContain('Praktikum Web')
    expect(wrapper.text()).toContain('Lab Komputer 1')
    wrapper.unmount()
  })

  it('menampilkan saran lab alternatif saat jadwal bertabrakan', async () => {
    const { ApiError } = await import('../api/client')
    api.createSchedule.mockRejectedValueOnce(
      new (ApiError as unknown as new (message: string) => Error)(
        'Jadwal bertabrakan untuk kelas, laboratorium, atau guru pada waktu yang sama.',
      ),
    )
    const r = router()
    r.push('/app/schedules')
    await r.isReady()
    const wrapper = mount(ScheduleView, { global: { plugins: [piniaTeacher(), r] } })
    await flushPromises()
    await wrapper
      .findAll('button')
      .find((b) => b.text().includes('Tambah Jadwal'))!
      .trigger('click')
    await flushPromises()
    const dialog = wrapper.find('[role="dialog"]')
    const selects = dialog.findAll('select')
    await selects[0].setValue('class-1')
    await selects[2].setValue('lab-1')
    await wrapper.find('input[name="subject"]').setValue('Uji Konflik')
    await wrapper
      .findAll('button')
      .find((b) => b.text() === 'Simpan jadwal')!
      .trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('Konflik Jadwal Laboratorium Terdeteksi')
    const alt = wrapper.findAll('button').find((b) => b.text().includes('Pindah ke Lab Fisika'))
    expect(alt?.text()).toContain('Lab Fisika')
    await alt!.trigger('click')
    expect((wrapper.vm as unknown as { form: { laboratory_id: string } }).form.laboratory_id).toBe(
      'lab-2',
    )
    wrapper.unmount()
  })
})
