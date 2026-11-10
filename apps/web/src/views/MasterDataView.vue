<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { deviceHealthLabel } from '../utils/attendanceStatus'
import {
  ApiError,
  commitStudentImport,
  createClass,
  createLaboratory,
  createStudent,
  enrollStudent,
  getClass,
  getLaboratory,
  getStudent,
  listClassLaboratories,
  listClassTeachers,
  listClasses,
  listDevices,
  listLabLaborants,
  listLaboratories,
  listStudents,
  previewStudentImport,
  removeStudentFromClass,
  updateClass,
  updateLaboratory,
  updateStudent,
  type ClassDetails,
  type Device,
  type Laboratory,
  type SchoolClass,
  type Student,
  type StudentDetails,
  type StudentImportPreview,
} from '../api/client'
import UiAvatar from '../components/ui/UiAvatar.vue'
import UiBadge from '../components/ui/UiBadge.vue'
import UiButton from '../components/ui/UiButton.vue'
import UiCard from '../components/ui/UiCard.vue'
import UiDrawer from '../components/ui/UiDrawer.vue'
import UiEmptyState from '../components/ui/UiEmptyState.vue'
import UiField from '../components/ui/UiField.vue'
import UiInput from '../components/ui/UiInput.vue'
import UiModal from '../components/ui/UiModal.vue'
import UiPageHeader from '../components/ui/UiPageHeader.vue'
import UiPagination from '../components/ui/UiPagination.vue'
import UiSearchInput from '../components/ui/UiSearchInput.vue'
import UiSelect from '../components/ui/UiSelect.vue'
import UiTabs from '../components/ui/UiTabs.vue'

type MasterTab = 'students' | 'classes' | 'laboratories'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const canManage = computed(() => auth.account?.roles.includes('ADMIN') ?? false)

const tab = ref<MasterTab>('students')
const rows = ref<(Student | SchoolClass | Laboratory)[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 10
const searchText = ref('')
const search = ref('')
const classFilter = ref('')
const statusFilter = ref('')
const isLoading = ref(false)
const errorMessage = ref<string | null>(null)
const formError = ref<string | null>(null)
const nisAvailability = computed(() => {
  const raw = String(form.value.student_number ?? '').trim()
  if (!raw) return 'idle' as const
  const taken = (rows.value as { id?: string; student_number?: string }[]).some(
    (r) => r.student_number?.trim() === raw && (!editingId.value || r.id !== editingId.value),
  )
  return taken ? ('taken' as const) : ('ok' as const)
})
const successMessage = ref<string | null>(null)

// form modal tambah/edit
const isFormOpen = ref(false)
const editingId = ref<string | null>(null)
const form = ref<Record<string, string | number | boolean>>({})

// import
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

// detail siswa
const studentDetail = ref<StudentDetails | null>(null)
function displayShortDate(value: string | null | undefined): string {
  if (!value) return '-'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return '-'
  return d.toLocaleDateString('id-ID', { day: 'numeric', month: 'short', year: 'numeric' })
}

function editStudentFromDetail(): void {
  if (!studentDetail.value || !canManage.value) return
  openEditStudent(studentDetail.value)
  closeStudentDrawer()
}

const isStudentDrawerOpen = ref(false)

// detail kelas
const classDetail = ref<ClassDetails | null>(null)
const classTeachers = ref<
  {
    user_id: string
    full_name: string | null
    starts_on: string | null
    ends_on: string | null
    is_substitute: boolean
  }[]
>([])
const classTab = ref<'members' | 'teachers'>('members')
const detailStudents = ref<Student[]>([])
const studentToEnroll = ref('')
const isDetailLoading = ref(false)

// detail lab
const labDetail = ref<Laboratory | null>(null)
const labDevices = ref<Device[]>([])
const labClasses = ref<SchoolClass[]>([])
const labStaff = ref<{ user_id: string; full_name: string | null; email: string | null }[]>([])

const tabs = [
  { id: 'students', label: 'Siswa' },
  { id: 'classes', label: 'Kelas' },
  { id: 'laboratories', label: 'Laboratorium' },
]
const tabPaths: Record<MasterTab, string> = {
  students: '/app/master-data/students',
  classes: '/app/master-data/classes',
  laboratories: '/app/master-data/laboratories',
}
const classOptions = ref<SchoolClass[]>([])
const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))
const activeFilterCount = computed(() => (classFilter.value ? 1 : 0) + (statusFilter.value ? 1 : 0))

function formatError(error: unknown): string {
  if (error instanceof ApiError) {
    const details = error.details?.map((item) => `${item.field}: ${item.message}`)
    return details?.length ? details.join(' · ') : error.message
  }
  return 'Permintaan tidak dapat diproses. Coba lagi.'
}

function syncTabFromRoute(): void {
  const name = String(route.name ?? '')
  if (name === 'master-data-class-detail' || name === 'master-data-classes') tab.value = 'classes'
  else if (name === 'master-data-laboratory-detail' || name === 'master-data-laboratories')
    tab.value = 'laboratories'
  else tab.value = 'students'
}

async function loadRows(): Promise<void> {
  isLoading.value = true
  errorMessage.value = null
  try {
    const query = {
      limit: pageSize,
      offset: (page.value - 1) * pageSize,
      search: search.value || undefined,
      is_active: statusFilter.value ? statusFilter.value === 'active' : undefined,
      class_id: tab.value === 'students' && classFilter.value ? classFilter.value : undefined,
    }
    const result =
      tab.value === 'students'
        ? await listStudents(query)
        : tab.value === 'classes'
          ? await listClasses(query)
          : await listLaboratories(query)
    rows.value = result.items as (Student | SchoolClass | Laboratory)[]
    total.value = result.pagination.total
  } catch (error) {
    errorMessage.value = formatError(error)
  } finally {
    isLoading.value = false
  }
}

async function loadClassOptions(): Promise<void> {
  try {
    const result = await listClasses({ limit: 100, offset: 0 })
    classOptions.value = result.items
  } catch {
    classOptions.value = []
  }
}

async function refreshAll(): Promise<void> {
  page.value = 1
  await Promise.all([loadRows(), loadClassOptions()])
  const detailId = route.params.id
  if (route.name === 'master-data-class-detail' && typeof detailId === 'string') {
    await openClassDetail(detailId)
  } else if (route.name === 'master-data-laboratory-detail' && typeof detailId === 'string') {
    await openLabDetail(detailId)
  } else {
    classDetail.value = null
    labDetail.value = null
  }
}

function setTab(next: string): void {
  const nextTab = next as MasterTab
  if (nextTab === tab.value && !route.params.id) return
  searchText.value = ''
  search.value = ''
  classFilter.value = ''
  statusFilter.value = ''
  void router.push(tabPaths[nextTab])
}

function createDefaults(): Record<string, string | number | boolean> {
  if (tab.value === 'students')
    return { student_number: '', full_name: '', is_active: true, class_id: '' }
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

function openEditStudent(row: Student): void {
  editingId.value = row.id
  form.value = {
    student_number: row.student_number,
    full_name: row.full_name,
    is_active: row.is_active,
  }
  formError.value = null
  isFormOpen.value = true
}

function openEditRow(row: SchoolClass | Laboratory): void {
  editingId.value = row.id
  form.value = { ...row } as Record<string, string | number | boolean>
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
      let studentId = editingId.value
      if (editingId.value) {
        await updateStudent(editingId.value, {
          ...payload,
          is_active: Boolean(form.value.is_active),
        })
      } else {
        const created = await createStudent(payload)
        studentId = created.id
      }
      const classId = String(form.value.class_id ?? '')
      if (classId && studentId) await enrollStudent(classId, studentId)
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
    successMessage.value = 'Data berhasil disimpan.'
    await loadRows()
    if (classDetail.value) await openClassDetail(classDetail.value.id)
  } catch (error) {
    formError.value = formatError(error)
  }
}

function openImport(): void {
  isImportOpen.value = true
  importFile.value = null
  importPreview.value = null
  importError.value = null
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
    successMessage.value = `${result.imported_count} siswa berhasil diimpor bersama relasi kelasnya.`
    isImportOpen.value = false
    importPreview.value = null
    await loadRows()
  } catch (error) {
    importError.value = formatError(error)
  } finally {
    isImportCommitting.value = false
  }
}

async function openStudentDetail(row: Student): Promise<void> {
  studentDetail.value = null
  isStudentDrawerOpen.value = true
  try {
    studentDetail.value = await getStudent(row.id)
  } catch (error) {
    errorMessage.value = formatError(error)
  }
}

async function openClassDetail(classId: string): Promise<void> {
  isDetailLoading.value = true
  errorMessage.value = null
  try {
    const [details, teachers] = await Promise.all([
      getClass(classId),
      listClassTeachers(classId).catch(() => ({ items: [] as typeof classTeachers.value })),
    ])
    classDetail.value = details
    classTeachers.value = teachers.items
    const active = await listStudents({ limit: 100, offset: 0, is_active: true }).catch(() => ({
      items: [] as Student[],
    }))
    detailStudents.value = active.items.filter(
      (student) => !details.students.some((member) => member.id === student.id),
    )
  } catch (error) {
    errorMessage.value = formatError(error)
  } finally {
    isDetailLoading.value = false
  }
}

async function openLabDetail(labId: string): Promise<void> {
  isDetailLoading.value = true
  errorMessage.value = null
  try {
    const [lab, devPage, mapping, staff] = await Promise.all([
      getLaboratory(labId),
      listDevices({ limit: 100, offset: 0 }).catch(() => ({ items: [] as Device[] })),
      listClassLaboratories().catch(() => ({
        items: [] as { class_id: string; laboratory_id: string }[],
      })),
      listLabLaborants(labId).catch(() => ({ items: [] as typeof labStaff.value })),
    ])
    labDetail.value = lab
    labStaff.value = staff.items
    labDevices.value = devPage.items.filter((d) => d.laboratory_id === labId)
    const classIds = new Set(
      mapping.items.filter((m) => m.laboratory_id === labId).map((m) => m.class_id),
    )
    const clsPage = await listClasses({ limit: 100, offset: 0 }).catch(() => ({
      items: [] as SchoolClass[],
    }))
    labClasses.value = clsPage.items.filter((c) => classIds.has(c.id))
  } catch (error) {
    errorMessage.value = formatError(error)
  } finally {
    isDetailLoading.value = false
  }
}

async function enrollSelectedStudent(): Promise<void> {
  if (!studentToEnroll.value || !classDetail.value) return
  try {
    await enrollStudent(classDetail.value.id, studentToEnroll.value)
    studentToEnroll.value = ''
    await openClassDetail(classDetail.value.id)
    await loadRows()
  } catch (error) {
    errorMessage.value = formatError(error)
  }
}

async function removeStudent(studentId: string): Promise<void> {
  if (!classDetail.value) return
  try {
    await removeStudentFromClass(classDetail.value.id, studentId)
    await openClassDetail(classDetail.value.id)
  } catch (error) {
    errorMessage.value = formatError(error)
  }
}

function submitSearch(): void {
  page.value = 1
  search.value = searchText.value.trim()
  void loadRows()
}

function resetFilters(): void {
  searchText.value = ''
  search.value = ''
  classFilter.value = ''
  statusFilter.value = ''
  page.value = 1
  void loadRows()
}

function goToPage(nextPage: number): void {
  if (nextPage < 1 || nextPage > totalPages.value || nextPage === page.value) return
  page.value = nextPage
  void loadRows()
}

watch(
  () => route.fullPath,
  () => {
    syncTabFromRoute()
    void refreshAll()
  },
)

onMounted(() => {
  syncTabFromRoute()
  void refreshAll()
})

function selectClass(classId: string): void {
  void router.push(`/app/master-data/classes/${classId}`)
}

function selectLab(labId: string): void {
  void router.push(`/app/master-data/laboratories/${labId}`)
}

function backToList(): void {
  classDetail.value = null
  labDetail.value = null
  void router.push(tabPaths[tab.value])
}

function closeStudentDrawer(): void {
  isStudentDrawerOpen.value = false
  studentDetail.value = null
}

function classNamesOf(student: Student): string {
  return student.classes?.map((c) => c.code).join(', ') || '-'
}

function labStatusTone(lab: Laboratory): 'present' | 'neutral' {
  return lab.is_active ? 'present' : 'neutral'
}
</script>

<template>
  <div class="st-page">
    <UiTabs :tabs="tabs" :model-value="tab" @update:model-value="setTab" />

    <p v-if="successMessage" class="st-alert st-alert--success" role="status">
      {{ successMessage }}
    </p>
    <p v-if="errorMessage" class="st-alert st-alert--error" role="alert">{{ errorMessage }}</p>

    <!-- ============ TAB SISWA (B02-01) ============ -->
    <section v-if="tab === 'students' && !classDetail && !labDetail">
      <UiPageHeader
        title="Siswa"
        description="Kelola data induk siswa, penetapan kelas, dan status keaktifan akademik"
      >
        <template #actions>
          <UiButton v-if="canManage" variant="secondary" @click="openImport">Impor Siswa</UiButton>
          <UiButton v-if="canManage" variant="primary" @click="openCreate">+ Tambah Siswa</UiButton>
        </template>
      </UiPageHeader>

      <form class="st-toolbar" @submit.prevent="submitSearch">
        <UiSearchInput
          v-model="searchText"
          placeholder="Cari nomor siswa atau nama…"
          aria-label="Cari siswa"
        />
        <UiSelect v-model="classFilter" aria-label="Filter kelas" @change="submitSearch">
          <option value="">Semua Kelas</option>
          <option v-for="cls in classOptions" :key="cls.id" :value="cls.id">
            {{ cls.code }} - {{ cls.name }}
          </option>
        </UiSelect>
        <UiSelect v-model="statusFilter" aria-label="Filter status" @change="submitSearch">
          <option value="">Semua Status</option>
          <option value="active">Aktif</option>
          <option value="inactive">Nonaktif</option>
        </UiSelect>
        <UiButton variant="secondary" type="submit">Cari</UiButton>
        <span class="st-toolbar__spacer" />
        <span v-if="activeFilterCount > 0" class="st-chip"
          >Filter Aktif: {{ activeFilterCount }} Kategori</span
        >
        <UiButton v-if="activeFilterCount > 0" variant="text" size="sm" @click="resetFilters"
          >Reset</UiButton
        >
      </form>

      <div class="st-card">
        <div class="st-tablewrap">
          <table class="st-table">
            <thead>
              <tr>
                <th scope="col">Nomor Siswa</th>
                <th scope="col">Nama Siswa</th>
                <th scope="col">Kelas</th>
                <th scope="col">Status</th>
                <th scope="col" class="st-table__actions">Aksi</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="isLoading">
                <td colspan="5" class="st-table__muted">Memuat data siswa…</td>
              </tr>
              <tr v-for="row in rows as Student[]" v-else :key="row.id">
                <td class="st-table__mono">{{ row.student_number }}</td>
                <td>
                  <span class="st-identity">
                    <UiAvatar :name="row.full_name" />
                    <span>{{ row.full_name }}</span>
                  </span>
                </td>
                <td>{{ classNamesOf(row) }}</td>
                <td>
                  <UiBadge :tone="row.is_active ? 'present' : 'neutral'">{{
                    row.is_active ? 'Aktif' : 'Nonaktif'
                  }}</UiBadge>
                </td>
                <td class="st-table__actions">
                  <button type="button" class="st-link" @click="openStudentDetail(row)">
                    Detail
                  </button>
                  <button
                    v-if="canManage"
                    type="button"
                    class="st-link"
                    @click="openEditStudent(row)"
                  >
                    Edit
                  </button>
                </td>
              </tr>
              <tr v-if="!isLoading && rows.length === 0">
                <td colspan="5">
                  <UiEmptyState
                    title="Belum ada siswa"
                    description="Tambah siswa baru atau impor dari berkas."
                  />
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <UiPagination
          :page="page"
          :total-pages="totalPages"
          :total="total"
          label="siswa"
          @update:page="goToPage"
        />
      </div>
    </section>

    <!-- ============ TAB KELAS (B02-04) ============ -->
    <section v-if="tab === 'classes' && !classDetail">
      <UiPageHeader
        title="Kelas"
        description="Struktur rombongan belajar, penugasan guru pengampu, dan periode tahun ajaran aktif"
      >
        <template #actions>
          <UiButton v-if="canManage" variant="primary" @click="openCreate">+ Tambah Kelas</UiButton>
        </template>
      </UiPageHeader>

      <form class="st-toolbar" @submit.prevent="submitSearch">
        <UiSearchInput
          v-model="searchText"
          placeholder="Cari nama kelas…"
          aria-label="Cari kelas"
        />
        <UiButton variant="secondary" type="submit">Cari</UiButton>
        <span class="st-toolbar__spacer" />
        <span v-if="activeFilterCount > 0" class="st-chip"
          >Filter Aktif: {{ activeFilterCount }} Kategori</span
        >
        <UiButton v-if="activeFilterCount > 0" variant="text" size="sm" @click="resetFilters"
          >Reset</UiButton
        >
      </form>

      <div class="st-card">
        <div class="st-tablewrap">
          <table class="st-table">
            <thead>
              <tr>
                <th scope="col">Nama Kelas</th>
                <th scope="col">Tingkat</th>
                <th scope="col">Tahun Ajaran</th>
                <th scope="col">Status</th>
                <th scope="col" class="st-table__actions">Aksi</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="isLoading">
                <td colspan="5" class="st-table__muted">Memuat data kelas…</td>
              </tr>
              <tr v-for="row in rows as SchoolClass[]" v-else :key="row.id">
                <td>
                  <span class="st-identity">
                    <UiAvatar :name="row.name" />
                    <span
                      ><strong>{{ row.code }}</strong
                      ><br /><span class="st-table__muted">{{ row.name }}</span></span
                    >
                  </span>
                </td>
                <td>Kelas {{ row.grade }}</td>
                <td>{{ row.academic_year }}</td>
                <td>
                  <UiBadge :tone="row.is_active ? 'present' : 'neutral'">{{
                    row.is_active ? 'Aktif' : 'Nonaktif'
                  }}</UiBadge>
                </td>
                <td class="st-table__actions">
                  <button type="button" class="st-link" @click="selectClass(row.id)">
                    Detail Kelas →
                  </button>
                  <button v-if="canManage" type="button" class="st-link" @click="openEditRow(row)">
                    Edit
                  </button>
                </td>
              </tr>
              <tr v-if="!isLoading && rows.length === 0">
                <td colspan="5">
                  <UiEmptyState
                    title="Belum ada kelas"
                    description="Tambah kelas baru untuk tahun ajaran aktif."
                  />
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <UiPagination
          :page="page"
          :total-pages="totalPages"
          :total="total"
          label="kelas"
          @update:page="goToPage"
        />
      </div>
    </section>

    <!-- ============ DETAIL KELAS (B02-05) ============ -->
    <section v-if="classDetail">
      <UiButton variant="text" size="sm" @click="backToList">← Kembali ke daftar kelas</UiButton>
      <UiPageHeader
        :title="classDetail.code"
        :description="`${classDetail.name} · Tahun ajaran ${classDetail.academic_year}`"
      >
        <template #actions>
          <UiButton v-if="canManage" variant="primary" @click="openEditRow(classDetail)"
            >Ubah Kelas</UiButton
          >
        </template>
      </UiPageHeader>

      <div class="st-grid3">
        <UiCard title="Tingkat">
          <p class="st-kpi">Kelas {{ classDetail.grade }}</p>
          <p class="st-table__muted">
            {{ classDetail.is_active ? 'Kelas Aktif' : 'Kelas Nonaktif' }}
          </p>
        </UiCard>
        <UiCard title="Periode Aktif">
          <p class="st-kpi">{{ classDetail.academic_year }}</p>
          <p class="st-table__muted">Tahun ajaran berjalan</p>
        </UiCard>
        <UiCard title="Total Roster">
          <p class="st-kpi">{{ classDetail.students.length }} <small>Siswa Terdaftar</small></p>
          <p class="st-table__muted">
            {{ classDetail.students.filter((s) => s.is_active).length }} Aktif Mengikuti
          </p>
        </UiCard>
      </div>

      <div class="st-card">
        <UiTabs
          :tabs="[
            { id: 'members', label: `Anggota Siswa (${classDetail.students.length})` },
            { id: 'teachers', label: 'Guru Penugasan & Riwayat' },
          ]"
          :model-value="classTab"
          @update:model-value="classTab = $event as 'members' | 'teachers'"
        />
        <div v-if="classTab === 'members'">
          <form v-if="canManage" class="st-toolbar" @submit.prevent="enrollSelectedStudent">
            <UiSelect v-model="studentToEnroll" aria-label="Pilih siswa untuk ditambahkan">
              <option value="">Pilih siswa untuk ditambahkan…</option>
              <option v-for="s in detailStudents" :key="s.id" :value="s.id">
                {{ s.student_number }} - {{ s.full_name }}
              </option>
            </UiSelect>
            <UiButton
              variant="secondary"
              :disabled="!studentToEnroll"
              @click="enrollSelectedStudent"
              >Tambah Anggota</UiButton
            >
          </form>
          <div class="st-tablewrap">
            <table class="st-table">
              <thead>
                <tr>
                  <th scope="col">Nomor Siswa</th>
                  <th scope="col">Nama Lengkap</th>
                  <th scope="col">Status Keanggotaan</th>
                  <th v-if="canManage" scope="col" class="st-table__actions">Aksi</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="member in classDetail.students" :key="member.id">
                  <td class="st-table__mono">{{ member.student_number }}</td>
                  <td>
                    <span class="st-identity">
                      <UiAvatar :name="member.full_name" />
                      <span>{{ member.full_name }}</span>
                    </span>
                  </td>
                  <td>
                    <UiBadge :tone="member.is_active ? 'present' : 'neutral'">{{
                      member.is_active ? 'Terdaftar Aktif' : 'Nonaktif'
                    }}</UiBadge>
                  </td>
                  <td v-if="canManage" class="st-table__actions">
                    <button
                      type="button"
                      class="st-link st-link--danger"
                      @click="removeStudent(member.id)"
                    >
                      Keluarkan
                    </button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
        <div v-else>
          <ul class="st-list">
            <li v-for="teacher in classTeachers" :key="teacher.user_id" class="st-list__item">
              <div>
                <strong>{{ teacher.full_name ?? teacher.user_id }}</strong>
                <span v-if="teacher.is_substitute" class="st-chip">Pengganti</span>
                <br />
                <span class="st-table__muted"
                  >{{ teacher.starts_on ?? '-' }} s.d. {{ teacher.ends_on ?? '-' }}</span
                >
              </div>
            </li>
            <li v-if="classTeachers.length === 0" class="st-list__item st-table__muted">
              Belum ada guru penugasan pada kelas ini.
            </li>
          </ul>
        </div>
      </div>
    </section>

    <!-- ============ TAB LABORATORIUM (B02-06) ============ -->
    <section v-if="tab === 'laboratories' && !classDetail">
      <UiPageHeader
        title="Laboratorium"
        description="Manajemen laboratorium, pemetaan perangkat presensi, dan petugas laboran"
      >
        <template #actions>
          <UiButton v-if="canManage" variant="primary" @click="openCreate"
            >+ Tambah Laboratorium</UiButton
          >
        </template>
      </UiPageHeader>

      <div class="st-split">
        <div class="st-card">
          <h2 class="st-card__title">Daftar Laboratorium</h2>
          <p v-if="isLoading" class="st-table__muted">Memuat…</p>
          <ul class="st-list">
            <li v-for="row in rows as Laboratory[]" :key="row.id">
              <button
                type="button"
                class="st-list__item st-list__item--button"
                :class="{ 'st-list__item--active': labDetail?.id === row.id }"
                @click="selectLab(row.id)"
              >
                <span class="st-identity">
                  <UiAvatar :name="row.name" />
                  <span
                    ><strong>{{ row.name }}</strong
                    ><br /><span class="st-table__muted">{{ row.code }}</span></span
                  >
                </span>
                <UiBadge :tone="labStatusTone(row)">{{
                  row.is_active ? 'Siap Operasional' : 'Nonaktif'
                }}</UiBadge>
              </button>
            </li>
          </ul>
          <UiPagination
            :page="page"
            :total-pages="totalPages"
            :total="total"
            label="laboratorium"
            @update:page="goToPage"
          />
        </div>

        <div class="st-card">
          <div v-if="isDetailLoading">
            <p class="st-table__muted">Memuat detail laboratorium…</p>
          </div>
          <div v-else-if="labDetail">
            <div class="st-detailhead">
              <h2 class="st-card__title">Detail {{ labDetail.name }}</h2>
              <UiButton
                v-if="canManage"
                variant="secondary"
                size="sm"
                @click="openEditRow(labDetail)"
                >Edit Identitas Lab</UiButton
              >
            </div>
            <h3 class="st-section">1. Identitas &amp; Status</h3>
            <dl class="st-def">
              <div>
                <dt>Nama Laboratorium</dt>
                <dd>{{ labDetail.name }}</dd>
              </div>
              <div>
                <dt>Kode Ruang</dt>
                <dd>{{ labDetail.code }}</dd>
              </div>
              <div>
                <dt>Lokasi</dt>
                <dd>{{ labDetail.location ?? '-' }}</dd>
              </div>
              <div>
                <dt>Status Operasi</dt>
                <dd>{{ labDetail.is_active ? 'Aktif & Siap Digunakan' : 'Nonaktif' }}</dd>
              </div>
            </dl>
            <h3 class="st-section">2. Perangkat Terhubung</h3>
            <ul class="st-list">
              <li v-for="device in labDevices" :key="device.device_id" class="st-list__item">
                <div>
                  <strong>{{ device.name }}</strong
                  ><br />
                  <span class="st-table__muted"
                    >Status kamera: {{ deviceHealthLabel(device.camera_status) }} · Kesehatan:
                    {{ deviceHealthLabel(device.health_status) }}</span
                  >
                </div>
              </li>
              <li v-if="labDevices.length === 0" class="st-list__item st-table__muted">
                Belum ada perangkat terhubung.
              </li>
            </ul>
            <h3 class="st-section">3. Kelas yang Dilayani</h3>
            <ul class="st-chips">
              <li v-for="cls in labClasses" :key="cls.id" class="st-chip">{{ cls.code }}</li>
              <li v-if="labClasses.length === 0" class="st-table__muted">
                Belum ada pemetaan kelas.
              </li>
            </ul>
            <h3 class="st-section">4. Petugas Laboran</h3>
            <ul class="st-list">
              <li v-for="staff in labStaff" :key="staff.user_id" class="st-list__item">
                <div>
                  <strong>{{ staff.full_name ?? staff.user_id }}</strong
                  ><br />
                  <span class="st-table__muted">{{ staff.email ?? '' }}</span>
                </div>
              </li>
              <li v-if="labStaff.length === 0" class="st-list__item st-table__muted">
                Belum ada laboran ditugaskan.
              </li>
            </ul>
          </div>
          <UiEmptyState
            v-else
            title="Pilih laboratorium"
            description="Pilih salah satu laboratorium untuk melihat identitas, perangkat, kelas yang dilayani, dan petugas."
          />
        </div>
      </div>
    </section>

    <!-- ============ DRAWER FORMULIR MASTER (B02-02) ============ -->
    <UiDrawer
      v-if="isFormOpen"
      :title="
        editingId
          ? 'Ubah Data'
          : tab === 'students'
            ? 'Tambah Siswa Baru'
            : tab === 'classes'
              ? 'Tambah Kelas'
              : 'Tambah Laboratorium'
      "
      subtitle="Formulir master - isi identitas lalu simpan ke data master."
      @close="isFormOpen = false"
    >
      <p v-if="formError" class="st-alert st-alert--error" role="alert">{{ formError }}</p>
      <form @submit.prevent="submitForm">
        <template v-if="tab === 'students'">
          <UiField
            label="Nomor Siswa (NIS/NISN)"
            required
            :error="
              nisAvailability === 'taken'
                ? 'Nomor ini sudah terdaftar pada data yang dimuat.'
                : null
            "
          >
            <template #label-action>
              <span v-if="nisAvailability === 'ok'" class="st-field__ok">Valid &amp; Tersedia</span>
              <span v-else-if="nisAvailability === 'taken'" class="st-field__bad"
                >Sudah terdaftar</span
              >
            </template>
            <UiInput
              :model-value="String(form.student_number ?? '')"
              name="student_number"
              required
              @update:model-value="form.student_number = $event"
            />
            <p class="st-field__hintbox">
              Nomor siswa harus unik dan belum terdaftar di tahun ajaran aktif.
            </p>
          </UiField>
          <UiField label="Nama Lengkap Siswa" required>
            <UiInput
              :model-value="String(form.full_name ?? '')"
              name="full_name"
              required
              @update:model-value="form.full_name = $event"
            />
            <p class="st-table__muted">Nama ini akan tercantum pada display presensi lab.</p>
          </UiField>
          <UiField label="Rombongan Belajar (Kelas)">
            <UiSelect
              :model-value="String(form.class_id ?? '')"
              @update:model-value="form.class_id = $event"
            >
              <option value="">- Tanpa kelas -</option>
              <option v-for="cls in classOptions" :key="cls.id" :value="cls.id">
                {{ cls.code }} - {{ cls.name }}
              </option>
            </UiSelect>
          </UiField>
          <UiField label="Status Akademik Siswa" required>
            <div class="st-radio-cards">
              <label class="st-radio-card" :class="{ 'st-radio-card--active': form.is_active }">
                <input v-model="form.is_active" type="radio" :value="true" name="is_active" />
                <span><strong>Aktif</strong><small>Akses penuh modul &amp; lab</small></span>
              </label>
              <label class="st-radio-card" :class="{ 'st-radio-card--active': !form.is_active }">
                <input v-model="form.is_active" type="radio" :value="false" name="is_active" />
                <span><strong>Nonaktif</strong><small>Skorsing / penundaan</small></span>
              </label>
            </div>
          </UiField>
        </template>
        <template v-else-if="tab === 'classes'">
          <UiField label="Kode Kelas" required>
            <UiInput
              :model-value="String(form.code ?? '')"
              name="code"
              required
              @update:model-value="form.code = $event"
            />
          </UiField>
          <UiField label="Nama Kelas" required>
            <UiInput
              :model-value="String(form.name ?? '')"
              name="name"
              required
              @update:model-value="form.name = $event"
            />
          </UiField>
          <UiField label="Tahun Ajaran" required>
            <UiInput
              :model-value="String(form.academic_year ?? '')"
              name="academic_year"
              required
              @update:model-value="form.academic_year = $event"
            />
          </UiField>
          <UiField label="Status" required>
            <div class="st-radio-cards">
              <label class="st-radio-card" :class="{ 'st-radio-card--active': form.is_active }">
                <input v-model="form.is_active" type="radio" :value="true" name="is_active" /> Aktif
              </label>
              <label class="st-radio-card" :class="{ 'st-radio-card--active': !form.is_active }">
                <input v-model="form.is_active" type="radio" :value="false" name="is_active" />
                Nonaktif
              </label>
            </div>
          </UiField>
        </template>
        <template v-else>
          <UiField label="Kode Laboratorium" required>
            <UiInput
              :model-value="String(form.code ?? '')"
              name="code"
              required
              @update:model-value="form.code = $event"
            />
          </UiField>
          <UiField label="Nama Laboratorium" required>
            <UiInput
              :model-value="String(form.name ?? '')"
              name="name"
              required
              @update:model-value="form.name = $event"
            />
          </UiField>
          <UiField label="Lokasi">
            <UiInput
              :model-value="String(form.location ?? '')"
              name="location"
              @update:model-value="form.location = $event"
            />
          </UiField>
          <UiField label="Status" required>
            <div class="st-radio-cards">
              <label class="st-radio-card" :class="{ 'st-radio-card--active': form.is_active }">
                <input v-model="form.is_active" type="radio" :value="true" name="is_active" /> Aktif
              </label>
              <label class="st-radio-card" :class="{ 'st-radio-card--active': !form.is_active }">
                <input v-model="form.is_active" type="radio" :value="false" name="is_active" />
                Nonaktif
              </label>
            </div>
          </UiField>
        </template>
      </form>
      <template #footer>
        <UiButton variant="secondary" @click="isFormOpen = false">Batal</UiButton>
        <UiButton variant="primary" @click="submitForm">Simpan</UiButton>
      </template>
    </UiDrawer>

    <!-- ============ DRAWER DETAIL SISWA ============ -->
    <UiDrawer
      v-if="isStudentDrawerOpen"
      :title="studentDetail?.full_name ?? 'Detail Siswa'"
      subtitle="Profil siswa dan status keanggotaan kelas."
      @close="closeStudentDrawer"
    >
      <div v-if="studentDetail">
        <dl class="st-def">
          <div>
            <dt>Nomor Siswa</dt>
            <dd class="st-table__mono">{{ studentDetail.student_number }}</dd>
          </div>
          <div>
            <dt>Nama Lengkap</dt>
            <dd>{{ studentDetail.full_name }}</dd>
          </div>
          <div>
            <dt>Status</dt>
            <dd>
              <UiBadge :tone="studentDetail.is_active ? 'present' : 'neutral'">{{
                studentDetail.is_active ? 'Aktif' : 'Nonaktif'
              }}</UiBadge>
            </dd>
          </div>
        </dl>
        <h3 class="st-section">Kelas</h3>
        <ul class="st-chips">
          <li v-for="cls in studentDetail.classes" :key="cls.id" class="st-chip">
            {{ cls.code }} - {{ cls.name }}
          </li>
          <li v-if="studentDetail.classes.length === 0" class="st-table__muted">
            Belum terdaftar di kelas mana pun.
          </li>
        </ul>
        <h3 class="st-section">Catatan Data</h3>
        <p class="st-table__muted">
          Terdaftar {{ displayShortDate(studentDetail.created_at) }} · Diperbarui
          {{ displayShortDate(studentDetail.updated_at) }}
        </p>
        <p v-if="canManage">
          <UiButton variant="secondary" @click="editStudentFromDetail">Ubah Data Siswa</UiButton>
        </p>
      </div>
      <p v-else class="st-table__muted">Memuat detail siswa…</p>
    </UiDrawer>

    <!-- ============ MODAL IMPOR SISWA (B02-03) ============ -->
    <UiModal v-if="isImportOpen" title="Impor Data Siswa" wide @close="isImportOpen = false">
      <p class="st-table__muted">
        Unggah dan validasi berkas CSV atau XLSX untuk penambahan data siswa secara massal.
      </p>
      <p v-if="importError" class="st-alert st-alert--error" role="alert">{{ importError }}</p>
      <UiField label="Berkas CSV / XLSX" required>
        <input
          class="st-file"
          type="file"
          accept=".csv,.xlsx,.xls"
          @change="handleImportFileChange"
        />
      </UiField>
      <div class="st-grid2">
        <UiCard
          v-if="importPreview"
          title="Baris Valid"
          :subtitle="`${importPreview.valid_rows} baris siap dimasukkan`"
        >
          <p class="st-kpi">{{ importPreview.valid_rows }}</p>
        </UiCard>
        <UiCard
          v-if="importPreview"
          title="Baris Bermasalah"
          :subtitle="`${importPreview.invalid_rows} baris perlu koreksi`"
        >
          <p class="st-kpi">{{ importPreview.invalid_rows }}</p>
        </UiCard>
      </div>
      <div class="st-tablewrap">
        <table v-if="importPreview" class="st-table">
          <thead>
            <tr>
              <th scope="col">Baris</th>
              <th scope="col">Nomor Siswa</th>
              <th scope="col">Nama Siswa</th>
              <th scope="col">Kelas</th>
              <th scope="col">Status Validasi</th>
              <th scope="col">Keterangan</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in importPreview.rows.slice(0, 8)" :key="row.row_number">
              <td>{{ row.row_number }}</td>
              <td class="st-table__mono">{{ row.student_number }}</td>
              <td>{{ row.full_name }}</td>
              <td>{{ row.class_code }}</td>
              <td>
                <UiBadge :tone="row.valid ? 'present' : 'absent'">{{
                  row.valid ? 'Valid' : 'Error'
                }}</UiBadge>
              </td>
              <td class="st-table__muted">{{ row.errors.join('; ') || 'Format lengkap' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <template #footer>
        <UiButton variant="secondary" @click="isImportOpen = false">Batal</UiButton>
        <UiButton
          v-if="!importPreview"
          variant="primary"
          :disabled="isImportLoading || !importFile"
          @click="previewImport"
        >
          {{ isImportLoading ? 'Memvalidasi…' : 'Validasi Format' }}
        </UiButton>
        <UiButton
          v-else
          variant="primary"
          :disabled="!importPreview.can_commit || isImportCommitting"
          @click="commitImport"
        >
          {{ isImportCommitting ? 'Mengimpor…' : 'Konfirmasi Impor' }}
        </UiButton>
      </template>
    </UiModal>
  </div>
</template>
