<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useAuthStore } from '../stores/auth'
import {
  ApiError,
  createClass,
  createLaboratory,
  createStudent,
  commitStudentImport,
  enrollStudent,
  getClass,
  getLaboratory,
  getStudent,
  listClasses,
  listLaboratories,
  listStudents,
  previewStudentImport,
  removeStudentFromClass,
  updateClass,
  updateLaboratory,
  updateStudent,
  type ClassDetails,
  type Laboratory,
  type SchoolClass,
  type Student,
  type StudentDetails,
  type StudentImportPreview,
} from '../api/client'

type MasterTab = 'students' | 'classes' | 'laboratories'
type MasterRow = Student | SchoolClass | Laboratory
type FormState = Record<string, string | number | boolean>

const auth = useAuthStore()
const canManage = computed(() => auth.account?.roles.includes('ADMIN') ?? false)
const tab = ref<MasterTab>('students')
const tabs: { id: MasterTab; label: string }[] = [
  { id: 'students', label: 'Siswa' },
  { id: 'classes', label: 'Kelas' },
  { id: 'laboratories', label: 'Laboratorium' },
]
const rows = ref<MasterRow[]>([])
const total = ref(0)
const page = ref(0)
const pageSize = 10
const searchText = ref('')
const search = ref('')
const isLoading = ref(false)
const errorMessage = ref<string | null>(null)
const formError = ref<string | null>(null)
const details = ref<StudentDetails | ClassDetails | Laboratory | null>(null)
const detailStudents = ref<Student[]>([])
const studentToEnroll = ref('')
const isDetailsLoading = ref(false)
const isFormOpen = ref(false)
const editingId = ref<string | null>(null)
const form = ref<FormState>({})
const isImportOpen = ref(false)
const isImportLoading = ref(false)
const isImportCommitting = ref(false)
const importFile = ref<File | null>(null)
const importMapping = ref({
  student_number_column: 'NIS',
  full_name_column: 'Nama',
  class_code_column: 'Kelas',
})
const importPreview = ref<StudentImportPreview | null>(null)
const importError = ref<string | null>(null)
const importSuccess = ref<string | null>(null)

const columns = computed(() => {
  if (tab.value === 'students') return ['NIS/NISN', 'Nama', 'Status']
  if (tab.value === 'classes') return ['Kode', 'Nama kelas', 'Tingkat', 'Tahun ajaran', 'Status']
  return ['Kode', 'Nama laboratorium', 'Lokasi', 'Status']
})

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))
const detailTitle = computed(() => {
  if (!details.value) return ''
  if ('student_number' in details.value) return details.value.full_name
  if ('grade' in details.value) return `${details.value.name} · ${details.value.academic_year}`
  return details.value.name
})

function displayValues(row: MasterRow): (string | number)[] {
  if ('student_number' in row) {
    return [row.student_number, row.full_name, row.is_active ? 'Aktif' : 'Nonaktif']
  }
  if ('grade' in row) {
    return [row.code, row.name, row.grade, row.academic_year, row.is_active ? 'Aktif' : 'Nonaktif']
  }
  return [row.code, row.name, row.location ?? '—', row.is_active ? 'Aktif' : 'Nonaktif']
}

function formatError(error: unknown): string {
  if (error instanceof ApiError) {
    const details = error.details?.map((item) => `${item.field}: ${item.message}`)
    return details?.length ? details.join(' · ') : error.message
  }
  return 'Permintaan tidak dapat diproses. Coba lagi.'
}

async function loadRows(): Promise<void> {
  isLoading.value = true
  errorMessage.value = null
  try {
    const query = {
      limit: pageSize,
      offset: page.value * pageSize,
      search: search.value || undefined,
    }
    const result =
      tab.value === 'students'
        ? await listStudents(query)
        : tab.value === 'classes'
          ? await listClasses(query)
          : await listLaboratories(query)
    rows.value = result.items
    total.value = result.pagination.total
  } catch (error) {
    errorMessage.value = formatError(error)
  } finally {
    isLoading.value = false
  }
}

watch([tab, page], () => {
  details.value = null
  isFormOpen.value = false
  void loadRows()
})

onMounted(() => void loadRows())

function submitSearch(): void {
  const changedPage = page.value !== 0
  page.value = 0
  search.value = searchText.value.trim()
  if (!changedPage) void loadRows()
}

function setTab(nextTab: MasterTab): void {
  if (tab.value === nextTab) return
  tab.value = nextTab
  page.value = 0
  searchText.value = ''
  search.value = ''
}

function createDefaults(): FormState {
  if (tab.value === 'students') return { student_number: '', full_name: '', is_active: true }
  if (tab.value === 'classes') {
    return {
      code: '',
      name: '',
      grade: 10,
      academic_year: `${new Date().getFullYear()}-${new Date().getFullYear() + 1}`,
      is_active: true,
    }
  }
  return { code: '', name: '', location: '', is_active: true }
}

function openCreate(): void {
  editingId.value = null
  form.value = createDefaults()
  formError.value = null
  isFormOpen.value = true
}

function openImport(): void {
  isImportOpen.value = true
  importFile.value = null
  importPreview.value = null
  importError.value = null
  importSuccess.value = null
  importMapping.value = {
    student_number_column: 'NIS',
    full_name_column: 'Nama',
    class_code_column: 'Kelas',
  }
}

function handleImportFileChange(event: Event): void {
  const input = event.target
  importFile.value = input instanceof HTMLInputElement ? (input.files?.[0] ?? null) : null
  importPreview.value = null
  importError.value = null
}

async function previewImport(): Promise<void> {
  if (!importFile.value) {
    importError.value = 'Pilih file CSV atau XLSX terlebih dahulu.'
    return
  }
  isImportLoading.value = true
  importError.value = null
  importPreview.value = null
  try {
    importPreview.value = await previewStudentImport(importFile.value, importMapping.value)
  } catch (error) {
    importError.value = formatError(error)
  } finally {
    isImportLoading.value = false
  }
}

async function commitImport(): Promise<void> {
  if (!importFile.value || !importPreview.value?.can_commit) return
  isImportCommitting.value = true
  importError.value = null
  try {
    const result = await commitStudentImport(importFile.value, importMapping.value)
    importSuccess.value = `${result.imported_count} siswa berhasil diimpor bersama relasi kelasnya.`
    isImportOpen.value = false
    importPreview.value = null
    await loadRows()
  } catch (error) {
    importError.value = formatError(error)
  } finally {
    isImportCommitting.value = false
  }
}

function openEdit(row: MasterRow): void {
  editingId.value = row.id
  form.value = { ...row } as FormState
  formError.value = null
  isFormOpen.value = true
}

async function submitForm(): Promise<void> {
  formError.value = null
  try {
    if (tab.value === 'students') {
      const payload = {
        student_number: String(form.value.student_number ?? '').trim(),
        full_name: String(form.value.full_name ?? '').trim(),
      }
      if (editingId.value) {
        await updateStudent(editingId.value, {
          ...payload,
          is_active: Boolean(form.value.is_active),
        })
      } else {
        await createStudent(payload)
      }
    } else if (tab.value === 'classes') {
      const payload = {
        code: String(form.value.code ?? '').trim(),
        name: String(form.value.name ?? '').trim(),
        grade: Number(form.value.grade),
        academic_year: String(form.value.academic_year ?? '').trim(),
      }
      if (editingId.value) {
        await updateClass(editingId.value, { ...payload, is_active: Boolean(form.value.is_active) })
      } else {
        await createClass(payload)
      }
    } else {
      const payload = {
        code: String(form.value.code ?? '').trim(),
        name: String(form.value.name ?? '').trim(),
        location: String(form.value.location ?? '').trim() || null,
      }
      if (editingId.value) {
        await updateLaboratory(editingId.value, {
          ...payload,
          is_active: Boolean(form.value.is_active),
        })
      } else {
        await createLaboratory(payload)
      }
    }
    isFormOpen.value = false
    details.value = null
    await loadRows()
  } catch (error) {
    formError.value = formatError(error)
  }
}

async function openDetails(row: MasterRow): Promise<void> {
  details.value = null
  detailStudents.value = []
  studentToEnroll.value = ''
  errorMessage.value = null
  isDetailsLoading.value = true
  try {
    if ('student_number' in row) details.value = await getStudent(row.id)
    else if ('grade' in row) {
      const [classDetails, activeStudents] = await Promise.all([
        getClass(row.id),
        listStudents({ limit: 100, offset: 0, is_active: true }),
      ])
      details.value = classDetails
      detailStudents.value = activeStudents.items.filter(
        (student) => !classDetails.students.some((member) => member.id === student.id),
      )
    } else details.value = await getLaboratory(row.id)
  } catch (error) {
    errorMessage.value = formatError(error)
  } finally {
    isDetailsLoading.value = false
  }
}

async function enrollSelectedStudent(): Promise<void> {
  if (!studentToEnroll.value || !details.value || !('grade' in details.value)) return
  try {
    await enrollStudent(details.value.id, studentToEnroll.value)
    await openDetails(details.value)
    await loadRows()
  } catch (error) {
    errorMessage.value = formatError(error)
  }
}

async function removeStudent(studentId: string): Promise<void> {
  if (!details.value || !('grade' in details.value)) return
  try {
    await removeStudentFromClass(details.value.id, studentId)
    await openDetails(details.value)
  } catch (error) {
    errorMessage.value = formatError(error)
  }
}

function goToPage(nextPage: number): void {
  if (nextPage < 0 || nextPage >= totalPages.value || nextPage === page.value) return
  page.value = nextPage
}
</script>

<template>
  <section class="master-data" aria-label="Data master">
    <div class="master-data__tabs" role="tablist" aria-label="Jenis data master">
      <button
        v-for="item in tabs"
        :key="item.id"
        class="master-data__tab"
        :class="{ 'master-data__tab--active': tab === item.id }"
        role="tab"
        :aria-selected="tab === item.id"
        :data-testid="`tab-${item.id}`"
        @click="setTab(item.id)"
      >
        {{ item.label }}
      </button>
    </div>

    <div class="master-data__toolbar">
      <form class="master-data__search" role="search" @submit.prevent="submitSearch">
        <label class="visually-hidden" for="master-search"
          >Cari {{ tabs.find((item) => item.id === tab)?.label.toLowerCase() }}</label
        >
        <input
          id="master-search"
          v-model="searchText"
          type="search"
          placeholder="Cari nama atau kode"
        />
        <button class="button button--secondary" type="submit">Cari</button>
      </form>
      <button
        v-if="canManage"
        class="button button--primary"
        data-testid="create-record"
        @click="openCreate"
      >
        Tambah {{ tabs.find((item) => item.id === tab)?.label.toLowerCase() }}
      </button>
      <button
        v-if="canManage && tab === 'students'"
        class="button button--secondary"
        data-testid="open-student-import"
        @click="openImport"
      >
        Import CSV/XLSX
      </button>
    </div>

    <p v-if="errorMessage" class="master-data__alert" role="alert">{{ errorMessage }}</p>
    <p v-if="importSuccess" class="master-data__success" role="status">{{ importSuccess }}</p>

    <section v-if="isImportOpen" class="master-data__panel" aria-labelledby="import-title">
      <div class="master-data__panel-heading">
        <div>
          <p class="master-data__eyebrow">Siswa</p>
          <h2 id="import-title">Preview import CSV/XLSX</h2>
        </div>
        <button class="button button--text" type="button" @click="isImportOpen = false">
          Tutup
        </button>
      </div>
      <p class="master-data__muted">
        Pilih header file untuk setiap kolom. Baris dengan NIS/NISN duplikat, nama kosong, atau
        kelas yang tidak dikenal akan ditandai sebelum commit.
      </p>
      <form class="master-data__form" @submit.prevent="previewImport">
        <label class="master-data__file-field"
          >File CSV atau XLSX
          <input type="file" accept=".csv,.xlsx" required @change="handleImportFileChange" />
        </label>
        <label
          >Header kolom NIS/NISN<input
            v-model="importMapping.student_number_column"
            required
            maxlength="128"
        /></label>
        <label
          >Header kolom nama<input
            v-model="importMapping.full_name_column"
            required
            maxlength="128"
        /></label>
        <label
          >Header kolom kode kelas<input
            v-model="importMapping.class_code_column"
            required
            maxlength="128"
        /></label>
        <div class="master-data__form-actions">
          <button class="button button--primary" type="submit" :disabled="isImportLoading">
            {{ isImportLoading ? 'Memeriksa file…' : 'Preview data' }}
          </button>
        </div>
      </form>
      <p v-if="importError" class="master-data__alert master-data__alert--form" role="alert">
        {{ importError }}
      </p>
      <template v-if="importPreview">
        <div class="master-data__import-summary" data-testid="import-summary">
          <span>{{ importPreview.total_rows }} baris</span>
          <span class="master-data__import-valid">{{ importPreview.valid_rows }} valid</span>
          <span class="master-data__import-invalid"
            >{{ importPreview.invalid_rows }} perlu diperbaiki</span
          >
        </div>
        <div class="master-data__table-wrap master-data__preview-table-wrap">
          <table class="master-data__table">
            <thead>
              <tr>
                <th scope="col">Baris</th>
                <th scope="col">NIS/NISN</th>
                <th scope="col">Nama</th>
                <th scope="col">Kelas</th>
                <th scope="col">Status</th>
                <th scope="col">Validasi</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="row in importPreview.rows"
                :key="row.row_number"
                :data-testid="`import-row-${row.row_number}`"
              >
                <td data-label="Baris">{{ row.row_number }}</td>
                <td data-label="NIS/NISN">{{ row.student_number || '—' }}</td>
                <td data-label="Nama">{{ row.full_name || '—' }}</td>
                <td data-label="Kelas">{{ row.class_code || '—' }}</td>
                <td data-label="Status">
                  <span
                    class="status-badge"
                    :class="row.valid ? 'status-badge--active' : 'status-badge--inactive'"
                    >{{ row.valid ? 'Valid' : 'Tidak valid' }}</span
                  >
                </td>
                <td data-label="Validasi">
                  {{ row.errors.length ? row.errors.join(' ') : 'Siap diimpor' }}
                </td>
              </tr>
              <tr v-if="importPreview.rows.length === 0">
                <td colspan="6" class="master-data__empty">Tidak ada baris data untuk diimpor.</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="master-data__form-actions">
          <button
            class="button button--primary"
            data-testid="commit-student-import"
            type="button"
            :disabled="!importPreview.can_commit || isImportCommitting"
            @click="commitImport"
          >
            {{ isImportCommitting ? 'Menyimpan…' : 'Commit import' }}
          </button>
        </div>
        <p v-if="!importPreview.can_commit" class="master-data__muted">
          Tidak ada baris yang disimpan. Perbaiki file lalu jalankan preview kembali.
        </p>
      </template>
    </section>

    <section v-if="isFormOpen" class="master-data__panel" aria-labelledby="form-title">
      <div class="master-data__panel-heading">
        <h2 id="form-title">
          {{ editingId ? 'Ubah' : 'Tambah' }}
          {{ tabs.find((item) => item.id === tab)?.label.toLowerCase() }}
        </h2>
        <button class="button button--text" type="button" @click="isFormOpen = false">Tutup</button>
      </div>
      <form class="master-data__form" @submit.prevent="submitForm">
        <template v-if="tab === 'students'">
          <label
            >NIS/NISN<input
              v-model="form.student_number"
              required
              maxlength="32"
              autocomplete="off"
          /></label>
          <label
            >Nama lengkap<input
              v-model="form.full_name"
              required
              maxlength="200"
              autocomplete="name"
          /></label>
        </template>
        <template v-else-if="tab === 'classes'">
          <label>Kode kelas<input v-model="form.code" required maxlength="32" /></label>
          <label>Nama kelas<input v-model="form.name" required maxlength="120" /></label>
          <label
            >Tingkat<input v-model.number="form.grade" required type="number" min="1" max="12"
          /></label>
          <label
            >Tahun ajaran<input
              v-model="form.academic_year"
              required
              pattern="\d{4}-\d{4}"
              placeholder="2026-2027"
          /></label>
        </template>
        <template v-else>
          <label>Kode laboratorium<input v-model="form.code" required maxlength="32" /></label>
          <label>Nama laboratorium<input v-model="form.name" required maxlength="120" /></label>
          <label>Lokasi (opsional)<input v-model="form.location" maxlength="200" /></label>
        </template>
        <label v-if="editingId" class="master-data__checkbox">
          <input v-model="form.is_active" type="checkbox" /> Data aktif
        </label>
        <p v-if="formError" class="master-data__alert master-data__alert--form" role="alert">
          {{ formError }}
        </p>
        <div class="master-data__form-actions">
          <button class="button button--secondary" type="button" @click="isFormOpen = false">
            Batal
          </button>
          <button class="button button--primary" type="submit">
            {{ editingId ? 'Simpan perubahan' : 'Simpan' }}
          </button>
        </div>
      </form>
    </section>

    <div class="master-data__table-wrap">
      <table class="master-data__table">
        <thead>
          <tr>
            <th v-for="column in columns" :key="column" scope="col">{{ column }}</th>
            <th scope="col">Aksi</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="isLoading">
            <td :colspan="columns.length + 1" class="master-data__empty">Memuat data…</td>
          </tr>
          <tr v-else-if="rows.length === 0">
            <td :colspan="columns.length + 1" class="master-data__empty">
              Belum ada data yang cocok.
            </td>
          </tr>
          <tr v-for="row in rows" v-else :key="row.id">
            <td
              v-for="(value, index) in displayValues(row)"
              :key="index"
              :data-label="columns[index]"
            >
              <span
                v-if="index === displayValues(row).length - 1 && (tab !== 'classes' || index === 4)"
                class="status-badge"
                :class="value === 'Aktif' ? 'status-badge--active' : 'status-badge--inactive'"
                >{{ value }}</span
              >
              <template v-else>{{ value }}</template>
            </td>
            <td class="master-data__actions" data-label="Aksi">
              <button class="button button--text" type="button" @click="openDetails(row)">
                Detail
              </button>
              <button
                v-if="canManage"
                class="button button--text"
                type="button"
                @click="openEdit(row)"
              >
                Ubah
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="master-data__pagination" aria-label="Navigasi halaman">
      <span>{{
        total === 0
          ? '0 data'
          : `${page * pageSize + 1}–${Math.min((page + 1) * pageSize, total)} dari ${total}`
      }}</span>
      <div>
        <button
          class="button button--secondary"
          type="button"
          :disabled="page === 0"
          @click="goToPage(page - 1)"
        >
          Sebelumnya
        </button>
        <span>Halaman {{ page + 1 }} dari {{ totalPages }}</span>
        <button
          class="button button--secondary"
          type="button"
          :disabled="page + 1 >= totalPages"
          @click="goToPage(page + 1)"
        >
          Berikutnya
        </button>
      </div>
    </div>

    <section
      v-if="details || isDetailsLoading"
      class="master-data__panel master-data__detail"
      aria-labelledby="detail-title"
    >
      <div class="master-data__panel-heading">
        <div>
          <p class="master-data__eyebrow">
            Detail {{ tabs.find((item) => item.id === tab)?.label.toLowerCase() }}
          </p>
          <h2 id="detail-title">{{ isDetailsLoading ? 'Memuat detail…' : detailTitle }}</h2>
        </div>
        <button
          v-if="!isDetailsLoading"
          class="button button--text"
          type="button"
          @click="details = null"
        >
          Tutup detail
        </button>
      </div>
      <p v-if="isDetailsLoading" class="master-data__muted">Memuat data terbaru…</p>
      <template v-else-if="details && 'student_number' in details">
        <dl class="master-data__details">
          <div>
            <dt>NIS/NISN</dt>
            <dd>{{ details.student_number }}</dd>
          </div>
          <div>
            <dt>Status</dt>
            <dd>{{ details.is_active ? 'Aktif' : 'Nonaktif' }}</dd>
          </div>
          <div>
            <dt>Kelas</dt>
            <dd>
              {{
                details.classes.length
                  ? details.classes.map((item) => `${item.name} (${item.academic_year})`).join(', ')
                  : 'Belum terdaftar'
              }}
            </dd>
          </div>
        </dl>
      </template>
      <template v-else-if="details && 'grade' in details">
        <dl class="master-data__details">
          <div>
            <dt>Kode</dt>
            <dd>{{ details.code }}</dd>
          </div>
          <div>
            <dt>Tingkat</dt>
            <dd>{{ details.grade }}</dd>
          </div>
          <div>
            <dt>Status</dt>
            <dd>{{ details.is_active ? 'Aktif' : 'Nonaktif' }}</dd>
          </div>
        </dl>
        <div class="master-data__roster-heading">
          <h3>Roster kelas</h3>
          <span>{{ details.students.length }} siswa</span>
        </div>
        <form
          v-if="canManage && details.is_active"
          class="master-data__enroll"
          @submit.prevent="enrollSelectedStudent"
        >
          <label class="visually-hidden" for="student-to-enroll"
            >Pilih siswa untuk ditambahkan</label
          >
          <select id="student-to-enroll" v-model="studentToEnroll" required>
            <option value="" disabled>Pilih siswa aktif</option>
            <option v-for="student in detailStudents" :key="student.id" :value="student.id">
              {{ student.student_number }} · {{ student.full_name }}
            </option>
          </select>
          <button class="button button--primary" type="submit" :disabled="!studentToEnroll">
            Tambah siswa
          </button>
        </form>
        <p v-if="details.students.length === 0" class="master-data__muted">
          Roster belum berisi siswa.
        </p>
        <ul v-else class="master-data__roster">
          <li v-for="student in details.students" :key="student.id">
            <span
              ><strong>{{ student.full_name }}</strong
              ><small
                >{{ student.student_number }} ·
                {{ student.is_active ? 'Aktif' : 'Nonaktif' }}</small
              ></span
            >
            <button
              v-if="canManage"
              class="button button--text"
              type="button"
              :aria-label="`Keluarkan ${student.full_name} dari kelas`"
              @click="removeStudent(student.id)"
            >
              Keluarkan
            </button>
          </li>
        </ul>
      </template>
      <template v-else-if="details">
        <dl class="master-data__details">
          <div>
            <dt>Kode</dt>
            <dd>{{ details.code }}</dd>
          </div>
          <div>
            <dt>Lokasi</dt>
            <dd>{{ details.location || '—' }}</dd>
          </div>
          <div>
            <dt>Status</dt>
            <dd>{{ details.is_active ? 'Aktif' : 'Nonaktif' }}</dd>
          </div>
        </dl>
      </template>
    </section>
  </section>
</template>
