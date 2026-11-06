<script setup lang="ts">
import { onMounted, ref } from 'vue'
import PageHeader from '../components/PageHeader.vue'
import {
  addLaborantAssignment,
  ApiError,
  createStaffAccount,
  getStaffAccount,
  grantOptionalPermission,
  listAccounts,
  listLaboratories,
  listLaborantAssignments,
  listPermissionGrants,
  removeLaborantAssignment,
  resetStaffPassword,
  revokeOptionalPermission,
  updateStaffAccount,
  type Account,
  type AccountDetail,
  type Laboratory,
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
const editName = ref('')
const editActive = ref(true)
const editOpeningMode = ref<'manual' | 'automatic'>('manual')
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
    const [assignRes, grantRes] = await Promise.all([
      listLaborantAssignments(account.id).catch(() => ({ items: [] })),
      listPermissionGrants(account.id).catch(() => ({ extra_permissions: [], grantable: [] })),
    ])
    assignments.value = (assignRes as { items: typeof assignments.value }).items
    grants.value = grantRes as typeof grants.value
  } catch (error) {
    detailError.value = formatError(error)
  }
}

async function saveAccount(): Promise<void> {
  if (!selectedDetail.value) return
  try {
    selectedDetail.value = await updateStaffAccount(selectedDetail.value.id, {
      full_name: editName.value.trim() || undefined,
      is_active: editActive.value,
      opening_mode: editOpeningMode.value,
    })
    manageMessage.value = 'Akun diperbarui: aktif/nonaktif, nama, mode pembukaan.'
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

onMounted(() => {
  void loadAccounts()
  void loadLabs()
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
  <section class="accounts-view" aria-label="Kelola akun staf">
    <PageHeader
      eyebrow="Administrasi"
      title="Kelola akun staf"
      description="Buat akun guru dan laboran. Akun baru wajib mengganti kata sandi sebelum memakai sistem."
    />

    <p v-if="errorMessage" class="master-data__alert" role="alert">{{ errorMessage }}</p>

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
        <input
          id="temporary-password"
          :value="createdAccount.temporary_password"
          type="text"
          readonly
          aria-label="Kata sandi sementara, hanya ditampilkan setelah akun dibuat"
          data-testid="temporary-password"
        />
        <button class="button button--secondary" type="button" @click="copyTemporaryPassword">
          Salin
        </button>
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
        <button
          class="button button--secondary"
          type="button"
          :disabled="isLoadingAccounts"
          @click="loadAccounts"
        >
          {{ isLoadingAccounts ? 'Memuat…' : 'Muat ulang' }}
        </button>
      </div>
      <p v-if="accountsError" class="master-data__alert" role="alert">{{ accountsError }}</p>
      <p v-else-if="isLoadingAccounts" class="accounts-view__hint">Memuat daftar akun…</p>
      <p
        v-else-if="accounts.length && accounts.length < accountsTotal"
        class="accounts-view__hint"
        role="status"
      >
        Menampilkan {{ accounts.length }} dari {{ accountsTotal }} akun (100 terbaru). Gunakan
        filter/paginasi API untuk sisanya.
      </p>
      <ul v-else-if="accounts.length" class="accounts-view__list" data-testid="account-list">
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
          <button
            class="button button--secondary"
            type="button"
            :data-testid="'manage-' + account.id"
            @click="selectAccount(account)"
          >
            Kelola
          </button>
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
          <input
            v-model="form.full_name"
            required
            minlength="2"
            maxlength="200"
            autocomplete="name"
          />
        </label>
        <label>
          Email login
          <input v-model="form.email" type="email" required maxlength="320" autocomplete="email" />
        </label>
        <label>
          Role
          <select v-model="form.role" required>
            <option value="TEACHER">Guru</option>
            <option value="LABORANT">Laboran</option>
          </select>
        </label>
        <div class="master-data__form-actions">
          <button class="button button--primary" type="submit" :disabled="isSaving">
            {{ isSaving ? 'Membuat akun…' : 'Buat akun' }}
          </button>
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
          <input v-model="editName" minlength="2" maxlength="200" required />
        </label>
        <label>
          Status akun
          <select v-model="editActive">
            <option :value="true">Aktif</option>
            <option :value="false">Nonaktif</option>
          </select>
        </label>
        <label>
          Mode pembukaan sesi (guru)
          <select v-model="editOpeningMode">
            <option value="manual">Saya membuka sesi sendiri</option>
            <option value="automatic">Sesi saya dibuka otomatis sesuai jadwal</option>
          </select>
        </label>
        <div class="master-data__form-actions">
          <button class="button button--primary" type="submit">Simpan perubahan</button>
          <button class="button button--secondary" type="button" @click="doReset">
            Reset kata sandi
          </button>
        </div>
      </form>
      <p v-if="resetResult" class="master-data__success" role="status">
        Sandi sementara baru: <code>{{ resetResult }}</code>
      </p>
      <h3>Penugasan laboran → lab</h3>
      <ul>
        <li v-for="a in assignments" :key="a.laboratory_id">
          {{ a.code }} — {{ a.name }}
          <button class="button button--text" type="button" @click="unassignLab(a.laboratory_id)">
            Lepas
          </button>
        </li>
      </ul>
      <form @submit.prevent="">
        <label>
          Tambah penugasan lab
          <select
            aria-label="Pilih lab untuk laboran"
            @change="(e) => assignLab((e.target as HTMLSelectElement).value)"
          >
            <option value="">Pilih lab…</option>
            <option v-for="lab in laboratories" :key="lab.id" :value="lab.id">
              {{ lab.code }} — {{ lab.name }}
            </option>
          </select>
        </label>
      </form>
      <h3>Hak akses opsional laboran (checklist)</h3>
      <p class="accounts-view__hint">
        Default laboran: perangkat, preview kamera, pendaftaran wajah. Centang untuk memberi akses
        guru (jadwal/sesi/koreksi/laporan/EWS). Laboran full ≈ admin kecuali buat staf &amp; AI.
      </p>
      <ul>
        <li v-for="perm in grants.grantable" :key="perm">
          <label>
            <input
              type="checkbox"
              :checked="grants.extra_permissions.includes(perm)"
              @change="(e) => toggleGrant(perm, (e.target as HTMLInputElement).checked)"
            />
            {{ perm }}
          </label>
        </li>
      </ul>
      <p class="accounts-view__hint">
        Aktif saat ini: {{ grants.extra_permissions.join(', ') || '—' }}
      </p>
    </section>
  </section>
</template>
