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

const emptyGrantList: {
  base_permissions: string[]
  extra_permissions: string[]
  grantable: string[]
} = { base_permissions: [], extra_permissions: [], grantable: [] }

async function openDrawer(
  detailRoles: string[],
  openManagement = true,
  grantList = emptyGrantList,
  classOptions: { id: string; code: string; name: string; academic_year: string }[] = [],
  teacherAssignments: {
    class_id: string
    code: string | null
    name: string | null
    starts_on: string | null
    ends_on: string | null
    is_substitute: boolean
  }[] = [],
  permissionLoadFails = false,
) {
  api.listAccounts.mockResolvedValue({
    items: [account('akun-1', detailRoles)],
    pagination: { total: 1, limit: 100, offset: 0 },
  })
  api.listLaboratories.mockResolvedValue({
    items: [],
    pagination: { total: 0, limit: 100, offset: 0 },
  })
  api.listClasses.mockResolvedValue({
    items: classOptions,
    pagination: { total: classOptions.length, limit: 100, offset: 0 },
  })
  api.getStaffAccount.mockResolvedValue(account('akun-1', detailRoles))
  api.listLaborantAssignments.mockResolvedValue({ items: [] })
  if (permissionLoadFails) {
    api.listPermissionGrants.mockRejectedValue(new Error('permission service unavailable'))
  } else {
    api.listPermissionGrants.mockResolvedValue(grantList)
  }
  api.listTeacherAssignments.mockResolvedValue({ items: teacherAssignments })
  const wrapper = mount(AccountsView)
  await flushPromises()
  if (openManagement) {
    await wrapper.find('[data-testid="manage-akun-1"]').trigger('click')
    await flushPromises()
  }
  return wrapper
}

describe('drawer kelola staf per role', () => {
  it('guru: hanya seksi guru + mode sesi, tanpa seksi laboran', async () => {
    const wrapper = await openDrawer(['TEACHER'], true, {
      base_permissions: ['session_view', 'reports_read'],
      extra_permissions: [],
      grantable: ['attendance_correct_closed'],
    })
    try {
      const drawer = wrapper.find('[data-testid="account-manage"]')
      expect(drawer.exists()).toBe(true)
      expect(wrapper.text()).toContain('Kelola guru')
      expect(wrapper.text()).toContain('Penugasan guru')
      expect(wrapper.text()).toContain('Mode pembukaan sesi (guru)')
      expect(wrapper.text()).not.toContain('Penugasan laboran')
      expect(wrapper.text()).not.toContain('Hak akses opsional')
      expect(wrapper.text()).toContain('Akses bawaan guru')
      expect(wrapper.text()).toContain('Pantau Sesi')
      expect(wrapper.text()).toContain('Lihat Laporan')
      expect(wrapper.text()).toContain('Koreksi Sesi Tertutup')
      expect(wrapper.text()).toContain('Hak akses tambahan aktif: -')
      expect(wrapper.text()).not.toContain('Lihat Jadwal')
      expect(api.listPermissionGrants).toHaveBeenCalled()
      expect(wrapper.text()).not.toContain('Tautkan')
    } finally {
      wrapper.unmount()
      vi.unstubAllGlobals()
    }
  })

  it('laboran: hanya seksi laboran + izin, tanpa seksi guru', async () => {
    const wrapper = await openDrawer(['LABORANT'], true, {
      base_permissions: ['roster_read', 'laboratory_read', 'device_operate', 'enrollment_manage'],
      extra_permissions: [],
      grantable: ['schedule_read', 'schedule_manage'],
    })
    try {
      expect(wrapper.text()).toContain('Kelola laboran')
      expect(wrapper.text()).toContain('Penugasan laboran')
      expect(wrapper.text()).toContain('Akses bawaan laboran')
      expect(wrapper.text()).toContain('Baca Roster')
      expect(wrapper.text()).toContain('Operasikan Perangkat')
      expect(wrapper.text()).toContain('Hak akses tambahan')
      expect(wrapper.text()).not.toContain('Penugasan guru')
      expect(wrapper.text()).not.toContain('Mode pembukaan sesi')
      expect(wrapper.text()).not.toContain('Tautkan')
    } finally {
      wrapper.unmount()
      vi.unstubAllGlobals()
    }
  })

  it('tidak menampilkan izin kosong jika daftar izin gagal dimuat', async () => {
    const wrapper = await openDrawer(['TEACHER'], true, emptyGrantList, [], [], true)
    try {
      expect(wrapper.find('[data-testid="permission-grants-load-error"]').exists()).toBe(true)
      expect(wrapper.find('[data-testid="base-permissions"]').exists()).toBe(false)
      expect(wrapper.text()).not.toContain('Tidak ada akses bawaan.')
      expect(wrapper.text()).not.toContain('Koreksi Sesi Tertutup')
    } finally {
      wrapper.unmount()
      vi.unstubAllGlobals()
    }
  })

  it('menyembunyikan kelas yang sudah ditugaskan dari pilihan kelas guru', async () => {
    const wrapper = await openDrawer(
      ['TEACHER'],
      true,
      emptyGrantList,
      [
        { id: 'kelas-1', code: 'TES1', name: 'MIPA TES', academic_year: '2026-2027' },
        { id: 'kelas-2', code: 'TES2', name: 'MIPA TES 2', academic_year: '2026-2027' },
      ],
      [
        {
          class_id: 'kelas-1',
          code: 'TES1',
          name: 'MIPA TES',
          starts_on: null,
          ends_on: null,
          is_substitute: false,
        },
      ],
    )
    try {
      const options = wrapper
        .findAll('select[aria-label="Pilih kelas untuk guru"] option')
        .map((option) => option.attributes('value'))
      expect(options).not.toContain('kelas-1')
      expect(options).toContain('kelas-2')
    } finally {
      wrapper.unmount()
      vi.unstubAllGlobals()
    }
  })

  it('memilih semua izin tambahan dengan prasyarat sebelum izin turunannya', async () => {
    const grantable = [
      'attendance_correct_closed',
      'attendance_manual',
      'attendance_read',
      'session_operate',
      'session_view',
    ]
    const active = new Set<string>()
    api.grantOptionalPermission.mockImplementation(async (_accountId, permission) => {
      active.add(String(permission))
    })
    api.listPermissionGrants.mockImplementation(async () => ({
      base_permissions: [],
      extra_permissions: [...active],
      grantable,
    }))
    const wrapper = await openDrawer(['LABORANT'], true, {
      base_permissions: [],
      extra_permissions: [],
      grantable,
    })
    try {
      api.grantOptionalPermission.mockClear()
      const sessionPermissions = wrapper
        .findAll('.accounts-view__permission-group')
        .find((group) => group.find('h4').text() === 'Sesi dan Kehadiran')
      const selectAll = sessionPermissions?.find('label.accounts-view__select-all')
      expect(selectAll).toBeDefined()
      await selectAll!.get('input[type="checkbox"]').setValue(true)
      await flushPromises()
      expect(api.grantOptionalPermission.mock.calls.map(([, permission]) => permission)).toEqual([
        'session_view',
        'attendance_correct_closed',
        'attendance_manual',
        'attendance_read',
        'session_operate',
      ])
    } finally {
      wrapper.unmount()
      vi.unstubAllGlobals()
    }
  })

  it('admin: menampilkan role tetapi menyembunyikan tombol Kelola', async () => {
    const wrapper = await openDrawer(['ADMIN'], false)
    try {
      expect(wrapper.text()).toContain('Admin')
      expect(wrapper.find('[data-testid="account-list"] table').exists()).toBe(true)
      expect(wrapper.find('[data-testid="manage-akun-1"]').exists()).toBe(false)
    } finally {
      wrapper.unmount()
      vi.unstubAllGlobals()
    }
  })
})
