<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import UiDrawer from '../components/ui/UiDrawer.vue'
import { UiBadge, UiButton, UiInput, UiModal, UiPageHeader, UiSelect } from '../components/ui'
import {
  addLaborantAssignment,
  addTeacherAssignment,
  ApiError,
  createStaffAccount,
  getStaffAccount,
  grantOptionalPermission,
  listAccounts,
  listClasses,
  listLaboratories,
  listLaborantAssignments,
  listPermissionGrants,
  listTeacherAssignments,
  removeLaborantAssignment,
  removeTeacherAssignment,
  revokeOptionalPermission,
  setStaffPassword,
  updateStaffAccount,
  type Account,
  type AccountDetail,
  type Laboratory,
  type SchoolClass,
  type StaffAccountCreate,
} from '../api/client'

const emptyCreateForm = (): StaffAccountCreate => ({
  full_name: '',
  email: '',
  role: 'TEACHER',
  password: '',
})
const form = ref<StaffAccountCreate>(emptyCreateForm())
const isCreateOpen = ref(false)
const isSaving = ref(false)
const createError = ref<string | null>(null)
const createdMessage = ref<string | null>(null)
const accounts = ref<Account[]>([])
const accountsTotal = ref(0)
const isLoadingAccounts = ref(false)
const accountsError = ref<string | null>(null)
const selectedDetail = ref<AccountDetail | null>(null)
const detailError = ref<string | null>(null)
const laboratories = ref<Laboratory[]>([])
const assignments = ref<{ laboratory_id: string; code: string | null; name: string | null }[]>([])
const grants = ref<{
  base_permissions: string[]
  extra_permissions: string[]
  grantable: string[]
}>({
  base_permissions: [],
  extra_permissions: [],
  grantable: [],
})
const permissionGrantsLoadFailed = ref(false)
const activeAdditionalPermissions = computed(() =>
  grants.value.extra_permissions.filter(
    (permission) => !grants.value.base_permissions.includes(permission),
  ),
)

import { PERMISSION_META } from '../utils/permissions'

const grantGroups = (permList: string[]): { group: string; perms: string[] }[] => {
  const groups: { group: string; perms: string[] }[] = []
  for (const perm of permList) {
    const group = PERMISSION_META[perm]?.group ?? 'Lainnya'
    const found = groups.find((g) => g.group === group)
    if (found) found.perms.push(perm)
    else groups.push({ group, perms: [perm] })
  }
  return groups
}

const allOperationalSelected = (permList: string[]): boolean =>
  permList.length > 0 && permList.every((p) => grants.value.extra_permissions.includes(p))

type ManagedRole = 'ADMIN' | 'TEACHER' | 'LABORANT'
const managedRole = (detail: AccountDetail | null): ManagedRole => {
  if (!detail) return 'TEACHER'
  if (detail.roles.includes('ADMIN')) return 'ADMIN'
  if (detail.roles.includes('LABORANT')) return 'LABORANT'
  return 'TEACHER'
}
const isTeacherAccount = (detail: AccountDetail | null): boolean =>
  managedRole(detail) === 'TEACHER'
const isLaborantAccount = (detail: AccountDetail | null): boolean =>
  managedRole(detail) === 'LABORANT'
const isAdminAccount = (detail: AccountDetail | null): boolean => managedRole(detail) === 'ADMIN'
const manageSubtitle = (detail: AccountDetail | null): string => {
  const role = managedRole(detail)
  if (role === 'TEACHER') return 'Kelola guru'
  if (role === 'LABORANT') return 'Kelola laboran'
  return 'Kelola admin'
}
const accountRoleLabels: Record<string, string> = {
  ADMIN: 'Admin',
  TEACHER: 'Guru',
  LABORANT: 'Laboran',
}
const accountRoleLabel = (role: string): string => accountRoleLabels[role] ?? role
const permissionLabels = (permissions: string[]): string =>
  permissions.map((permission) => PERMISSION_META[permission]?.label ?? permission).join(', ') ||
  '-'

function permissionDependencyOrder(permissions: string[]): string[] {
  const included = new Set(permissions)
  const visited = new Set<string>()
  const ordered: string[] = []
  const visit = (permission: string): void => {
    if (visited.has(permission)) return
    visited.add(permission)
    const prerequisite = PERMISSION_META[permission]?.needs
    if (prerequisite && included.has(prerequisite)) visit(prerequisite)
    ordered.push(permission)
  }
  permissions.forEach(visit)
  return ordered
}

async function toggleAllOperational(permList: string[], enabled: boolean): Promise<void> {
  const ordered = permissionDependencyOrder(permList)
  const changes = enabled ? ordered : [...ordered].reverse()
  for (const perm of changes) {
    const active = grants.value.extra_permissions.includes(perm)
    if (enabled && !active) await toggleGrant(perm, true)
    else if (!enabled && active) await toggleGrant(perm, false)
  }
}
const editName = ref('')
const editActive = ref(true)
const editOpeningMode = ref<'manual' | 'automatic'>('manual')
const editRole = ref<'TEACHER' | 'LABORANT'>('TEACHER')
const editDeactivationReason = ref('')
const schoolClasses = ref<SchoolClass[]>([])
const teacherAssignments = ref<
  {
    class_id: string
    code: string | null
    name: string | null
    starts_on: string | null
    ends_on: string | null
    is_substitute: boolean
  }[]
>([])
const selectedTeacherClass = ref('')
const availableTeacherClasses = computed(() => {
  const assignedClassIds = new Set(teacherAssignments.value.map((item) => item.class_id))
  return schoolClasses.value.filter((schoolClass) => !assignedClassIds.has(schoolClass.id))
})
const manageMessage = ref<string | null>(null)
const managingId = ref<string | null>(null)
const newPassword = ref('')
const showPasswordForm = ref(false)
const setPasswordMessage = ref<string | null>(null)
const setPasswordError = ref<string | null>(null)
const isSettingPassword = ref(false)

async function loadAccounts(): Promise<void> {
  isLoadingAccounts.value = true
  accountsError.value = null
  try {
    const page = await listAccounts({ limit: 100, offset: 0 })
    accounts.value = page.items
    accountsTotal.value = page.pagination.total
  } catch (error) {
    accountsError.value = formatError(error)
  } finally {
    isLoadingAccounts.value = false
  }
}

async function loadLabs(): Promise<void> {
  try {
    const page = await listLaboratories({ limit: 100, offset: 0 })
    laboratories.value = page.items
  } catch {
    // optional
  }
}

async function selectAccount(account: Account): Promise<void> {
  if (managingId.value) return
  managingId.value = account.id
  detailError.value = null
  manageMessage.value = null
  permissionGrantsLoadFailed.value = false
  showPasswordForm.value = false
  setPasswordMessage.value = null
  setPasswordError.value = null
  newPassword.value = ''
  try {
    selectedDetail.value = await getStaffAccount(account.id)
    editName.value = selectedDetail.value.full_name
    editActive.value = selectedDetail.value.is_active
    editOpeningMode.value =
      selectedDetail.value.opening_mode === 'automatic' ? 'automatic' : 'manual'
    editRole.value = selectedDetail.value.roles.includes('TEACHER') ? 'TEACHER' : 'LABORANT'
    const role = managedRole(selectedDetail.value)
    assignments.value = []
    grants.value = { base_permissions: [], extra_permissions: [], grantable: [] }
    teacherAssignments.value = []
    if (role === 'LABORANT') {
      const [assignRes, grantRes] = await Promise.all([
        listLaborantAssignments(account.id).catch(() => ({ items: [] })),
        listPermissionGrants(account.id).catch((error: unknown) => {
          permissionGrantsLoadFailed.value = true
          throw error
        }),
      ])
      assignments.value = (assignRes as { items: typeof assignments.value }).items
      grants.value = grantRes as typeof grants.value
    } else if (role === 'TEACHER') {
      const [teacherRes, grantRes] = await Promise.all([
        listTeacherAssignments(account.id).catch(() => ({ items: [] })),
        listPermissionGrants(account.id).catch((error: unknown) => {
          permissionGrantsLoadFailed.value = true
          throw error
        }),
      ])
      teacherAssignments.value = (teacherRes as { items: typeof teacherAssignments.value }).items
      grants.value = grantRes as typeof grants.value
    }
    editDeactivationReason.value = ''
  } catch (error) {
    detailError.value = formatError(error)
  } finally {
    managingId.value = null
  }
}

function closeManage(): void {
  selectedDetail.value = null
  newPassword.value = ''
  showPasswordForm.value = false
  setPasswordMessage.value = null
  setPasswordError.value = null
}

function openPasswordForm(): void {
  newPassword.value = ''
  setPasswordMessage.value = null
  setPasswordError.value = null
  showPasswordForm.value = true
}

function closePasswordForm(): void {
  if (isSettingPassword.value) return
  newPassword.value = ''
  setPasswordError.value = null
  showPasswordForm.value = false
}

async function saveAccount(): Promise<void> {
  if (!selectedDetail.value) return
  try {
    const roleForSave = managedRole(selectedDetail.value)
    const currentRole = roleForSave === 'ADMIN' ? 'ADMIN' : roleForSave
    selectedDetail.value = await updateStaffAccount(selectedDetail.value.id, {
      full_name: editName.value.trim() || undefined,
      is_active: editActive.value,
      opening_mode: roleForSave === 'TEACHER' ? editOpeningMode.value : undefined,
      role: roleForSave === 'ADMIN' || editRole.value === currentRole ? undefined : editRole.value,
      deactivation_reason:
        editActive.value || !editDeactivationReason.value.trim()
          ? undefined
          : editDeactivationReason.value.trim(),
    })
    manageMessage.value =
      roleForSave === 'TEACHER'
        ? 'Akun guru diperbarui: aktif/nonaktif, nama, penugasan kelas, dan mode pembukaan sesi.'
        : roleForSave === 'LABORANT'
          ? 'Akun laboran diperbarui: aktif/nonaktif, nama, penugasan lab, dan izin tambahan.'
          : 'Akun admin diperbarui: aktif/nonaktif dan nama.'
    void loadAccounts()
  } catch (error) {
    detailError.value = formatError(error)
  }
}

async function doSetPassword(): Promise<void> {
  if (!selectedDetail.value || isSettingPassword.value) return
  setPasswordError.value = null
  setPasswordMessage.value = null
  const value = newPassword.value
  if (value.length < 8) {
    setPasswordError.value = 'Kata sandi minimal 8 karakter tanpa spasi.'
    return
  }
  if (/\s/.test(value)) {
    setPasswordError.value = 'Kata sandi tidak boleh mengandung spasi.'
    return
  }
  isSettingPassword.value = true
  try {
    await setStaffPassword(selectedDetail.value.id, value)
    newPassword.value = ''
    showPasswordForm.value = false
    setPasswordMessage.value =
      'Kata sandi diperbarui. Staf dapat langsung masuk memakai kata sandi baru.'
  } catch (error) {
    setPasswordError.value = formatError(error)
  } finally {
    isSettingPassword.value = false
  }
}

async function toggleGrant(permission: string, enabled: boolean): Promise<void> {
  if (!selectedDetail.value) return
  detailError.value = null
  try {
    if (enabled) await grantOptionalPermission(selectedDetail.value.id, permission)
    else await revokeOptionalPermission(selectedDetail.value.id, permission)
    try {
      const g = await listPermissionGrants(selectedDetail.value.id)
      grants.value = g
      permissionGrantsLoadFailed.value = false
      manageMessage.value = 'Hak akses opsional diperbarui.'
    } catch (error) {
      permissionGrantsLoadFailed.value = true
      throw error
    }
  } catch (error) {
    detailError.value = formatError(error)
  }
}

async function assignLab(labId: string): Promise<void> {
  if (!selectedDetail.value || !labId) return
  try {
    await addLaborantAssignment(selectedDetail.value.id, labId)
    const a = await listLaborantAssignments(selectedDetail.value.id)
    assignments.value = (a as { items: typeof assignments.value }).items
    manageMessage.value = 'Penugasan lab diperbarui.'
  } catch (error) {
    detailError.value = formatError(error)
  }
}

async function unassignLab(labId: string): Promise<void> {
  if (!selectedDetail.value) return
  try {
    await removeLaborantAssignment(selectedDetail.value.id, labId)
    const a = await listLaborantAssignments(selectedDetail.value.id)
    assignments.value = (a as { items: typeof assignments.value }).items
  } catch (error) {
    detailError.value = formatError(error)
  }
}

async function loadClassOptions(): Promise<void> {
  try {
    const classPage = await listClasses({ limit: 100, offset: 0 })
    schoolClasses.value = classPage.items
  } catch {
    // optional
  }
}

async function refreshTeacherAssignments(): Promise<void> {
  if (!selectedDetail.value) return
  try {
    const res = await listTeacherAssignments(selectedDetail.value.id)
    teacherAssignments.value = res.items
    manageMessage.value = 'Penugasan guru diperbarui.'
  } catch (error) {
    detailError.value = formatError(error)
  }
}

async function assignTeacherClass(): Promise<void> {
  if (!selectedDetail.value || !selectedTeacherClass.value) return
  try {
    await addTeacherAssignment(selectedDetail.value.id, {
      class_id: selectedTeacherClass.value,
      is_substitute: false,
    })
    selectedTeacherClass.value = ''
    await refreshTeacherAssignments()
  } catch (error) {
    detailError.value = formatError(error)
  }
}

async function unassignTeacherClass(classId: string): Promise<void> {
  if (!selectedDetail.value) return
  try {
    await removeTeacherAssignment(selectedDetail.value.id, classId)
    await refreshTeacherAssignments()
  } catch (error) {
    detailError.value = formatError(error)
  }
}

onMounted(() => {
  void loadAccounts()
  void loadLabs()
  void loadClassOptions()
})

function formatError(error: unknown): string {
  if (error instanceof ApiError) {
    const details = error.details?.map((item) => `${item.field}: ${item.message}`)
    return details?.length ? details.join(' · ') : error.message
  }
  return 'Permintaan tidak dapat diproses. Coba lagi.'
}

async function submitForm(): Promise<void> {
  createError.value = null
  isSaving.value = true
  try {
    const created = await createStaffAccount({
      ...form.value,
      full_name: form.value.full_name.trim(),
      email: form.value.email.trim(),
    })
    createdMessage.value = `Akun ${created.full_name} berhasil dibuat.`
    isCreateOpen.value = false
    form.value = emptyCreateForm()
    void loadAccounts()
  } catch (error) {
    createError.value = formatError(error)
  } finally {
    isSaving.value = false
  }
}

function openCreate(): void {
  form.value = emptyCreateForm()
  createError.value = null
  createdMessage.value = null
  isCreateOpen.value = true
}

function closeCreate(): void {
  if (isSaving.value) return
  isCreateOpen.value = false
  form.value.password = ''
}
</script>

<template>
  <div class="st-page" aria-label="Kelola akun staf">
    <UiPageHeader
      eyebrow="Administrasi"
      title="Kelola akun staf"
      description="Kelola akses guru dan laboran."
    >
      <template #actions>
        <UiButton variant="primary" type="button" @click="openCreate">Tambah Staff</UiButton>
      </template>
    </UiPageHeader>

    <p v-if="createdMessage" class="master-data__success" role="status">
      {{ createdMessage }}
    </p>

    <section class="master-data__panel">
      <div class="master-data__panel-heading">
        <div>
          <p class="master-data__eyebrow">Akun internal · {{ accountsTotal }} terdaftar</p>
          <h2>Akun staf terdaftar</h2>
        </div>
        <UiButton
          variant="secondary"
          type="button"
          :disabled="isLoadingAccounts"
          @click="loadAccounts"
        >
          {{ isLoadingAccounts ? 'Memuat…' : 'Muat ulang' }}
        </UiButton>
      </div>
      <p v-if="accountsError" class="st-alert st-alert--error" role="alert">{{ accountsError }}</p>
      <p v-else-if="isLoadingAccounts" class="accounts-view__hint">Memuat daftar akun…</p>
      <p
        v-else-if="accounts.length && accounts.length < accountsTotal"
        class="accounts-view__hint"
        role="status"
      >
        Menampilkan {{ accounts.length }} dari {{ accountsTotal }} akun (100 terbaru). Gunakan
        filter/paginasi API untuk sisanya.
      </p>
      <div v-else-if="accounts.length" class="st-tablewrap" data-testid="account-list">
        <table class="st-table">
          <thead>
            <tr>
              <th scope="col">Nama</th>
              <th scope="col">Email</th>
              <th scope="col">Role</th>
              <th scope="col">Status</th>
              <th scope="col">Aksi</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="account in accounts" :key="account.id">
              <td class="st-table__mono">{{ account.full_name }}</td>
              <td>{{ account.email }}</td>
              <td>
                <div class="accounts-view__roles">
                  <UiBadge
                    v-for="role in account.roles"
                    :key="role"
                    :tone="role === 'ADMIN' ? 'info' : 'neutral'"
                  >
                    {{ accountRoleLabel(role) }}
                  </UiBadge>
                  <span v-if="!account.roles.length" class="st-table__muted">Tanpa role</span>
                </div>
              </td>
              <td>
                <UiBadge :tone="account.is_active ? 'present' : 'absent'">
                  {{ account.is_active ? 'Aktif' : 'Nonaktif' }}
                </UiBadge>
              </td>
              <td class="st-table__actions">
                <UiButton
                  v-if="!account.roles.includes('ADMIN')"
                  variant="secondary"
                  type="button"
                  :data-testid="'manage-' + account.id"
                  :disabled="managingId === account.id"
                  @click="selectAccount(account)"
                >
                  {{ managingId === account.id ? 'Membuka…' : 'Kelola' }}
                </UiButton>
                <span v-else class="st-table__muted" aria-label="Akun administrator"> — </span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-else class="accounts-view__hint">Belum ada akun staf terdaftar.</p>
    </section>

    <UiModal v-if="isCreateOpen" title="Tambah Staff" @close="closeCreate">
      <p class="accounts-view__hint">
        Isi identitas, role, dan kata sandi yang akan digunakan staf untuk login.
      </p>
      <p v-if="createError" class="st-alert st-alert--error" role="alert">{{ createError }}</p>
      <form id="create-staff-form" class="master-data__form" @submit.prevent="submitForm">
        <label>
          Nama lengkap
          <UiInput
            v-model="form.full_name"
            required
            minlength="2"
            maxlength="200"
            autocomplete="name"
          />
        </label>
        <label>
          Email login
          <UiInput
            v-model="form.email"
            type="email"
            required
            maxlength="320"
            autocomplete="email"
          />
        </label>
        <label>
          Role
          <UiSelect v-model="form.role" required>
            <option value="TEACHER">Guru</option>
            <option value="LABORANT">Laboran</option>
          </UiSelect>
        </label>
        <label>
          Kata sandi (minimal 8 karakter, tanpa spasi)
          <UiInput
            v-model="form.password"
            type="password"
            required
            minlength="8"
            maxlength="200"
            pattern="\S{8,200}"
            title="Kata sandi minimal 8 karakter tanpa spasi."
            autocomplete="new-password"
          />
        </label>
      </form>
      <template #footer>
        <UiButton variant="secondary" type="button" :disabled="isSaving" @click="closeCreate">
          Batal
        </UiButton>
        <UiButton variant="primary" type="submit" form="create-staff-form" :disabled="isSaving">
          {{ isSaving ? 'Membuat akun…' : 'Buat akun' }}
        </UiButton>
      </template>
    </UiModal>

    <UiDrawer
      v-if="selectedDetail"
      :title="`${selectedDetail.full_name} · ${selectedDetail.email}`"
      :subtitle="manageSubtitle(selectedDetail)"
      data-testid="account-manage"
      @close="closeManage"
    >
      <div class="accounts-view__manage">
        <p v-if="detailError" class="master-data__alert" role="alert">{{ detailError }}</p>
        <p
          v-if="permissionGrantsLoadFailed"
          class="st-alert st-alert--error"
          role="alert"
          data-testid="permission-grants-load-error"
        >
          Hak akses belum berhasil dimuat. Bagian izin disembunyikan agar akses bawaan tidak
          ditampilkan secara keliru.
        </p>
        <p v-if="manageMessage" class="master-data__success" role="status">{{ manageMessage }}</p>
        <section class="accounts-view__section" aria-labelledby="account-settings-heading">
          <div class="accounts-view__summary" aria-label="Status akun">
            <UiBadge tone="info">{{
              selectedDetail.roles.map(accountRoleLabel).join(', ')
            }}</UiBadge>
            <UiBadge :tone="selectedDetail.is_active ? 'present' : 'neutral'">
              {{ selectedDetail.is_active ? 'Aktif' : 'Nonaktif' }}
            </UiBadge>
            <UiBadge v-if="isTeacherAccount(selectedDetail)" tone="neutral">
              {{ editOpeningMode === 'automatic' ? 'Buka otomatis' : 'Sesi manual' }}
            </UiBadge>
          </div>
          <h3 id="account-settings-heading">Pengaturan akun</h3>
          <form class="master-data__form" @submit.prevent="saveAccount">
            <label>
              Nama lengkap
              <UiInput v-model="editName" minlength="2" maxlength="200" required />
            </label>
            <label>
              Status akun
              <select v-model="editActive">
                <option :value="true">Aktif</option>
                <option :value="false">Nonaktif</option>
              </select>
            </label>
            <label v-if="!editActive">
              Alasan penonaktifan (wajib dicatat audit)
              <UiInput
                v-model="editDeactivationReason"
                maxlength="500"
                placeholder="mis. mutasi / masa tugas selesai"
              />
            </label>
            <label v-if="!isAdminAccount(selectedDetail)">
              Role akun
              <UiSelect v-model="editRole" data-testid="edit-role">
                <option value="TEACHER">Guru</option>
                <option value="LABORANT">Laboran</option>
              </UiSelect>
            </label>
            <p v-if="!isAdminAccount(selectedDetail)" class="accounts-view__hint">
              Perubahan role melepas penugasan dan izin yang tidak sesuai; perubahan dicatat pada
              audit.
            </p>
            <label v-if="isTeacherAccount(selectedDetail)">
              Mode pembukaan sesi (guru)
              <UiSelect v-model="editOpeningMode">
                <option value="manual">Saya membuka sesi sendiri</option>
                <option value="automatic">Sesi saya dibuka otomatis sesuai jadwal</option>
              </UiSelect>
            </label>
            <p v-if="isTeacherAccount(selectedDetail)" class="accounts-view__hint">
              Mode otomatis hanya berlaku untuk jadwal milik guru ini.
            </p>
            <div class="master-data__form-actions">
              <UiButton variant="primary" type="submit">Simpan perubahan</UiButton>
            </div>
          </form>
        </section>

        <section class="accounts-view__section" aria-labelledby="account-password-heading">
          <div class="accounts-view__section-heading">
            <div>
              <h3 id="account-password-heading">Kata sandi</h3>
              <p class="accounts-view__hint">Sesi aktif staf dicabut setelah sandi diganti.</p>
            </div>
            <UiButton
              v-if="!showPasswordForm"
              variant="secondary"
              type="button"
              data-testid="open-password-form"
              @click="openPasswordForm"
            >
              Ganti kata sandi
            </UiButton>
          </div>
          <form
            v-if="showPasswordForm"
            class="master-data__form accounts-view__password-form"
            @submit.prevent="doSetPassword"
          >
            <label>
              Kata sandi baru (min. 8 karakter, tanpa spasi)
              <UiInput
                v-model="newPassword"
                type="password"
                required
                minlength="8"
                maxlength="200"
                autocomplete="new-password"
                data-testid="set-password-input"
              />
            </label>
            <div class="master-data__form-actions">
              <UiButton
                variant="secondary"
                type="button"
                :disabled="isSettingPassword"
                @click="closePasswordForm"
              >
                Batal
              </UiButton>
              <UiButton
                variant="primary"
                type="submit"
                :disabled="isSettingPassword || newPassword.length < 8 || /\s/.test(newPassword)"
                data-testid="set-password-submit"
              >
                {{ isSettingPassword ? 'Menyimpan…' : 'Simpan kata sandi' }}
              </UiButton>
            </div>
          </form>
          <p v-if="setPasswordMessage" class="master-data__success" role="status">
            {{ setPasswordMessage }}
          </p>
          <p v-if="setPasswordError" class="master-data__alert" role="alert">
            {{ setPasswordError }}
          </p>
        </section>
        <template v-if="isTeacherAccount(selectedDetail)">
          <section class="accounts-view__section" aria-labelledby="teacher-assignments-heading">
            <h3 id="teacher-assignments-heading">Penugasan guru</h3>
            <p class="accounts-view__hint">Akses guru hanya mencakup kelas yang ditugaskan.</p>
            <ul class="accounts-view__assignments">
              <li v-for="t in teacherAssignments" :key="t.class_id">
                <span
                  >{{ t.code }} - {{ t.name
                  }}<small v-if="t.is_substitute"> · Pengganti</small></span
                >
                <UiButton variant="text" type="button" @click="unassignTeacherClass(t.class_id)">
                  Lepas
                </UiButton>
              </li>
              <li v-if="!teacherAssignments.length" class="accounts-view__empty">
                Belum ada penugasan kelas.
              </li>
            </ul>
            <form class="master-data__form" @submit.prevent="assignTeacherClass">
              <label>
                Tambah penugasan kelas
                <UiSelect v-model="selectedTeacherClass" aria-label="Pilih kelas untuk guru">
                  <option value="">Pilih kelas…</option>
                  <option v-for="c in availableTeacherClasses" :key="c.id" :value="c.id">
                    {{ c.code }} - {{ c.name }}
                  </option>
                </UiSelect>
              </label>
              <div class="master-data__form-actions">
                <UiButton variant="secondary" type="submit" :disabled="!selectedTeacherClass">
                  Tugaskan
                </UiButton>
              </div>
            </form>
          </section>
        </template>
        <template v-if="isLaborantAccount(selectedDetail)">
          <section class="accounts-view__section" aria-labelledby="laborant-assignments-heading">
            <h3 id="laborant-assignments-heading">Penugasan laboran</h3>
            <p class="accounts-view__hint">
              Data yang dibaca laboran dibatasi pada laboratorium yang ditugaskan.
            </p>
            <ul class="accounts-view__assignments">
              <li v-for="a in assignments" :key="a.laboratory_id">
                <span>{{ a.code }} - {{ a.name }}</span>
                <UiButton variant="text" type="button" @click="unassignLab(a.laboratory_id)">
                  Lepas
                </UiButton>
              </li>
              <li v-if="!assignments.length" class="accounts-view__empty">
                Belum ada penugasan laboratorium.
              </li>
            </ul>
            <label class="accounts-view__field">
              Tambah laboratorium
              <UiSelect
                aria-label="Pilih lab untuk laboran"
                @change="
                  (e: Event) => assignLab((e.target as HTMLSelectElement | null)?.value ?? '')
                "
              >
                <option value="">Pilih laboratorium…</option>
                <option v-for="lab in laboratories" :key="lab.id" :value="lab.id">
                  {{ lab.code }} - {{ lab.name }}
                </option>
              </UiSelect>
            </label>
          </section>
        </template>
        <template
          v-if="
            (isLaborantAccount(selectedDetail) || isTeacherAccount(selectedDetail)) &&
            !permissionGrantsLoadFailed
          "
        >
          <section class="accounts-view__section" aria-labelledby="account-permissions-heading">
            <h3 id="account-permissions-heading">Akses akun</h3>
            <div class="accounts-view__permission-summary">
              <h4>Akses bawaan {{ isTeacherAccount(selectedDetail) ? 'guru' : 'laboran' }}</h4>
              <p class="accounts-view__hint">Otomatis aktif dari role.</p>
              <div class="accounts-view__roles" data-testid="base-permissions">
                <UiBadge
                  v-for="permission in grants.base_permissions"
                  :key="permission"
                  tone="info"
                >
                  {{ PERMISSION_META[permission]?.label ?? permission }}
                </UiBadge>
                <span v-if="!grants.base_permissions.length" class="accounts-view__hint">
                  Tidak ada akses bawaan.
                </span>
              </div>
            </div>
            <div class="accounts-view__permission-extra">
              <h4>Hak akses tambahan</h4>
              <p class="accounts-view__hint">
                Tambahkan izin di luar akses bawaan role bila diperlukan.
              </p>
            </div>
            <div class="accounts-view__permission-groups">
              <div
                v-for="group in grantGroups(grants.grantable)"
                :key="group.group"
                class="accounts-view__permission-group"
              >
                <div class="accounts-view__permission-group-heading">
                  <h4>{{ group.group }}</h4>
                  <label class="accounts-view__select-all">
                    <input
                      type="checkbox"
                      :checked="allOperationalSelected(group.perms)"
                      @change="
                        (e) =>
                          toggleAllOperational(group.perms, (e.target as HTMLInputElement).checked)
                      "
                    />
                    Pilih semua
                  </label>
                </div>
                <ul class="accounts-view__permission-list">
                  <li
                    v-for="perm in group.perms"
                    :key="perm"
                    class="accounts-view__permission-item"
                  >
                    <label>
                      <input
                        type="checkbox"
                        :checked="grants.extra_permissions.includes(perm)"
                        @change="(e) => toggleGrant(perm, (e.target as HTMLInputElement).checked)"
                      />
                      <span>{{ PERMISSION_META[perm]?.label ?? perm }}</span>
                    </label>
                    <details class="accounts-view__permission-details">
                      <summary>Detail izin</summary>
                      <small class="accounts-view__hint">
                        {{ PERMISSION_META[perm]?.hint ?? '' }}
                        <span v-if="PERMISSION_META[perm]?.needs">
                          Butuh: {{ PERMISSION_META[perm]?.needs }}.
                          <span
                            v-if="grants.base_permissions.includes(PERMISSION_META[perm].needs)"
                          >
                            Tersedia dari akses bawaan role.
                          </span>
                        </span>
                      </small>
                    </details>
                  </li>
                </ul>
              </div>
            </div>
            <p class="accounts-view__hint" data-testid="additional-permissions-summary">
              Hak akses tambahan aktif: {{ permissionLabels(activeAdditionalPermissions) }}
            </p>
            <details class="accounts-view__access-help" data-testid="grant-impact">
              <summary>Tentang hak akses</summary>
              <p class="accounts-view__hint">
                {{
                  isTeacherAccount(selectedDetail)
                    ? 'Koreksi sesi tertutup memerlukan alasan dan tercatat pada audit.'
                    : 'Izin mengatur menu operasional yang dapat dibuka laboran. Data lab tetap mengikuti penugasan laboratorium.'
                }}
              </p>
            </details>
          </section>
        </template>
      </div>
    </UiDrawer>
  </div>
</template>
