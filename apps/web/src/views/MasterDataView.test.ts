import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useAuthStore } from '../stores/auth'
import MasterDataView from './MasterDataView.vue'

const api = vi.hoisted(() => ({
  listStudents: vi.fn(),
  listClasses: vi.fn(),
  listLaboratories: vi.fn(),
  createStudent: vi.fn(),
  previewStudentImport: vi.fn(),
  commitStudentImport: vi.fn(),
  createClass: vi.fn(),
  createLaboratory: vi.fn(),
  updateStudent: vi.fn(),
  updateClass: vi.fn(),
  updateLaboratory: vi.fn(),
  getStudent: vi.fn(),
  getClass: vi.fn(),
  getLaboratory: vi.fn(),
  enrollStudent: vi.fn(),
  removeStudentFromClass: vi.fn(),
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
  created_at: '2026-10-01T00:00:00Z',
  updated_at: '2026-10-01T00:00:00Z',
}

function authenticatedPinia(role: 'ADMIN' | 'TEACHER') {
  const pinia = createPinia()
  useAuthStore(pinia).$patch({
    accessToken: 'unit-test-token',
    expiresAt: Date.now() + 60_000,
    account: {
      id: 'account-1',
      email: 'staff@example.test',
      full_name: 'Test Staff',
      roles: [role],
    },
  })
  return pinia
}

describe('master data view', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.listStudents.mockResolvedValue({
      items: [student],
      pagination: { total: 1, limit: 10, offset: 0 },
    })
    api.listClasses.mockResolvedValue({
      items: [],
      pagination: { total: 0, limit: 10, offset: 0 },
    })
    api.listLaboratories.mockResolvedValue({
      items: [],
      pagination: { total: 0, limit: 10, offset: 0 },
    })
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
          errors: ['Nama siswa wajib diisi.', 'Kelas tidak ditemukan.'],
        },
      ],
    })
  })

  it('loads generated API data and hides write controls from read-only roles', async () => {
    const wrapper = mount(MasterDataView, { global: { plugins: [authenticatedPinia('TEACHER')] } })
    await flushPromises()

    expect(wrapper.text()).toContain('Synthetic Student')
    expect(wrapper.find('[data-testid="create-record"]').exists()).toBe(false)
    expect(api.listStudents).toHaveBeenCalledWith({ limit: 10, offset: 0, search: undefined })
    wrapper.unmount()
  })

  it('submits a student create form for an administrator', async () => {
    const wrapper = mount(MasterDataView, { global: { plugins: [authenticatedPinia('ADMIN')] } })
    await flushPromises()
    await wrapper.get('[data-testid="create-record"]').trigger('click')
    await wrapper.get('input[maxlength="32"]').setValue('S-002')
    await wrapper.get('input[autocomplete="name"]').setValue('New Synthetic Student')
    await wrapper.get('form.master-data__form').trigger('submit')
    await flushPromises()

    expect(api.createStudent).toHaveBeenCalledWith({
      student_number: 'S-002',
      full_name: 'New Synthetic Student',
    })
    expect(wrapper.find('[aria-labelledby="form-title"]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('shows import row errors and prevents committing invalid preview rows', async () => {
    const wrapper = mount(MasterDataView, { global: { plugins: [authenticatedPinia('ADMIN')] } })
    await flushPromises()
    await wrapper.get('[data-testid="open-student-import"]').trigger('click')
    const file = new File(['NIS,Nama,Kelas\nS-900,,UNKNOWN'], 'students.csv', {
      type: 'text/csv',
    })
    const fileInput = wrapper.get<HTMLInputElement>('input[type="file"]')
    Object.defineProperty(fileInput.element, 'files', { value: [file] })
    await fileInput.trigger('change')
    await wrapper.find('.master-data__panel form').trigger('submit')
    await flushPromises()

    expect(api.previewStudentImport).toHaveBeenCalledWith(file, {
      student_number_column: 'NIS',
      full_name_column: 'Nama',
      class_code_column: 'Kelas',
    })
    expect(wrapper.get('[data-testid="import-row-2"]').text()).toContain('Tidak valid')
    expect(
      wrapper.get('[data-testid="commit-student-import"]').attributes('disabled'),
    ).toBeDefined()
    expect(api.commitStudentImport).not.toHaveBeenCalled()
    wrapper.unmount()
  })
})
