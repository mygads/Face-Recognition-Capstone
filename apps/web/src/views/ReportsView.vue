<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import {
  UiBadge,
  UiButton,
  UiCard,
  UiEmptyState,
  UiInput,
  UiPageHeader,
  UiSearchInput,
  UiSelect,
  UiStat,
} from '../components/ui'

const route = useRoute()
import {
  ApiError,
  downloadAttendanceReport,
  getAttendanceReportSummary,
  listAttendanceReportRows,
  listAttendanceSessions,
  listSchedules,
  type AttendanceReportQuery,
  type AttendanceReportRow,
  type AttendanceReportSummary,
  type AttendanceSession,
  type Schedule,
} from '../api/client'
import { triggerDownload } from '../utils/download'
import { formatDateTimeLocal, todayLocalISO } from '../utils/dateFormat'

const pageSize = 20
const filters = reactive({
  starts_on: localDate(-6),
  ends_on: localDate(0),
  student_number: '',
  class_id: '',
  laboratory_id: '',
  session_id: '',
  status: '',
})
const schedules = ref<Schedule[]>([])
const sessions = ref<AttendanceSession[]>([])
const auth = useAuthStore()
const canExport = computed(() => {
  const roles = auth.account?.roles ?? []
  if (roles.includes('ADMIN')) return true
  return (auth.account?.permissions as string[] | undefined)?.includes('reports_export') ?? false
})
const scopeLabel = computed(() => {
  const roles = auth.account?.roles ?? []
  if (roles.includes('ADMIN')) return 'Cakupan: seluruh sekolah'
  if (roles.includes('TEACHER')) return 'Cakupan: kelas yang ditugaskan kepada Anda'
  return 'Cakupan: lab/kelas sesuai izin delegasi Anda'
})
function minutesLate(row: AttendanceReportRow): number | null {
  // Durasi dihitung dari waktu kedatangan terverifikasi (occurred_at).
  // Manual-mark tanpa jam datang yang diketahui tidak menampilkan durasi.
  if (row.status !== 'late' || !row.occurred_at) return null
  const start = new Date(row.session_opened_at).getTime()
  const rec = new Date(row.occurred_at).getTime()
  if (Number.isNaN(start) || Number.isNaN(rec)) return null
  return Math.max(0, Math.round((rec - start) / 60000))
}
const summary = ref<AttendanceReportSummary | null>(null)
const rows = ref<AttendanceReportRow[]>([])
const total = ref(0)
const tableSearch = ref('')
const reportColumns = [
  { key: 'session_time', label: 'Waktu sesi' },
  { key: 'student', label: 'Siswa' },
  { key: 'class', label: 'Kelas' },
  { key: 'lab', label: 'Laboratorium' },
  { key: 'subject', label: 'Praktikum' },
  { key: 'teacher', label: 'Guru' },
  { key: 'status', label: 'Status' },
  { key: 'late', label: 'Terlambat' },
  { key: 'note', label: 'Catatan' },
  { key: 'recorded', label: 'Waktu tercatat' },
] as const
const hiddenCols = ref<string[]>([])
function colVisible(key: string): boolean {
  return !hiddenCols.value.includes(key)
}
const visibleColCount = computed(() => reportColumns.filter((c) => colVisible(c.key)).length || 1)
const visibleRows = computed(() => {
  const q = tableSearch.value.trim().toLowerCase()
  if (!q) return rows.value
  return rows.value.filter(
    (row) =>
      row.student_name.toLowerCase().includes(q) || row.student_number.toLowerCase().includes(q),
  )
})
const page = ref(0)
const appliedQuery = ref<AttendanceReportQuery | null>(null)
const isLoading = ref(false)
const downloading = ref<'csv' | 'xlsx' | null>(null)
const errorMessage = ref<string | null>(null)
const classOptions = computed(() => {
  const options = new Map<string, Schedule>()
  schedules.value.forEach((schedule) => options.set(schedule.class_id, schedule))
  return [...options.values()]
})
const laboratoryOptions = computed(() => {
  const options = new Map<string, Schedule>()
  schedules.value.forEach((schedule) => options.set(schedule.laboratory_id, schedule))
  return [...options.values()]
})

function localDate(dayOffset: number): string {
  return todayLocalISO(dayOffset)
}

function formatError(error: unknown): string {
  if (error instanceof ApiError) {
    const details = error.details?.map((item) => `${item.field}: ${item.message}`)
    return details?.length ? details.join(' · ') : error.message
  }
  return 'Permintaan tidak dapat diproses. Coba lagi.'
}

function buildQuery(offset: number): AttendanceReportQuery {
  return {
    starts_on: filters.starts_on,
    ends_on: filters.ends_on,
    timezone_name: 'Asia/Jakarta',
    limit: pageSize,
    offset,
    student_number: filters.student_number.trim() || undefined,
    class_id: filters.class_id || undefined,
    laboratory_id: filters.laboratory_id || undefined,
    session_id: filters.session_id || undefined,
    status: filters.status ? (filters.status as AttendanceReportQuery['status']) : undefined,
  }
}

async function loadRows(query: AttendanceReportQuery): Promise<void> {
  const result = await listAttendanceReportRows(query)
  rows.value = result.items
  total.value = result.pagination.total
}

async function applyFilters(): Promise<void> {
  page.value = 0
  isLoading.value = true
  errorMessage.value = null
  const query = buildQuery(0)
  appliedQuery.value = query
  try {
    const [reportSummary, reportRows] = await Promise.all([
      getAttendanceReportSummary(query),
      listAttendanceReportRows(query),
    ])
    summary.value = reportSummary
    rows.value = reportRows.items
    total.value = reportRows.pagination.total
  } catch (error) {
    summary.value = null
    rows.value = []
    total.value = 0
    errorMessage.value = formatError(error)
  } finally {
    isLoading.value = false
  }
}

async function goToPage(nextPage: number): Promise<void> {
  const totalPages = Math.max(1, Math.ceil(total.value / pageSize))
  if (nextPage < 0 || nextPage >= totalPages || nextPage === page.value || !appliedQuery.value) {
    return
  }
  page.value = nextPage
  isLoading.value = true
  errorMessage.value = null
  try {
    const query = { ...appliedQuery.value, offset: page.value * pageSize }
    await loadRows(query)
  } catch (error) {
    errorMessage.value = formatError(error)
  } finally {
    isLoading.value = false
  }
}

async function exportReport(format: 'csv' | 'xlsx'): Promise<void> {
  if (!appliedQuery.value) return
  downloading.value = format
  errorMessage.value = null
  try {
    const { blob, filename } = await downloadAttendanceReport(appliedQuery.value, format)
    triggerDownload(blob, filename)
  } catch (error) {
    errorMessage.value = formatError(error)
  } finally {
    downloading.value = null
  }
}

function pct(part: number, whole: number): string {
  if (!whole) return '0%'
  return `${((part / whole) * 100).toFixed(1)}%`
}
function printSlip(): void {
  window.print()
}
function statusLabel(status: AttendanceReportRow['status']): string {
  return {
    present: 'Hadir',
    late: 'Terlambat',
    absent: 'Absen',
    excused: 'Izin',
    not_recorded: 'Belum tercatat',
  }[status]
}

function formatDate(value: string | null): string {
  return formatDateTimeLocal(value)
}

function sessionLabel(session: AttendanceSession): string {
  return `${formatDate(session.opened_at)} · ${session.subject} · ${session.class_name}`
}

function resetFilters(): void {
  Object.assign(filters, {
    starts_on: localDate(-6),
    ends_on: localDate(0),
    student_number: '',
    class_id: '',
    laboratory_id: '',
    session_id: '',
    status: '',
  })
  void applyFilters()
}

async function loadOptions(): Promise<void> {
  try {
    const [schedulePage, sessionPage] = await Promise.all([
      listSchedules({ limit: 100, offset: 0 }),
      listAttendanceSessions({ limit: 100, offset: 0 }),
    ])
    schedules.value = schedulePage.items
    sessions.value = sessionPage.items
  } catch (error) {
    errorMessage.value = formatError(error)
  }
}

onMounted(async () => {
  // Filter dapat dipulihkan dari URL (mis. tautan EWS ?student_number=...).
  const query = route.query
  const pick = (key: string): string => {
    const value = query[key]
    return typeof value === 'string' ? value : ''
  }
  if (pick('student_number')) filters.student_number = pick('student_number')
  if (pick('status')) filters.status = pick('status')
  if (pick('class_id')) filters.class_id = pick('class_id')
  if (pick('laboratory_id')) filters.laboratory_id = pick('laboratory_id')
  if (pick('session_id')) filters.session_id = pick('session_id')
  if (pick('starts_on')) filters.starts_on = pick('starts_on')
  if (pick('ends_on')) filters.ends_on = pick('ends_on')
  await Promise.all([loadOptions(), applyFilters()])
})
</script>

<template>
  <div class="st-page" aria-label="Laporan kehadiran">
    <UiPageHeader
      eyebrow="Arsip & Rekapitulasi"
      title="Laporan Kehadiran"
      description="Rekapitulasi presensi praktikum laboratorium terintegrasi."
    >
      <template #actions>
        <UiButton variant="secondary" type="button" @click="printSlip"
          ><span class="st-material-icon" aria-hidden="true">print</span>Cetak Slip</UiButton
        >
        <UiButton
          variant="primary"
          type="button"
          :disabled="!summary || downloading !== null || !canExport"
          data-testid="export-csv"
          @click="exportReport('csv')"
        >
          {{ downloading === 'csv' ? 'Menyiapkan CSV…' : ''
          }}<span v-if="downloading !== 'csv'" class="st-material-icon" aria-hidden="true"
            >download</span
          ><span v-if="downloading !== 'csv'">Ekspor Rekap (CSV)</span>
        </UiButton>
        <UiButton
          variant="secondary"
          type="button"
          :disabled="!summary || downloading !== null || !canExport"
          data-testid="export-xlsx"
          @click="exportReport('xlsx')"
        >
          {{ downloading === 'xlsx' ? 'Menyiapkan XLSX…' : 'XLSX' }}
        </UiButton>
      </template>
    </UiPageHeader>
    <p class="st-table__muted" data-testid="reports-scope">{{ scopeLabel }}</p>
    <p v-if="!canExport" class="st-table__muted">
      Ekspor membutuhkan izin “Ekspor Laporan”. Minta admin mengaktifkan delegasi bila perlu.
    </p>

    <UiCard title="Filter Parameter Laporan">
      <template #header>
        <UiButton variant="secondary" type="button" @click="resetFilters">Reset Semua</UiButton>
      </template>
      <form aria-label="Filter laporan" @submit.prevent="applyFilters">
        <div class="reports__filters">
          <label class="st-field"
            ><span>Mulai tanggal</span><UiInput v-model="filters.starts_on" type="date" required
          /></label>
          <label class="st-field"
            ><span>Sampai tanggal</span
            ><UiInput v-model="filters.ends_on" type="date" required :min="filters.starts_on"
          /></label>
          <label class="st-field"
            ><span>Siswa · NIS/NISN</span
            ><UiInput v-model="filters.student_number" type="text" placeholder="cth. 2401"
          /></label>
          <label class="st-field"
            ><span>Laboratorium</span>
            <UiSelect v-model="filters.laboratory_id">
              <option value="">Semua laboratorium</option>
              <option
                v-for="lab in laboratoryOptions"
                :key="lab.laboratory_id"
                :value="lab.laboratory_id"
              >
                {{ lab.laboratory_name }}
              </option>
            </UiSelect>
          </label>
          <label class="st-field"
            ><span>Kelas</span>
            <UiSelect v-model="filters.class_id">
              <option value="">Semua kelas</option>
              <option v-for="cls in classOptions" :key="cls.class_id" :value="cls.class_id">
                {{ cls.class_name }}
              </option>
            </UiSelect>
          </label>
          <label class="st-field"
            ><span>Sesi Praktikum</span>
            <UiSelect v-model="filters.session_id">
              <option value="">Semua sesi</option>
              <option v-for="session in sessions" :key="session.id" :value="session.id">
                {{ sessionLabel(session) }}
              </option>
            </UiSelect>
          </label>
          <label class="st-field"
            ><span>Status Kehadiran</span>
            <UiSelect v-model="filters.status">
              <option value="">Semua Status</option>
              <option value="present">Hadir</option>
              <option value="late">Terlambat</option>
              <option value="absent">Absen</option>
              <option value="excused">Izin</option>
              <option value="not_recorded">Belum tercatat</option>
            </UiSelect>
          </label>
        </div>
        <div style="display: flex; gap: 8px; margin-top: 12px">
          <UiButton variant="primary" type="submit" :disabled="isLoading">{{
            isLoading ? 'Memuat…' : 'Terapkan filter'
          }}</UiButton>
        </div>
      </form>
    </UiCard>

    <p v-if="errorMessage" class="st-alert st-alert--error" role="alert">{{ errorMessage }}</p>

    <div v-if="summary" class="st-kpi" aria-label="Ringkasan kehadiran">
      <UiStat
        label="Total terdaftar"
        :value="summary.total_rows"
        :caption="`${total} baris pada halaman ini`"
        icon="groups"
        :progress="100"
      />
      <UiStat
        label="Hadir tepat"
        :value="summary.present_count"
        :caption="`${pct(summary.present_count, summary.total_rows)} dari total`"
        tone="success"
        icon="check_circle"
        :progress="(summary.present_count / Math.max(1, summary.total_rows)) * 100"
      />
      <UiStat
        label="Terlambat"
        :value="summary.late_count"
        :caption="`${pct(summary.late_count, summary.total_rows)} terdata terlambat`"
        tone="warning"
        icon="schedule"
        :progress="(summary.late_count / Math.max(1, summary.total_rows)) * 100"
      />
      <UiStat
        label="Absen"
        :value="summary.absent_count"
        :caption="`${pct(summary.absent_count, summary.total_rows)} belum verifikasi`"
        tone="danger"
        icon="cancel"
        :progress="(summary.absent_count / Math.max(1, summary.total_rows)) * 100"
      />
    </div>

    <div v-if="summary && summary.absent_count > 0" class="st-notice st-notice--info" role="note">
      <span class="st-material-icon st-notice__icon" aria-hidden="true">info</span>
      <div class="st-notice__text">
        <strong>Status Rekonsiliasi Kehadiran Praktikum</strong>
        <p>{{ summary.absent_count }} siswa berstatus absen sebelum proses koreksi manual admin.</p>
      </div>
      <RouterLink class="st-btnlink" to="/app/corrections"
        >Tinjau di Koreksi Kehadiran →</RouterLink
      >
    </div>

    <UiCard title="Daftar Presensi Peserta Praktikum" :subtitle="`${total} entri`">
      <template #header>
        <div class="reports__tabletools">
          <UiSearchInput
            v-model="tableSearch"
            placeholder="Cari NIS atau Nama Siswa…"
            aria-label="Cari NIS atau nama siswa"
          />
          <details class="st-coltoggle">
            <summary><span class="st-material-icon" aria-hidden="true">tune</span>Kolom</summary>
            <div class="st-coltoggle__panel" role="group" aria-label="Visibilitas kolom">
              <label v-for="c in reportColumns" :key="c.key">
                <input v-model="hiddenCols" type="checkbox" :value="c.key" /> {{ c.label }}
              </label>
            </div>
          </details>
        </div>
      </template>
      <div class="st-tablewrap">
        <table class="st-table reports__table">
          <thead>
            <tr>
              <th v-if="colVisible('session_time')" scope="col">Waktu sesi</th>
              <th v-if="colVisible('student')" scope="col">Siswa</th>
              <th v-if="colVisible('class')" scope="col">Kelas</th>
              <th v-if="colVisible('lab')" scope="col">Laboratorium</th>
              <th v-if="colVisible('subject')" scope="col">Praktikum</th>
              <th v-if="colVisible('teacher')" scope="col">Guru</th>
              <th v-if="colVisible('status')" scope="col">Status</th>
              <th v-if="colVisible('late')" scope="col">Terlambat</th>
              <th v-if="colVisible('note')" scope="col">Catatan</th>
              <th v-if="colVisible('recorded')" scope="col">Waktu tercatat</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="isLoading">
              <td :colspan="visibleColCount"><UiEmptyState title="Memuat laporan…" /></td>
            </tr>
            <tr v-else-if="visibleRows.length === 0">
              <td :colspan="visibleColCount">
                <UiEmptyState title="Tidak ada data untuk filter ini." />
              </td>
            </tr>
            <tr v-for="row in visibleRows" v-else :key="`${row.session_id}-${row.student_id}`">
              <td v-if="colVisible('session_time')" data-label="Waktu sesi" class="st-table__mono">
                {{ formatDate(row.session_opened_at) }}
              </td>
              <td v-if="colVisible('student')" data-label="Siswa">
                <strong>{{ row.student_name }}</strong
                ><span class="st-table__sub">{{ row.student_number }}</span>
              </td>
              <td v-if="colVisible('class')" data-label="Kelas">{{ row.class_name }}</td>
              <td v-if="colVisible('lab')" data-label="Laboratorium">{{ row.laboratory_name }}</td>
              <td v-if="colVisible('subject')" data-label="Praktikum">{{ row.subject }}</td>
              <td v-if="colVisible('teacher')" data-label="Guru">{{ row.teacher_name }}</td>
              <td v-if="colVisible('status')" data-label="Status">
                <UiBadge
                  :tone="
                    row.status === 'present'
                      ? 'present'
                      : row.status === 'late'
                        ? 'late'
                        : row.status === 'absent'
                          ? 'absent'
                          : row.status === 'excused'
                            ? 'excused'
                            : 'neutral'
                  "
                  >{{ statusLabel(row.status) }}</UiBadge
                >
              </td>
              <td v-if="colVisible('late')" data-label="Terlambat">
                <small v-if="minutesLate(row) != null">telat {{ minutesLate(row) }} mnt</small>
                <span v-else class="st-table__muted">-</span>
              </td>
              <td v-if="colVisible('note')" data-label="Catatan">
                <small v-if="row.note">{{ row.note }}</small>
                <span v-else class="st-table__muted">-</span>
              </td>
              <td v-if="colVisible('recorded')" data-label="Waktu tercatat" class="st-table__mono">
                {{ formatDate(row.recorded_at) }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div
        class="master-data__pagination"
        aria-label="Navigasi halaman laporan"
        style="display: flex; justify-content: space-between; align-items: center; margin-top: 12px"
      >
        <span class="st-table__muted">{{
          total === 0
            ? '0 baris'
            : `${page * pageSize + 1}-${Math.min((page + 1) * pageSize, total)} dari ${total}`
        }}</span>
        <div style="display: flex; gap: 8px; align-items: center">
          <UiButton
            variant="secondary"
            type="button"
            :disabled="page === 0 || isLoading"
            @click="goToPage(page - 1)"
            >Sebelumnya</UiButton
          >
          <span class="st-table__muted"
            >Halaman {{ page + 1 }} dari {{ Math.max(1, Math.ceil(total / pageSize)) }}</span
          >
          <UiButton
            variant="secondary"
            type="button"
            :disabled="page + 1 >= Math.max(1, Math.ceil(total / pageSize)) || isLoading"
            @click="goToPage(page + 1)"
            >Berikutnya</UiButton
          >
        </div>
      </div>
    </UiCard>

    <UiCard
      title="Siswa perlu perhatian"
      subtitle="Watchlist dan catatan tindak lanjut dikelola di halaman Peringatan Dini."
      data-testid="ews-panel"
    >
      <template #header>
        <RouterLink class="st-btnlink" to="/app/ews">Buka Peringatan Dini</RouterLink>
      </template>
    </UiCard>
  </div>
</template>
