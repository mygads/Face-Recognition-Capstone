<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import {
  ApiError,
  createEwsFollowUp,
  downloadAttendanceReport,
  getAttendanceReportSummary,
  listAttendanceReportRows,
  listAtRiskStudents,
  listAttendanceSessions,
  listEwsFollowUps,
  listSchedules,
  type AttendanceReportQuery,
  type AttendanceReportRow,
  type AttendanceReportSummary,
  type AtRiskPage,
  type AttendanceSession,
  type EwsFollowUp,
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
const atRisk = ref<AtRiskPage | null>(null)
const atRiskError = ref<string | null>(null)
const followUps = ref<Record<string, EwsFollowUp[]>>({})
const followUpDrafts = ref<Record<string, string>>({})
const followUpError = ref<string | null>(null)
function minutesLate(row: AttendanceReportRow): number | null {
  if (row.status !== 'late' || !row.recorded_at) return null
  const start = new Date(row.session_opened_at).getTime()
  const rec = new Date(row.recorded_at).getTime()
  if (Number.isNaN(start) || Number.isNaN(rec)) return null
  return Math.max(0, Math.round((rec - start) / 60000))
}
async function loadAtRisk(): Promise<void> {
  try {
    atRisk.value = await listAtRiskStudents({ limit: 25, offset: 0 })
  } catch (error) {
    atRiskError.value = formatError(error)
  }
}
async function loadFollowUps(studentId: string): Promise<void> {
  try {
    followUps.value[studentId] = await listEwsFollowUps(studentId)
  } catch (error) {
    followUpError.value = formatError(error)
  }
}
async function submitFollowUp(studentId: string): Promise<void> {
  const note = (followUpDrafts.value[studentId] ?? '').trim()
  if (!note) {
    followUpError.value = 'Catatan tindak lanjut tidak boleh kosong.'
    return
  }
  try {
    const created = await createEwsFollowUp(studentId, note)
    followUpDrafts.value[studentId] = ''
    followUps.value[studentId] = [created, ...(followUps.value[studentId] ?? [])]
  } catch (error) {
    followUpError.value = formatError(error)
  }
}
const summary = ref<AttendanceReportSummary | null>(null)
const rows = ref<AttendanceReportRow[]>([])
const total = ref(0)
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

function statusLabel(status: AttendanceReportRow['status']): string {
  return {
    present: 'Hadir',
    late: 'Terlambat',
    absent: 'Absen',
    excused: 'Izin',
    not_recorded: 'Belum tercatat',
  }[status]
}

function statusClass(status: AttendanceReportRow['status']): string {
  return `reports__status--${status}`
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
  await Promise.all([loadOptions(), applyFilters(), loadAtRisk()])
})
</script>

<template>
  <section class="master-data reports-view" aria-label="Laporan kehadiran">
    <div class="reports__actions">
      <p class="schedule-view__hint">
        Filter data presensi per siswa dan sesi, lalu unduh rekap untuk dokumentasi.
      </p>
      <div>
        <button
          class="button button--secondary"
          type="button"
          :disabled="!summary || downloading !== null"
          data-testid="export-csv"
          @click="exportReport('csv')"
        >
          {{ downloading === 'csv' ? 'Menyiapkan CSV…' : 'Unduh CSV' }}
        </button>
        <button
          class="button button--primary"
          type="button"
          :disabled="!summary || downloading !== null"
          data-testid="export-xlsx"
          @click="exportReport('xlsx')"
        >
          {{ downloading === 'xlsx' ? 'Menyiapkan XLSX…' : 'Unduh XLSX' }}
        </button>
      </div>
    </div>

    <form class="reports__filters" aria-label="Filter laporan" @submit.prevent="applyFilters">
      <label>
        <span>Mulai tanggal</span>
        <input v-model="filters.starts_on" type="date" required />
      </label>
      <label>
        <span>Sampai tanggal</span>
        <input v-model="filters.ends_on" type="date" required :min="filters.starts_on" />
      </label>
      <label>
        <span>Siswa · NIS/NISN</span>
        <input
          v-model="filters.student_number"
          aria-label="Filter siswa"
          type="search"
          maxlength="32"
          placeholder="Masukkan NIS/NISN"
        />
      </label>
      <label>
        <span>Kelas</span>
        <select v-model="filters.class_id" aria-label="Filter kelas">
          <option value="">Semua kelas</option>
          <option
            v-for="schedule in classOptions"
            :key="schedule.class_id"
            :value="schedule.class_id"
          >
            {{ schedule.class_name }}
          </option>
        </select>
      </label>
      <label>
        <span>Laboratorium</span>
        <select v-model="filters.laboratory_id" aria-label="Filter laboratorium">
          <option value="">Semua laboratorium</option>
          <option
            v-for="schedule in laboratoryOptions"
            :key="schedule.laboratory_id"
            :value="schedule.laboratory_id"
          >
            {{ schedule.laboratory_name }}
          </option>
        </select>
      </label>
      <label>
        <span>Sesi</span>
        <select v-model="filters.session_id" aria-label="Filter sesi">
          <option value="">Semua sesi</option>
          <option v-for="session in sessions" :key="session.id" :value="session.id">
            {{ sessionLabel(session) }}
          </option>
        </select>
      </label>
      <label>
        <span>Status</span>
        <select v-model="filters.status" aria-label="Filter status">
          <option value="">Semua status</option>
          <option value="present">Hadir</option>
          <option value="late">Terlambat</option>
          <option value="absent">Absen</option>
          <option value="excused">Izin</option>
          <option value="not_recorded">Belum tercatat</option>
        </select>
      </label>
      <div class="reports__filter-actions">
        <button class="button button--secondary" type="button" @click="resetFilters">
          Atur ulang
        </button>
        <button class="button button--primary" type="submit" :disabled="isLoading">
          {{ isLoading ? 'Memuat…' : 'Terapkan filter' }}
        </button>
      </div>
    </form>

    <p v-if="errorMessage" class="master-data__alert" role="alert">{{ errorMessage }}</p>

    <section v-if="summary" class="reports__summary" aria-label="Ringkasan kehadiran">
      <article class="reports__metric">
        <span>Total siswa-sesi</span>
        <strong>{{ summary.total_rows }}</strong>
      </article>
      <article class="reports__metric">
        <span>Hadir</span>
        <strong>{{ summary.present_count }}</strong>
      </article>
      <article class="reports__metric">
        <span>Terlambat</span>
        <strong>{{ summary.late_count }}</strong>
      </article>
      <article class="reports__metric">
        <span>Absen</span>
        <strong>{{ summary.absent_count }}</strong>
      </article>
      <article class="reports__metric">
        <span>Belum tercatat</span>
        <strong>{{ summary.not_recorded_count }}</strong>
      </article>
    </section>

    <div class="master-data__table-wrap">
      <table class="master-data__table reports__table">
        <thead>
          <tr>
            <th scope="col">Waktu sesi</th>
            <th scope="col">Siswa</th>
            <th scope="col">Kelas</th>
            <th scope="col">Laboratorium</th>
            <th scope="col">Praktikum</th>
            <th scope="col">Guru</th>
            <th scope="col">Status</th>
            <th scope="col">Terlambat</th>
            <th scope="col">Catatan</th>
            <th scope="col">Waktu tercatat</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="isLoading">
            <td colspan="10" class="master-data__empty">Memuat laporan…</td>
          </tr>
          <tr v-else-if="rows.length === 0">
            <td colspan="10" class="master-data__empty">Tidak ada data untuk filter ini.</td>
          </tr>
          <tr v-for="row in rows" v-else :key="`${row.session_id}-${row.student_id}`">
            <td data-label="Waktu sesi">{{ formatDate(row.session_opened_at) }}</td>
            <td data-label="Siswa">
              <strong>{{ row.student_name }}</strong>
              <small>{{ row.student_number }}</small>
            </td>
            <td data-label="Kelas">{{ row.class_name }}</td>
            <td data-label="Laboratorium">{{ row.laboratory_name }}</td>
            <td data-label="Praktikum">{{ row.subject }}</td>
            <td data-label="Guru">{{ row.teacher_name }}</td>
            <td data-label="Status">
              <span class="reports__status" :class="statusClass(row.status)">
                {{ statusLabel(row.status) }}
              </span>
              <span
                v-if="row.status === 'late'"
                class="reports__status reports__status--late"
                data-testid="late-watermark"
                >TERLAMBAT</span
              >
            </td>
            <td data-label="Terlambat">
              <small v-if="minutesLate(row) != null">telat {{ minutesLate(row) }} mnt</small>
              <span v-else class="master-data__muted">–</span>
            </td>
            <td data-label="Catatan">
              <small v-if="row.note">{{ row.note }}</small>
              <span v-else class="master-data__muted">–</span>
            </td>
            <td data-label="Waktu tercatat">{{ formatDate(row.recorded_at) }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <section class="master-data__panel" aria-label="EWS tahap 1" data-testid="ews-panel">
      <div class="master-data__panel-heading">
        <div>
          <p class="master-data__eyebrow">EWS tahap 1 · watchlist</p>
          <h2>Siswa perlu perhatian + tindak lanjut</h2>
        </div>
        <button class="button button--secondary" type="button" @click="loadAtRisk">
          Muat ulang watchlist
        </button>
      </div>
      <p class="accounts-view__hint">
        Watchlist bukan sanksi dan tidak memblokir presensi. Klik siswa untuk melihat riwayat di
        tabel di atas (filter NIS), lalu tulis catatan tindak lanjut. Tahap 1 tanpa notifikasi /
        eskalasi otomatis.
      </p>
      <p v-if="atRiskError" class="master-data__alert" role="alert">{{ atRiskError }}</p>
      <ul v-else-if="atRisk && atRisk.items.length" class="accounts-view__list">
        <li
          v-for="item in atRisk.items"
          :key="item.student_id"
          class="accounts-view__row"
          data-testid="ews-row"
        >
          <div>
            <strong>{{ item.full_name }}</strong>
            <small
              >{{ item.student_number }} · {{ item.class_name }} · absen {{ item.absence_pct }}% ·
              terlambat {{ item.late_count }}x</small
            >
            <div>
              <button
                class="button button--text"
                type="button"
                @click="loadFollowUps(item.student_id)"
              >
                Lihat / tambah tindak lanjut
              </button>
            </div>
            <ul v-if="followUps[item.student_id]?.length">
              <li v-for="f in followUps[item.student_id]" :key="f.id">
                <small>{{ f.created_at }} — {{ f.author_name }}: {{ f.note }}</small>
              </li>
            </ul>
            <form @submit.prevent="submitFollowUp(item.student_id)">
              <input
                v-model="followUpDrafts[item.student_id]"
                type="text"
                maxlength="2000"
                placeholder="Tulis tindak lanjut, mis. panggil orang tua / bimbingan"
                :aria-label="'Tindak lanjut untuk ' + item.full_name"
              />
              <button class="button button--secondary" type="submit">Simpan catatan</button>
            </form>
          </div>
        </li>
      </ul>
      <p v-else class="accounts-view__hint">Belum ada siswa yang perlu perhatian.</p>
      <p v-if="followUpError" class="master-data__alert" role="alert">{{ followUpError }}</p>
    </section>
    <div class="master-data__pagination" aria-label="Navigasi halaman laporan">
      <span>{{
        total === 0
          ? '0 baris'
          : `${page * pageSize + 1}–${Math.min((page + 1) * pageSize, total)} dari ${total}`
      }}</span>
      <div>
        <button
          class="button button--secondary"
          type="button"
          :disabled="page === 0 || isLoading"
          @click="goToPage(page - 1)"
        >
          Sebelumnya
        </button>
        <span>Halaman {{ page + 1 }} dari {{ Math.max(1, Math.ceil(total / pageSize)) }}</span>
        <button
          class="button button--secondary"
          type="button"
          :disabled="page + 1 >= Math.max(1, Math.ceil(total / pageSize)) || isLoading"
          @click="goToPage(page + 1)"
        >
          Berikutnya
        </button>
      </div>
    </div>
  </section>
</template>
