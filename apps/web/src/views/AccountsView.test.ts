import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import AccountsView from './AccountsView.vue'

const api = vi.hoisted(() => ({
  listAccounts: vi.fn(),
  listLaboratories: vi.fn(),
  listClasses: vi.fn(),
  getStaffAccount: vi.fn(),
  listLaborantAssignments: vi.fn(),
  listPermissionGrants: vi.fn(),
  listTeacherAssignments: vi.fn(),
  createStaffAccount: vi.fn(),
  updateStaffAccount: vi.fn(),
  resetStaffPassword: vi.fn(),
  setStaffPassword: vi.fn(),
  addLaborantAssignment: vi.fn(),
  removeLaborantAssignment: vi.fn(),
  addTeacherAssignment: vi.fn(),
  removeTeacherAssignment: vi.fn(),
  grantOptionalPermission: vi.fn(),
  revokeOptionalPermission: vi.fn(),
}))

vi.mock('../api/client', () => ({
  ApiError: class ApiError extends Error {},
  ...api,
}))

function account(id: string, roles: string[]) {
  return {
    id,
    full_name: `Nama ${id}`,
    email: `${id}@example.test`,
    roles,
    is_active: true,
    opening_mode: 'manual',
    created_at: '2026-01-01T00:00:00Z',
  }
}

async function openDrawer(detailRoles: string[]) {
  api.listAccounts.mockResolvedValue({
    items: [account('akun-1', detailRoles)],
    pagination: { total: 1, limit: 100, offset: 0 },
  })
  api.listLaboratories.mockResolvedValue({
    items: [],
    pagination: { total: 0, limit: 100, offset: 0 },
  })
  api.listClasses.mockResolvedValue({ items: [], pagination: { total: 0, limit: 100, offset: 0 } })
  api.getStaffAccount.mockResolvedValue(account('akun-1', detailRoles))
  api.listLaborantAssignments.mockResolvedValue({ items: [] })
  api.listPermissionGrants.mockResolvedValue({ extra_permissions: [], grantable: [] })
  api.listTeacherAssignments.mockResolvedValue({ items: [] })
  const wrapper = mount(AccountsView)
  await flushPromises()
  await wrapper.find('[data-testid="manage-akun-1"]').trigger('click')
  await flushPromises()
  return wrapper
}

describe('drawer kelola staf per role', () => {
  it('guru: hanya seksi guru + mode sesi, tanpa seksi laboran', async () => {
    const wrapper = await openDrawer(['TEACHER'])
    try {
      const drawer = wrapper.find('[data-testid="account-manage"]')
      expect(drawer.exists()).toBe(true)
      expect(wrapper.text()).toContain('Kelola guru')
      expect(wrapper.text()).toContain('Penugasan guru')
      expect(wrapper.text()).toContain('Mode pembukaan sesi (guru)')
      expect(wrapper.text()).not.toContain('Penugasan laboran')
      expect(wrapper.text()).not.toContain('Hak akses opsional')
      expect(wrapper.text()).not.toContain('Tautkan')
    } finally {
      wrapper.unmount()
      vi.unstubAllGlobals()
    }
  })

  it('laboran: hanya seksi laboran + izin, tanpa seksi guru', async () => {
    const wrapper = await openDrawer(['LABORANT'])
    try {
      expect(wrapper.text()).toContain('Kelola laboran')
      expect(wrapper.text()).toContain('Penugasan laboran')
      expect(wrapper.text()).toContain('Hak akses opsional')
      expect(wrapper.text()).not.toContain('Penugasan guru')
      expect(wrapper.text()).not.toContain('Mode pembukaan sesi')
      expect(wrapper.text()).not.toContain('Tautkan')
    } finally {
      wrapper.unmount()
      vi.unstubAllGlobals()
    }
  })

  it('admin: tanpa seksi guru/laboran dan tanpa ubah role', async () => {
    const wrapper = await openDrawer(['ADMIN'])
    try {
      expect(wrapper.text()).toContain('Kelola admin')
      expect(wrapper.text()).not.toContain('Penugasan guru')
      expect(wrapper.text()).not.toContain('Penugasan laboran')
      expect(wrapper.text()).not.toContain('Mode pembukaan sesi')
      expect(wrapper.find('[data-testid="edit-role"]').exists()).toBe(false)
    } finally {
      wrapper.unmount()
      vi.unstubAllGlobals()
    }
  })
})
