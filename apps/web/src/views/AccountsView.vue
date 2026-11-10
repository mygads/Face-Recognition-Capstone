<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { UiButton, UiInput, UiPageHeader, UiSelect } from '../components/ui'
import {
  addClassLaboratory,
  addLaborantAssignment,
  addTeacherAssignment,
  ApiError,
  createStaffAccount,
  getStaffAccount,
  grantOptionalPermission,
  listAccounts,
  listClasses,
  listClassLaboratories,
  listLaboratories,
  listLaborantAssignments,
  listPermissionGrants,
  listTeacherAssignments,
  removeClassLaboratory,
  removeLaborantAssignment,
  removeTeacherAssignment,
  resetStaffPassword,
  revokeOptionalPermission,
  updateStaffAccount,
  type Account,
  type AccountDetail,
  type Laboratory,
  type SchoolClass,
  type StaffAccountCreate,
  type StaffAccountCreated,
} from '../api/client'

const form = ref<StaffAccountCreate>({
  full_name: '',
  email: '',
  role: 'TEACHER',
})
const createdAccount = ref<StaffAccountCreated | null>(null)
const isSaving = ref(false)
const errorMessage = ref<string | null>(null)
const copyMessage = ref<string | null>(null)
const accounts = ref<Account[]>([])
const accountsTotal = ref(0)
const isLoadingAccounts = ref(false)
const accountsError = ref<string | null>(null)
const selectedDetail = ref<AccountDetail | null>(null)
const detailError = ref<string | null>(null)
const laboratories = ref<Laboratory[]>([])
const assignments = ref<{ laboratory_id: string; code: string | null; name: string | null }[]>([])
const grants = ref<{ extra_permissions: string[]; grantable: string[] }>({
  extra_permissions: [],
  grantable: [],
})

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

async function toggleAllOperational(permList: string[], enabled: boolean): Promise<void> {
  for (const perm of permList) {
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
const classLaboratories = ref<{ class_id: string; laboratory_id: string }[]>([])
const selectedTeacherClass = ref('')
const selectedClassLabClass = ref('')
const selectedClassLabLab = ref('')
const resetResult = ref<string | null>(null)
const manageMessage = ref<string | null>(null)

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
  detailError.value = null
  manageMessage.value = null
  resetResult.value = null
  try {
    selectedDetail.value = await getStaffAccount(account.id)
    editName.value = selectedDetail.value.full_name
    editActive.value = selectedDetail.value.is_active
    editOpeningMode.value =
      selectedDetail.value.opening_mode === 'automatic' ? 'automatic' : 'manual'
    editRole.value = selectedDetail.value.roles.includes('TEACHER') ? 'TEACHER' : 'LABORANT'
    const [assignRes, grantRes, teacherRes] = await Promise.all([
      listLaborantAssignments(account.id).catch(() => ({ items: [] })),
      listPermissionGrants(account.id).catch(() => ({ extra_permissions: [], grantable: [] })),
      listTeacherAssignments(account.id).catch(() => ({ items: [] })),
    ])
    assignments.value = (assignRes as { items: typeof assignments.value }).items
    grants.value = grantRes as typeof grants.value
    teacherAssignments.value = (teacherRes as { items: typeof teacherAssignments.value }).items
    editDeactivationReason.value = ''
  } catch (error) {
    detailError.value = formatError(error)
  }
}

async function saveAccount(): Promise<void> {
  if (!selectedDetail.value) return
  try {
    const currentRole = selectedDetail.value.roles.includes('TEACHER') ? 'TEACHER' : 'LABORANT'
    selectedDetail.value = await updateStaffAccount(selectedDetail.value.id, {
      full_name: editName.value.trim() || undefined,
      is_active: editActive.value,
      opening_mode: editOpeningMode.value,
      role: editRole.value === currentRole ? undefined : editRole.value,
      deactivation_reason:
        editActive.value || !editDeactivationReason.value.trim()
          ? undefined
          : editDeactivationReason.value.trim(),
    })
    manageMessage.value =
      'Akun diperbarui: aktif/nonaktif, nama, mode pembukaan, role ' +
      '(ganti role melepas penugasan & izin yang tidak relevan).'
    void loadAccounts()
  } catch (error) {
    detailError.value = formatError(error)
  }
}

async function doReset(): Promise<void> {
  if (!selectedDetail.value) return
  try {
    const res = await resetStaffPassword(selectedDetail.value.id)
    resetResult.value = res.temporary_password
    manageMessage.value = 'Kata sandi direset. Berikan sandi sementara baru ke staf.'
  } catch (error) {
    detailError.value = formatError(error)
  }
}

async function toggleGrant(permission: string, enabled: boolean): Promise<void> {
  if (!selectedDetail.value) return
  try {
    if (enabled) await grantOptionalPermission(selectedDetail.value.id, permission)
    else await revokeOptionalPermission(selectedDetail.value.id, permission)
    const g = await listPermissionGrants(selectedDetail.value.id)
    grants.value = g
    manageMessage.value = 'Hak akses opsional diperbarui.'
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
    const [classPage, classLab] = await Promise.all([
      listClasses({ limit: 100, offset: 0 }),
      listClassLaboratories().catch(() => ({ items: [] })),
    ])
    schoolClasses.value = classPage.items
    classLaboratories.value = (classLab as { items: typeof classLaboratories.value }).items
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

async function addClassLabMapping(): Promise<void> {
  if (!selectedClassLabClass.value || !selectedClassLabLab.value) return
  try {
    await addClassLaboratory(selectedClassLabClass.value, selectedClassLabLab.value)
    const res = await listClassLaboratories()
    classLaboratories.value = res.items
    manageMessage.value = 'Relasi kelas–lab diperbarui.'
  } catch (error) {
    detailError.value = formatError(error)
  }
}

async function removeClassLabMapping(classId: string, labId: string): Promise<void> {
  try {
    await removeClassLaboratory(classId, labId)
    const res = await listClassLaboratories()
    classLaboratories.value = res.items
    manageMessage.value = 'Relasi kelas–lab diperbarui.'
  } catch (error) {
    detailError.value = formatError(error)
  }
}

function classNameOf(classId: string): string {
  return schoolClasses.value.find((c) => c.id === classId)?.name ?? classId
}

function labNameOf(labId: string): string {
  const lab = laboratories.value.find((l) => l.id === labId)
  return lab ? `${lab.code} - ${lab.name}` : labId
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
  errorMessage.value = null
  copyMessage.value = null
  createdAccount.value = null
  isSaving.value = true
  try {
    createdAccount.value = await createStaffAccount({
      full_name: form.value.full_name.trim(),
      email: form.value.email.trim(),
      role: form.value.role,
    })
    form.value = { full_name: '', email: '', role: form.value.role }
    void loadAccounts()
  } catch (error) {
    errorMessage.value = formatError(error)
  } finally {
    isSaving.value = false
  }
}

async function copyTemporaryPassword(): Promise<void> {
  if (!createdAccount.value) return
  try {
    await navigator.clipboard.writeText(createdAccount.value.temporary_password)
    copyMessage.value = 'Kata sandi sementara disalin.'
  } catch {
    copyMessage.value = 'Salin kata sandi dari kotak di atas secara manual.'
  }
}
</script>

<template>
  <div class="st-page" aria-label="Kelola akun staf">
    <UiPageHeader
      eyebrow="Administrasi"
      title="Kelola akun staf"
      description="Buat akun guru dan laboran. Akun baru wajib mengganti kata sandi sebelum memakai sistem."
    />

    <p v-if="errorMessage" class="st-alert st-alert--error" role="alert">{{ errorMessage }}</p>

    <section
      v-if="createdAccount"
      class="accounts-view__created master-data__success"
      aria-live="polite"
      data-testid="account-created"
    >
      <div>
        <h2>Akun berhasil dibuat</h2>
        <p>
          Berikan kata sandi sementara ini kepada {{ createdAccount.full_name }}. Kata sandi hanya
          tersedia pada layar ini dan harus diganti saat login pertama.
        </p>
      </div>
      <dl class="accounts-view__details">
        <div>
          <dt>Email</dt>
          <dd>{{ createdAccount.email }}</dd>
        </div>
        <div>
          <dt>Role</dt>
          <dd>{{ createdAccount.role === 'TEACHER' ? 'Guru' : 'Laboran' }}</dd>
        </div>
      </dl>
      <label class="accounts-view__password-label" for="temporary-password">
        Kata sandi sementara
      </label>
      <div class="accounts-view__password-row">
        <UiInput
          id="temporary-password"
          :value="createdAccount.temporary_password"
          type="text"
          readonly
          aria-label="Kata sandi sementara, hanya ditampilkan setelah akun dibuat"
          data-testid="temporary-password"
        />
        <UiButton variant="secondary" type="button" @click="copyTemporaryPassword">
          Salin
        </UiButton>
      </div>
      <p v-if="copyMessage" class="accounts-view__copy-message" role="status">
        {{ copyMessage }}
      </p>
    </section>

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
      <ul
        v-else-if="accounts.length"
        class="accounts-view__list st-list"
        data-testid="account-list"
      >
        <li v-for="account in accounts" :key="account.id" class="accounts-view__row">
          <div>
            <strong>{{ account.full_name }}</strong>
            <small>{{ account.email }}</small>
          </div>
          <span
            class="accounts-view__status"
            :class="account.is_active ? 'accounts-view__status--active' : ''"
          >
            {{ account.is_active ? 'Aktif' : 'Nonaktif' }}
          </span>
          <UiButton
            variant="secondary"
            type="button"
            :data-testid="'manage-' + account.id"
            @click="selectAccount(account)"
          >
            Kelola
          </UiButton>
        </li>
      </ul>
      <p v-else class="accounts-view__hint">Belum ada akun staf terdaftar.</p>
    </section>

    <section class="master-data__panel">
      <div class="master-data__panel-heading">
        <div>
          <p class="master-data__eyebrow">Akun internal</p>
          <h2>Buat akun guru atau laboran</h2>
        </div>
      </div>
      <p class="accounts-view__hint">
        Sistem membuat kata sandi sementara secara otomatis. Nilai itu tidak disimpan sebagai teks
        biasa dan tidak dapat ditampilkan ulang setelah panel ini ditutup.
      </p>
      <form class="master-data__form" @submit.prevent="submitForm">
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
        <div class="master-data__form-actions">
          <UiButton variant="primary" type="submit" :disabled="isSaving">
            {{ isSaving ? 'Membuat akun…' : 'Buat akun' }}
          </UiButton>
        </div>
      </form>
    </section>

    <section v-if="selectedDetail" class="master-data__panel" data-testid="account-manage">
      <div class="master-data__panel-heading">
        <div>
          <p class="master-data__eyebrow">Kelola staf</p>
          <h2>{{ selectedDetail.full_name }} · {{ selectedDetail.email }}</h2>
        </div>
      </div>
      <p v-if="detailError" class="master-data__alert" role="alert">{{ detailError }}</p>
      <p v-if="manageMessage" class="master-data__success" role="status">{{ manageMessage }}</p>
      <p class="accounts-view__hint">
        Role: {{ selectedDetail.roles.join(', ') }} · Status:
        {{ selectedDetail.is_active ? 'Aktif' : 'Nonaktif' }} · Mode buka:
        {{ selectedDetail.opening_mode }} · Dibuat: {{ selectedDetail.created_at }}
      </p>
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
        <label>
          Role akun
          <UiSelect v-model="editRole" data-testid="edit-role">
            <option value="TEACHER">Guru</option>
            <option value="LABORANT">Laboran</option>
          </UiSelect>
        </label>
        <p class="accounts-view__hint">
          Ganti role melepas penugasan &amp; izin yang tidak relevan (dicatat audit). Role admin
          tidak dapat diubah di sini.
        </p>
        <label>
          Mode pembukaan sesi (guru)
          <UiSelect v-model="editOpeningMode">
            <option value="manual">Saya membuka sesi sendiri</option>
            <option value="automatic">Sesi saya dibuka otomatis sesuai jadwal</option>
          </UiSelect>
        </label>
        <div class="master-data__form-actions">
          <UiButton variant="primary" type="submit">Simpan perubahan</UiButton>
          <UiButton variant="secondary" type="button" @click="doReset"> Reset kata sandi </UiButton>
        </div>
      </form>
      <p v-if="resetResult" class="master-data__success" role="status">
        Sandi sementara baru: <code>{{ resetResult }}</code>
      </p>
      <h3>Penugasan guru → kelas</h3>
      <p class="accounts-view__hint">
        Hanya kelas yang ditugaskan yang bisa dibaca guru di Kelas Saya, laporan, dan EWS.
      </p>
      <ul>
        <li v-for="t in teacherAssignments" :key="t.class_id">
          {{ t.code }} - {{ t.name }}
          <small v-if="t.is_substitute">(pengganti)</small>
          <UiButton variant="text" type="button" @click="unassignTeacherClass(t.class_id)">
            Lepas
          </UiButton>
        </li>
        <li v-if="!teacherAssignments.length" class="accounts-view__hint">
          Belum ada penugasan kelas.
        </li>
      </ul>
      <form class="master-data__form" @submit.prevent="assignTeacherClass">
        <label>
          Tambah penugasan kelas
          <UiSelect v-model="selectedTeacherClass" aria-label="Pilih kelas untuk guru">
            <option value="">Pilih kelas…</option>
            <option v-for="c in schoolClasses" :key="c.id" :value="c.id">
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
      <h3>Relasi kelas ↔ laboratorium (cakupan enrollment laboran)</h3>
      <p class="accounts-view__hint">
        Laboran hanya melihat enrollment kelas yang dilayani lab penugasannya.
      </p>
      <ul>
        <li v-for="m in classLaboratories" :key="`${m.class_id}-${m.laboratory_id}`">
          {{ classNameOf(m.class_id) }} ↔ {{ labNameOf(m.laboratory_id) }}
          <UiButton
            variant="text"
            type="button"
            @click="removeClassLabMapping(m.class_id, m.laboratory_id)"
          >
            Lepas
          </UiButton>
        </li>
        <li v-if="!classLaboratories.length" class="accounts-view__hint">
          Belum ada relasi kelas–lab.
        </li>
      </ul>
      <form class="master-data__form" @submit.prevent="addClassLabMapping">
        <label>
          Kelas
          <UiSelect v-model="selectedClassLabClass" aria-label="Pilih kelas untuk relasi lab">
            <option value="">Pilih kelas…</option>
            <option v-for="c in schoolClasses" :key="c.id" :value="c.id">
              {{ c.code }} - {{ c.name }}
            </option>
          </UiSelect>
        </label>
        <label>
          Laboratorium
          <UiSelect v-model="selectedClassLabLab" aria-label="Pilih lab untuk relasi kelas">
            <option value="">Pilih lab…</option>
            <option v-for="lab in laboratories" :key="lab.id" :value="lab.id">
              {{ lab.code }} - {{ lab.name }}
            </option>
          </UiSelect>
        </label>
        <div class="master-data__form-actions">
          <UiButton
            variant="secondary"
            type="submit"
            :disabled="!selectedClassLabClass || !selectedClassLabLab"
          >
            Tautkan
          </UiButton>
        </div>
      </form>
      <h3>Penugasan laboran → lab</h3>
      <ul>
        <li v-for="a in assignments" :key="a.laboratory_id">
          {{ a.code }} - {{ a.name }}
          <UiButton variant="text" type="button" @click="unassignLab(a.laboratory_id)">
            Lepas
          </UiButton>
        </li>
      </ul>
      <form @submit.prevent="">
        <label>
          Tambah penugasan lab
          <UiSelect
            aria-label="Pilih lab untuk laboran"
            @change="(e: Event) => assignLab((e.target as HTMLSelectElement | null)?.value ?? '')"
          >
            <option value="">Pilih lab…</option>
            <option v-for="lab in laboratories" :key="lab.id" :value="lab.id">
              {{ lab.code }} - {{ lab.name }}
            </option>
          </UiSelect>
        </label>
      </form>
      <h3>Hak akses opsional laboran (checklist)</h3>
      <p class="accounts-view__hint">
        Default laboran: perangkat, preview kamera, pendaftaran wajah. Centang untuk memberi akses
        guru (jadwal/sesi/koreksi/laporan/EWS). Laboran full ≈ admin kecuali buat staf &amp; AI.
      </p>
      <div v-for="group in grantGroups(grants.grantable)" :key="group.group">
        <h4>{{ group.group }}</h4>
        <label>
          <input
            type="checkbox"
            :checked="allOperationalSelected(group.perms)"
            @change="
              (e) => toggleAllOperational(group.perms, (e.target as HTMLInputElement).checked)
            "
          />
          Pilih semua {{ group.group }}
        </label>
        <ul>
          <li v-for="perm in group.perms" :key="perm">
            <label>
              <input
                type="checkbox"
                :checked="grants.extra_permissions.includes(perm)"
                @change="(e) => toggleGrant(perm, (e.target as HTMLInputElement).checked)"
              />
              {{ PERMISSION_META[perm]?.label ?? perm }}
            </label>
            <small class="accounts-view__hint">
              {{ PERMISSION_META[perm]?.hint ?? '' }}
              <span v-if="PERMISSION_META[perm]?.needs">
                Butuh: {{ PERMISSION_META[perm]?.needs }}.
              </span>
            </small>
          </li>
        </ul>
      </div>
      <p class="accounts-view__hint">
        Aktif saat ini: {{ grants.extra_permissions.join(', ') || '-' }}
      </p>
      <p class="accounts-view__hint" data-testid="grant-impact">
        Dampak menu bila disimpan: laboran dasar hanya melihat workspace teknis. Setiap izin yang
        dicentang membuka menu terkait (Jadwal → Sesi → Koreksi → Laporan/EWS). Tanpa lab yang
        ditugaskan, data lab tetap kosong (“Belum ada penugasan laboratorium”).
      </p>
    </section>
  </div>
</template>
