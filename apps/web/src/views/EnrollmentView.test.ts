import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import EnrollmentView from './EnrollmentView.vue'

const api = vi.hoisted(() => ({
  listClasses: vi.fn(),
  listClassEnrollmentStatus: vi.fn(),
  listFaceTemplates: vi.fn(),
  revokeFaceTemplate: vi.fn(),
  submitEnrollmentCaptures: vi.fn(),
}))

vi.mock('../api/client', () => ({
  ApiError: class extends Error {
    code?: string
    details?: { field: string; message: string }[]
    constructor(_status?: number, code?: string, message?: string) {
      super(message)
      if (code !== undefined) this.code = code
    }
  },
  ...api,
}))

const enrolledStudent = {
  id: 'student-enrolled',
  student_number: '2403',
  full_name: 'Tio Mahendra',
  template_status: 'enrolled',
}
const pendingStudent = {
  id: 'student-pending',
  student_number: '2407',
  full_name: 'Sinta Aulia',
  template_status: 'not_enrolled',
}

function mountView() {
  return mount(EnrollmentView, {
    global: {
      stubs: { UiPageHeader: { template: '<div><slot name="actions" /><slot /></div>' } },
    },
  })
}

describe('enrollment revoke dialog', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.listClasses.mockResolvedValue({
      items: [
        {
          id: 'class-1',
          code: 'XII-RPL-1',
          name: 'Kelas XII RPL 1',
          academic_year: '2026-2027',
          grade: 12,
          homeroom_teacher_id: null,
          is_active: true,
        },
      ],
      pagination: { total: 1, limit: 100, offset: 0 },
    })
    api.listClassEnrollmentStatus.mockResolvedValue([enrolledStudent, pendingStudent])
    api.listFaceTemplates.mockResolvedValue([{ id: 'template-1' }])
    api.revokeFaceTemplate.mockResolvedValue({ id: 'template-1' })
  })

  it('membuka dialog konfirmasi kritis dan memvalidasi alasan', async () => {
    const wrapper = mountView()
    await flushPromises()

    await wrapper
      .find('[data-testid="enrollment-student-student-enrolled"] .st-rowbtn')
      .trigger('click')
    await flushPromises()

    const opener = wrapper.find('[data-testid="revoke-enrollment-template"]')
    expect(opener.exists()).toBe(true)
    await opener.trigger('click')
    await flushPromises()

    expect(wrapper.find('[data-testid="revoke-identity"]').text()).toContain('Tio Mahendra')
    const confirm = wrapper.find('[data-testid="confirm-revoke-template"]')
    expect(confirm.attributes('disabled')).toBeDefined()

    await wrapper.find('[data-testid="revoke-reason-input"]').setValue('kurang')
    expect(
      wrapper.find('[data-testid="confirm-revoke-template"]').attributes('disabled'),
    ).toBeDefined()

    await wrapper
      .find('[data-testid="revoke-reason-input"]')
      .setValue('Kualitas tangkapan lama buruk dan sering galat')
    expect(
      wrapper.find('[data-testid="confirm-revoke-template"]').attributes('disabled'),
    ).toBeUndefined()

    await wrapper.find('[data-testid="confirm-revoke-template"]').trigger('click')
    await flushPromises()

    expect(api.revokeFaceTemplate).toHaveBeenCalledWith('template-1')
    expect(wrapper.find('[data-testid="revoke-identity"]').exists()).toBe(false)
  })
})
