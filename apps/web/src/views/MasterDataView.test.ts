import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useAuthStore } from '../stores/auth'
import MasterDataView from './MasterDataView.vue'

const api = vi.hoisted(() => ({
  listStudents: vi.fn(),
  listClasses: vi.fn(),
  listLaboratories: vi.fn(),
  listDevices: vi.fn(),
  listClassTeachers: vi.fn(),
  listLabLaborants: vi.fn(),
  listClassLaboratories: vi.fn(),
  createStudent: vi.fn(),
  updateStudent: vi.fn(),
  createClass: vi.fn(),
  updateClass: vi.fn(),
  createLaboratory: vi.fn(),
  updateLaboratory: vi.fn(),
  getStudent: vi.fn(),
  getClass: vi.fn(),
  getLaboratory: vi.fn(),
  enrollStudent: vi.fn(),
  removeStudentFromClass: vi.fn(),
  previewStudentImport: vi.fn(),
  commitStudentImport: vi.fn(),
}))

vi.mock('../api/client', () => ({
  ApiError: class ApiError extends Error {},
  ...api,
}))

const student = {
  id: 'student-1',
  student_number: 'S-001',
  full_name: 'Synthetic Student',
  is_active: true,
  classes: [
    { id: 'class-1', code: 'XI IPA 1', name: 'Kelas XI IPA 1', academic_year: '2026/2027' },
  ],
}

const kelas = {
  id: 'class-1',
  code: 'XI IPA 1',
  name: 'Kelas XI IPA 1',
  grade: 11,
  academic_year: '2026/2027',
  homeroom_teacher_id: null,
  is_active: true,
}

const lab = {
  id: 'lab-1',
  code: 'LAB-KIM-01',
  name: 'Lab Kimia 1',
  location: 'Gedung Laboratorium Lt. 1',
  is_active: true,
}

function testRouter(initialPath = '/app/master-data/students') {
  return createRouter({
    history: createMemoryHistory(initialPath),
    routes: [
      {
        path: '/app/master-data/students',
        name: 'master-data-students',
        component: { template: '<div />' },
      },
      {
        path: '/app/master-data/classes',
        name: 'master-data-classes',
        component: { template: '<div />' },
      },
      {
        path: '/app/master-data/classes/:id',
        name: 'master-data-class-detail',
        component: { template: '<div />' },
      },
      {
        path: '/app/master-data/laboratories',
        name: 'master-data-laboratories',
        component: { template: '<div />' },
      },
      {
        path: '/app/master-data/laboratories/:id',
        name: 'master-data-laboratory-detail',
        component: { template: '<div />' },
      },
    ],
  })
}

function piniaWith(role: 'ADMIN' | 'TEACHER') {
  const pinia = createPinia()
  useAuthStore(pinia).$patch({
    accessToken: 't',
    expiresAt: Date.now() + 60_000,
    account: {
      id: 'account-1',
      email: 'staff@example.test',
      full_name: 'Test Staff',
      roles: [role],
      must_change_password: false,
    },
  })
  return pinia
}

async function mountAt(path: string, role: 'ADMIN' | 'TEACHER' = 'ADMIN') {
  const router = testRouter(path)
  router.push(path)
  await router.isReady()
  const wrapper = mount(MasterDataView, { global: { plugins: [piniaWith(role), router] } })
  await flushPromises()
  return { wrapper, router }
}

beforeEach(() => {
  vi.clearAllMocks()
  api.listStudents.mockResolvedValue({
    items: [student],
    pagination: { total: 1, limit: 10, offset: 0 },
  })
  api.listClasses.mockResolvedValue({
    items: [kelas],
    pagination: { total: 1, limit: 100, offset: 0 },
  })
  api.listLaboratories.mockResolvedValue({
    items: [lab],
    pagination: { total: 1, limit: 10, offset: 0 },
  })
  api.listDevices.mockResolvedValue({ items: [], pagination: { total: 0, limit: 100, offset: 0 } })
  api.listClassTeachers.mockResolvedValue({ items: [] })
  api.listLabLaborants.mockResolvedValue({ items: [] })
  api.listClassLaboratories.mockResolvedValue({ items: [] })
  api.getStudent.mockResolvedValue({ ...student, classes: student.classes })
  api.getClass.mockResolvedValue({ ...kelas, students: [] })
  api.getLaboratory.mockResolvedValue(lab)
  api.createStudent.mockResolvedValue(student)
  api.previewStudentImport.mockResolvedValue({
    total_rows: 1,
    valid_rows: 0,
    invalid_rows: 1,
    can_commit: false,
    rows: [
      {
        row_number: 2,
        student_number: 'S-900',
        full_name: '',
        class_code: 'UNKNOWN',
        valid: false,
        errors: ['Nama siswa wajib diisi.'],
      },
    ],
  })
})

describe('master data view (Stitch B02)', () => {
  it('menampilkan daftar siswa dengan kelas dan menyembunyikan aksi tulis dari guru', async () => {
    const { wrapper } = await mountAt('/app/master-data/students', 'TEACHER')
    expect(wrapper.text()).toContain('Synthetic Student')
    expect(wrapper.text()).toContain('S-001')
    expect(wrapper.text()).toContain('XI IPA 1')
    expect(api.listStudents).toHaveBeenCalledWith({
      limit: 10,
      offset: 0,
      search: undefined,
      is_active: undefined,
      class_id: undefined,
    })
    expect(wrapper.text()).not.toContain('Tambah Siswa')
    expect(wrapper.text()).not.toContain('Impor Siswa')
    wrapper.unmount()
  })

  it('admin menambah siswa lewat drawer formulir master', async () => {
    const { wrapper } = await mountAt('/app/master-data/students', 'ADMIN')
    await wrapper
      .findAll('button')
      .find((b) => b.text().includes('Tambah Siswa'))!
      .trigger('click')
    await flushPromises()
    await wrapper.find('input[name="student_number"]').setValue('S-002')
    await wrapper.find('input[name="full_name"]').setValue('New Synthetic Student')
    await wrapper
      .findAll('button')
      .find((b) => b.text() === 'Simpan')!
      .trigger('click')
    await flushPromises()

    expect(api.createStudent).toHaveBeenCalledWith({
      student_number: 'S-002',
      full_name: 'New Synthetic Student',
    })
    expect(api.enrollStudent).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('impor menampilkan baris bermasalah dan menahan konfirmasi', async () => {
    const { wrapper } = await mountAt('/app/master-data/students', 'ADMIN')
    await wrapper
      .findAll('button')
      .find((b) => b.text().includes('Impor Siswa'))!
      .trigger('click')
    await flushPromises()
    const file = new File(['NIS,Nama,Kelas\nS-900,,UNKNOWN'], 'students.csv', { type: 'text/csv' })
    const fileInput = wrapper.find('input[type="file"]')
    Object.defineProperty(fileInput.element, 'files', { value: [file] })
    await fileInput.trigger('change')
    await wrapper
      .findAll('button')
      .find((b) => b.text().includes('Validasi Format'))!
      .trigger('click')
    await flushPromises()

    expect(api.previewStudentImport).toHaveBeenCalledWith(file, {
      student_number_column: 'NIS',
      full_name_column: 'Nama',
      class_code_column: 'Kelas',
    })
    expect(wrapper.text()).toContain('Baris Bermasalah')
    expect(wrapper.text()).toContain('Nama siswa wajib diisi.')
    const commit = wrapper.findAll('button').find((b) => b.text().includes('Konfirmasi Impor'))!
    expect(commit.attributes('disabled')).toBeDefined()
    expect(api.commitStudentImport).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('tab kelas memuat daftar dan membuka detail beserta guru penugasan', async () => {
    const { wrapper, router } = await mountAt('/app/master-data/students', 'ADMIN')
    await wrapper
      .findAll('[role="tab"]')
      .find((b) => b.text().includes('Kelas'))!
      .trigger('click')
    await flushPromises()
    await router.isReady()
    expect(router.currentRoute.value.path).toBe('/app/master-data/classes')
    expect(api.listClasses).toHaveBeenCalled()
    wrapper.unmount()

    const detail = await mountAt('/app/master-data/classes/class-1', 'ADMIN')
    expect(api.getClass).toHaveBeenCalledWith('class-1')
    expect(api.listClassTeachers).toHaveBeenCalledWith('class-1')
    expect(detail.wrapper.text()).toContain('XI IPA 1')
    detail.wrapper.unmount()
  })

  it('tab laboratorium memuat daftar dan detail perangkat', async () => {
    const { wrapper } = await mountAt('/app/master-data/laboratories', 'ADMIN')
    expect(api.listLaboratories).toHaveBeenCalled()
    expect(wrapper.text()).toContain('Lab Kimia 1')
    wrapper.unmount()

    const detail = await mountAt('/app/master-data/laboratories/lab-1', 'ADMIN')
    expect(api.getLaboratory).toHaveBeenCalledWith('lab-1')
    expect(api.listDevices).toHaveBeenCalled()
    expect(detail.wrapper.text()).toContain('Detail Lab Kimia 1')
    detail.wrapper.unmount()
  })
})
