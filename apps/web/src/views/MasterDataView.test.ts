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
  downloadStudentImportTemplate: vi.fn(),
  addClassLaboratory: vi.fn(),
  removeClassLaboratory: vi.fn(),
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
  api.addClassLaboratory.mockResolvedValue({ ok: true })
  api.removeClassLaboratory.mockResolvedValue({ ok: true })
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

  it('menonaktifkan perubahan siswa saat belum ada kelas serta memberi tautan untuk membuat kelas', async () => {
    api.listClasses.mockResolvedValue({
      items: [],
      pagination: { total: 0, limit: 100, offset: 0 },
    })
    const { wrapper, router } = await mountAt('/app/master-data/students', 'ADMIN')

    expect(wrapper.get('[data-testid="no-active-classes"]').text()).toContain(
      'Tambahkan kelas terlebih dahulu',
    )
    expect(wrapper.get('[data-testid="add-student-button"]').attributes('disabled')).toBeDefined()
    expect(
      wrapper.get('[data-testid="import-students-button"]').attributes('disabled'),
    ).toBeDefined()
    expect(
      wrapper.get('[data-testid="edit-student-student-1"]').attributes('disabled'),
    ).toBeDefined()
    expect(wrapper.get('[data-testid="no-active-classes"]').text()).toContain('mengubah')

    await wrapper.get('[data-testid="create-class-link"]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/app/master-data/classes')
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

  it('menautkan kelas yang dipilih saat membuat siswa', async () => {
    api.createStudent.mockResolvedValue({ ...student, id: 'student-2', classes: [] })
    const { wrapper } = await mountAt('/app/master-data/students', 'ADMIN')
    await wrapper
      .findAll('button')
      .find((b) => b.text().includes('Tambah Siswa'))!
      .trigger('click')
    await flushPromises()
    await wrapper.find('input[name="student_number"]').setValue('S-002')
    await wrapper.find('input[name="full_name"]').setValue('Student With Class')
    await wrapper.get('select[aria-label="Rombongan Belajar (Kelas)"]').setValue('class-1')
    await wrapper
      .findAll('button')
      .find((b) => b.text() === 'Simpan')!
      .trigger('click')
    await flushPromises()

    expect(api.createStudent).toHaveBeenCalledWith({
      student_number: 'S-002',
      full_name: 'Student With Class',
    })
    expect(api.enrollStudent).toHaveBeenCalledWith('class-1', 'student-2')
    wrapper.unmount()
  })

  it('mengisi kelas siswa saat edit dan mengganti hanya keanggotaan terbaru', async () => {
    const classNow = { ...kelas, id: 'class-2', code: 'X MIPA 2', name: 'Kelas X MIPA 2' }
    const priorYear = { ...kelas, id: 'class-0', academic_year: '2025-2026' }
    const row = { ...student, classes: [kelas, priorYear] }
    api.listStudents.mockResolvedValue({
      items: [row],
      pagination: { total: 1, limit: 10, offset: 0 },
    })
    api.listClasses.mockResolvedValue({
      items: [classNow],
      pagination: { total: 1, limit: 100, offset: 0 },
    })
    api.enrollStudent.mockResolvedValue({})
    api.removeStudentFromClass.mockResolvedValue(undefined)
    const { wrapper } = await mountAt('/app/master-data/students', 'ADMIN')

    await wrapper
      .findAll('button')
      .find((b) => b.text() === 'Edit')!
      .trigger('click')
    await flushPromises()
    const classSelect = wrapper.get('select[aria-label="Rombongan Belajar (Kelas)"]')
    expect((classSelect.element as HTMLSelectElement).value).toBe('class-1')
    await classSelect.setValue('class-2')
    await wrapper
      .findAll('button')
      .find((b) => b.text() === 'Simpan')!
      .trigger('click')
    await flushPromises()

    expect(api.enrollStudent).toHaveBeenCalledWith('class-2', 'student-1')
    expect(api.removeStudentFromClass).toHaveBeenCalledWith('class-1', 'student-1')
    expect(api.removeStudentFromClass).not.toHaveBeenCalledWith('class-0', 'student-1')
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
      student_number_column: 'NIS/NISN',
      full_name_column: 'Nama Lengkap',
      class_code_column: 'Kode Kelas',
    })
    expect(wrapper.text()).toContain('Baris Bermasalah')
    expect(wrapper.text()).toContain('Nama siswa wajib diisi.')
    const commit = wrapper.findAll('button').find((b) => b.text().includes('Konfirmasi Impor'))!
    expect(commit.attributes('disabled')).toBeDefined()
    expect(api.commitStudentImport).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('tombol unduh template mengunduh CSV contoh', async () => {
    const blob = new Blob(['student_number,full_name,class_code\n'], { type: 'text/csv' })
    api.downloadStudentImportTemplate.mockResolvedValue({
      blob,
      filename: 'template-import-siswa.csv',
    })
    const created = document.createElement.bind(document)
    const urls: string[] = []
    const originalCreateObjectURL = URL.createObjectURL
    const originalRevokeObjectURL = URL.revokeObjectURL
    // jsdom stub
    URL.createObjectURL = function stubCreate(input: Blob): string {
      void input
      urls.push('blob:template')
      return 'blob:template'
    } as typeof URL.createObjectURL
    // jsdom stub
    URL.revokeObjectURL = () => undefined
    const clicks: string[] = []
    document.createElement = ((tag: string, ...rest: never[]) => {
      const element = created(tag, ...rest) as HTMLElement
      if (tag === 'a') {
        element.click = () => {
          clicks.push((element as HTMLAnchorElement).download)
        }
      }
      return element
    }) as typeof document.createElement
    try {
      const { wrapper } = await mountAt('/app/master-data/students', 'ADMIN')
      await wrapper
        .findAll('button')
        .find((b) => b.text().includes('Impor Siswa'))!
        .trigger('click')
      await flushPromises()
      await wrapper.find('[data-testid="download-import-template"]').trigger('click')
      await flushPromises()
      expect(api.downloadStudentImportTemplate).toHaveBeenCalled()
      expect(clicks).toContain('template-import-siswa.csv')
      wrapper.unmount()
    } finally {
      document.createElement = created
      URL.createObjectURL = originalCreateObjectURL
      URL.revokeObjectURL = originalRevokeObjectURL
    }
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

  it('admin menautkan dan melepas relasi kelas-lab dari detail laboratorium', async () => {
    api.listClassLaboratories.mockResolvedValue({ items: [] })
    const { wrapper } = await mountAt('/app/master-data/laboratories/lab-1', 'ADMIN')
    expect(wrapper.text()).toContain('Kelas yang Dilayani')
    expect(wrapper.text()).toContain('Belum ada pemetaan kelas.')

    const selects = wrapper.findAll('select')
    const classSelect = selects.find(
      (el) => el.attributes('aria-label') === 'Pilih kelas untuk dilayani lab ini',
    )
    expect(classSelect?.exists()).toBe(true)
    await classSelect!.setValue('class-1')
    const forms = wrapper.findAll('form')
    const mapForm = forms.find((form) => form.text().includes('Tautkan'))
    expect(mapForm?.exists()).toBe(true)
    await mapForm!.trigger('submit.prevent')
    await flushPromises()
    expect(api.addClassLaboratory).toHaveBeenCalledWith('class-1', 'lab-1')
    expect(wrapper.text()).toContain('Relasi kelas-lab diperbarui.')
    wrapper.unmount()
  })

  it('guru tidak melihat form relasi kelas-lab', async () => {
    const { wrapper } = await mountAt('/app/master-data/laboratories/lab-1', 'TEACHER')
    expect(wrapper.text()).toContain('Kelas yang Dilayani')
    expect(wrapper.find('button.st-link--danger').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('Tautkan')
    wrapper.unmount()
  })
})
