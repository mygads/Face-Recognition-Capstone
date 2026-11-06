<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { formatDateTime } from '../utils/dateFormat'
import { useAuthStore } from '../stores/auth'
import {
  ApiError,
  closeAttendanceSession,
  decideAttendanceCorrection,
  getAttendanceSessionStatus,
  getOpeningPreference,
  getSessionOpeningPolicy,
  getSessionRoster,
  listAttendanceCorrections,
  listAttendanceSessions,
  listOpenableSchedules,
  markManualAttendance,
  openAttendanceSession,
  requestAttendanceCorrection,
  saveOpeningPreference,
  saveSessionOpeningPolicy,
  type AttendanceCorrectionResponse,
  type AttendanceSession,
  type ManualMarkRequest,
  type OpenableSchedule,
  type SessionOpeningPolicy,
  type SessionOpeningPolicyResponse,
  type SessionRosterEntry,
  type TeacherOpeningPreferenceResponse,
} from '../api/client'

const weekdays = ['Senin', 'Selasa', 'Rabu', 'Kamis', 'Jumat', 'Sabtu', 'Minggu']
const auth = useAuthStore()
const canManagePolicy = computed(() => auth.account?.roles.includes('ADMIN') ?? false)
const isTeacher = computed(() => auth.account?.roles.includes('TEACHER') ?? false)
const schedules = ref<OpenableSchedule[]>([])
const sessions = ref<AttendanceSession[]>([])
const policy = ref<SessionOpeningPolicyResponse | null>(null)
const policyForm = ref<SessionOpeningPolicy>({
  mode: 'manual',
  auto_open_minutes_before: 0,
  auto_open_minutes_after: 15,
  default_grace_period_minutes: 15,
})
const isSavingPolicy = ref(false)
const preference = ref<TeacherOpeningPreferenceResponse | null>(null)
const preferenceMode = ref<'manual' | 'automatic'>('manual')
const isSavingPreference = ref(false)
const preferenceMessage = ref<string | null>(null)
const gracePeriodMinutes = ref(15)
const openingScheduleId = ref<string | null>(null)
const closingSessionId = ref<string | null>(null)
const isLoading = ref(false)
const pageError = ref<string | null>(null)
const successMessage = ref<string | null>(null)
const selected = ref<AttendanceSession | null>(null)
const roster = ref<SessionRosterEntry[]>([])
const isRosterLoading = ref(false)
const rosterError = ref<string | null>(null)
const markDrafts = reactive<
  Record<string, { status: string; note: string; saving: boolean; error: string | null }>
>({})
const manualMarkMessage = ref<string | null>(null)
const corrections = ref<AttendanceCorrectionResponse[]>([])
const correctionsError = ref<string | null>(null)
const isCorrectionsLoading = ref(false)
const correctionDrafts = reactive<
  Record<
    string,
    { corrected_status: string; reason: string; saving: boolean; error: string | null }
  >
>({})
const correctionMessage = ref<string | null>(null)
const isAdmin = computed(() => auth.account?.roles.includes('ADMIN') ?? false)
function correctionDraftFor(key: string): {
  corrected_status: string
  reason: string
  saving: boolean
  error: string | null
} {
  let draft = correctionDrafts[key]
  if (!draft) {
    draft = { corrected_status: 'present', reason: '', saving: false, error: null }
    correctionDrafts[key] = draft
  }
  return draft
}
async function loadCorrections(): Promise<void> {
  if (!selected.value) return
  isCorrectionsLoading.value = true
  correctionsError.value = null
  try {
    const page = await listAttendanceCorrections({ session_id: selected.value.id, limit: 100 })
    corrections.value = page.items
  } catch (error) {
    correctionsError.value = formatError(error)
  } finally {
    isCorrectionsLoading.value = false
  }
}
async function submitCorrectionForRecord(entry: SessionRosterEntry): Promise<void> {
  if (!selected.value || !entry.record_status) return
  const key = 'record-' + entry.student_id
  const draft = correctionDraftFor(key)
  if (!draft.reason.trim()) {
    draft.error = 'Alasan koreksi wajib diisi.'
    return
  }
  const recordId = (entry as unknown as { attendance_record_id?: string }).attendance_record_id
  if (!recordId) {
    draft.error = 'ID record tidak tersedia; muat ulang roster.'
    return
  }
  draft.saving = true
  draft.error = null
  try {
    await requestAttendanceCorrection({
      attendance_record_id: recordId,
      corrected_status: draft.corrected_status as 'present' | 'late' | 'absent' | 'excused',
      reason: draft.reason.trim(),
    })
    correctionMessage.value = 'Pengajuan koreksi untuk ' + entry.full_name + ' dikirim (pending).'
    draft.reason = ''
    await loadCorrections()
  } catch (error) {
    draft.error = formatError(error)
  } finally {
    draft.saving = false
  }
}
async function submitCorrectionForMissing(entry: SessionRosterEntry): Promise<void> {
  if (!selected.value) return
  const key = 'missing-' + entry.student_id
  const draft = correctionDraftFor(key)
  if (!draft.reason.trim()) {
    draft.error = 'Alasan koreksi wajib diisi.'
    return
  }
  draft.saving = true
  draft.error = null
  try {
    await requestAttendanceCorrection({
      session_id: selected.value.id,
      student_id: entry.student_id,
      corrected_status: draft.corrected_status as 'present' | 'late' | 'absent' | 'excused',
      reason: draft.reason.trim(),
    })
    correctionMessage.value =
      'Pengajuan koreksi (siswa tanpa record, dianggap absen) untuk ' +
      entry.full_name +
      ' dikirim (pending).'
    draft.reason = ''
    await loadCorrections()
  } catch (error) {
    draft.error = formatError(error)
  } finally {
    draft.saving = false
  }
}
async function decideCorrection(
  item: AttendanceCorrectionResponse,
  decision: 'approved' | 'rejected',
): Promise<void> {
  try {
    await decideAttendanceCorrection(item.id, { decision })
    correctionMessage.value =
      decision === 'approved' ? 'Koreksi disetujui & diterapkan.' : 'Koreksi ditolak.'
    await loadCorrections()
    if (selected.value) await loadRoster(selected.value.id)
  } catch (error) {
    correctionsError.value = formatError(error)
  }
}

function formatError(error: unknown): string {
  if (error instanceof ApiError) {
    const details = error.details?.map((item) => item.field + ': ' + item.message)
    return details?.length ? details.join(' · ') : error.message
  }
  return 'Permintaan tidak dapat diproses. Coba lagi.'
}

function manualMarkError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.code === 'attendance_already_recorded') {
      return 'Presensi siswa ini sudah tercatat. Muat ulang daftar.'
    }
    if (error.code === 'session_inactive') {
      return 'Sesi sudah ditutup, muat ulang halaman.'
    }
    if (error.code === 'student_not_in_session_roster') {
      return 'Siswa tidak termasuk roster sesi ini.'
    }
    if (error.code === 'student_not_found') {
      return 'Siswa tidak ditemukan.'
    }
    return formatError(error)
  }
  return 'Permintaan tidak dapat diproses. Coba lagi.'
}

function weekdayName(day: number): string {
  return weekdays[day] ?? '—'
}

function displayTime(value: string): string {
  return value.slice(0, 5)
}

function displayDateTime(value: string, timezone: string): string {
  return formatDateTime(value, timezone)
}

function sessionStatusLabel(status: AttendanceSession['status']): string {
  if (status === 'active') return 'Aktif'
  if (status === 'manual_override') return 'Override manual'
  if (status === 'cancelled') return 'Dibatalkan'
  return 'Ditutup'
}

function sessionStatusClass(status: AttendanceSession['status']): string {
  if (status === 'active') return 'status-badge--active'
  if (status === 'manual_override') return 'status-badge--warning'
  return 'status-badge--inactive'
}

function draftFor(studentId: string): {
  status: string
  note: string
  saving: boolean
  error: string | null
} {
  let draft = markDrafts[studentId]
  if (!draft) {
    draft = { status: 'present', note: '', saving: false, error: null }
    markDrafts[studentId] = draft
  }
  return draft
}

const unmarkedRoster = computed(() => roster.value.filter((entry) => entry.record_status === null))

type RosterStatusFilter = 'all' | 'unmarked' | 'present' | 'late' | 'absent' | 'excused'
const rosterSearch = ref('')
const rosterStatusFilter = ref<RosterStatusFilter>('all')

const rosterStatusFilters: { value: RosterStatusFilter; label: string }[] = [
  { value: 'all', label: 'Semua' },
  { value: 'unmarked', label: 'Belum tercatat' },
  { value: 'present', label: 'Hadir' },
  { value: 'late', label: 'Terlambat' },
  { value: 'absent', label: 'Absen' },
  { value: 'excused', label: 'Izin' },
]

const rosterStatusCounts = computed<Record<RosterStatusFilter, number>>(() => {
  const counts: Record<RosterStatusFilter, number> = {
    all: roster.value.length,
    unmarked: 0,
    present: 0,
    late: 0,
    absent: 0,
    excused: 0,
  }
  for (const entry of roster.value) {
    if (entry.record_status === null || entry.record_status === undefined) {
      counts.unmarked += 1
    } else {
      counts[entry.record_status] += 1
    }
  }
  return counts
})

const filteredRoster = computed(() => {
  const query = rosterSearch.value.trim().toLowerCase()
  return roster.value.filter((entry) => {
    if (rosterStatusFilter.value === 'unmarked') {
      if (entry.record_status !== null && entry.record_status !== undefined) return false
    } else if (
      rosterStatusFilter.value !== 'all' &&
      entry.record_status !== rosterStatusFilter.value
    ) {
      return false
    }
    if (!query) return true
    return (
      entry.full_name.toLowerCase().includes(query) ||
      entry.student_number.toLowerCase().includes(query)
    )
  })
})

function rosterStatusLabel(status: SessionRosterEntry['record_status']): string {
  if (status === 'present') return 'Hadir'
  if (status === 'late') return 'Terlambat'
  if (status === 'absent') return 'Absen'
  if (status === 'excused') return 'Izin'
  return 'Belum tercatat'
}

function rosterStatusClass(status: SessionRosterEntry['record_status']): string {
  if (status === 'present') return 'status-badge--active'
  if (status === 'late' || status === 'excused') return 'status-badge--warning'
  return 'status-badge--inactive'
}

async function reload(): Promise<void> {
  isLoading.value = true
  pageError.value = null
  try {
    const [available, page, latestPolicy] = await Promise.all([
      listOpenableSchedules(),
      listAttendanceSessions({ limit: 50, offset: 0 }),
      getSessionOpeningPolicy(),
    ])
    schedules.value = available
    sessions.value = page.items
    policy.value = latestPolicy
    policyForm.value = {
      mode: latestPolicy.mode,
      auto_open_minutes_before: latestPolicy.auto_open_minutes_before,
      auto_open_minutes_after: latestPolicy.auto_open_minutes_after,
      default_grace_period_minutes: latestPolicy.default_grace_period_minutes,
    }
    gracePeriodMinutes.value = latestPolicy.default_grace_period_minutes
    if (isTeacher.value) {
      try {
        preference.value = await getOpeningPreference()
        preferenceMode.value = preference.value.opening_mode
      } catch (error) {
        pageError.value = formatError(error)
      }
    }
  } catch (error) {
    pageError.value = formatError(error)
  } finally {
    isLoading.value = false
  }
}

onMounted(() => void reload())

async function savePolicy(): Promise<void> {
  isSavingPolicy.value = true
  pageError.value = null
  successMessage.value = null
  try {
    policy.value = await saveSessionOpeningPolicy(policyForm.value)
    gracePeriodMinutes.value = policyForm.value.default_grace_period_minutes
    successMessage.value =
      'Jendela buka otomatis dan grace period tersimpan. Mode pembukaan mengikuti pengaturan tiap guru.'
    await reload()
  } catch (error) {
    pageError.value = formatError(error)
  } finally {
    isSavingPolicy.value = false
  }
}

async function savePreference(): Promise<void> {
  isSavingPreference.value = true
  preferenceMessage.value = null
  pageError.value = null
  try {
    preference.value = await saveOpeningPreference({ opening_mode: preferenceMode.value })
    preferenceMessage.value =
      preferenceMode.value === 'automatic'
        ? 'Sesi Anda akan dibuka otomatis dalam jendela jadwal.'
        : 'Sesi Anda dibuka manual dari halaman ini.'
  } catch (error) {
    pageError.value = formatError(error)
  } finally {
    isSavingPreference.value = false
  }
}

async function openSession(schedule: OpenableSchedule): Promise<void> {
  openingScheduleId.value = schedule.id
  pageError.value = null
  successMessage.value = null
  try {
    const created = await openAttendanceSession(schedule.id, gracePeriodMinutes.value)
    successMessage.value =
      created.status === 'manual_override'
        ? 'Sesi ' +
          created.subject +
          ' dibuka sebagai override manual dengan ' +
          created.student_count +
          ' siswa di roster.'
        : 'Sesi ' +
          created.subject +
          ' dibuka dengan ' +
          created.student_count +
          ' siswa di roster.'
    await reload()
  } catch (error) {
    if (error instanceof ApiError && error.code === 'session_already_active') {
      // Race with another opener (or the auto-open worker): the schedule left
      // the openable list on the server, so refresh before telling the teacher.
      await reload()
      if (!pageError.value) {
        pageError.value = 'Sesi untuk jadwal ini sudah dibuka. Daftar dimuat ulang.'
      }
    } else {
      pageError.value = formatError(error)
    }
  } finally {
    openingScheduleId.value = null
  }
}

async function closeSession(item: AttendanceSession): Promise<void> {
  closingSessionId.value = item.id
  pageError.value = null
  try {
    selected.value = await closeAttendanceSession(item.id)
    successMessage.value = 'Sesi ' + item.subject + ' telah ditutup.'
    await reload()
  } catch (error) {
    pageError.value = formatError(error)
  } finally {
    closingSessionId.value = null
  }
}

async function showStatus(item: AttendanceSession): Promise<void> {
  pageError.value = null
  manualMarkMessage.value = null
  try {
    selected.value = await getAttendanceSessionStatus(item.id)
    await loadRoster(item.id)
    await loadCorrections()
  } catch (error) {
    pageError.value = formatError(error)
  }
}

async function loadRoster(sessionId: string): Promise<void> {
  isRosterLoading.value = true
  rosterError.value = null
  try {
    roster.value = await getSessionRoster(sessionId)
    rosterSearch.value = ''
    rosterStatusFilter.value = 'all'
  } catch (error) {
    roster.value = []
    rosterError.value = formatError(error)
  } finally {
    isRosterLoading.value = false
  }
}

async function submitManualMark(entry: SessionRosterEntry): Promise<void> {
  if (!selected.value) return
  const draft = draftFor(entry.student_id)
  if (!['present', 'late', 'absent', 'excused'].includes(draft.status)) {
    draft.error = 'Pilih status kehadiran yang valid.'
    return
  }
  const trimmedNote = draft.note.trim()
  if (trimmedNote.length > 500) {
    draft.error = 'Catatan maksimal 500 karakter.'
    return
  }
  draft.saving = true
  draft.error = null
  manualMarkMessage.value = null
  try {
    const body: ManualMarkRequest = {
      student_id: entry.student_id,
      status: draft.status as ManualMarkRequest['status'],
      ...(trimmedNote ? { note: trimmedNote } : {}),
    }
    await markManualAttendance(selected.value.id, body)
    manualMarkMessage.value = 'Kehadiran ' + entry.full_name + ' ditandai manual.'
    await loadRoster(selected.value.id)
  } catch (error) {
    draft.error = manualMarkError(error)
  } finally {
    draft.saving = false
  }
}
</script>

<template>
  <section class="master-data session-view" aria-label="Sesi presensi">
    <p class="session-view__hint">
      Membuka sesi akan mengambil snapshot roster kelas saat ini. Perubahan roster setelah sesi
      dibuka tidak mengubah daftar peserta sesi tersebut.
    </p>
    <p v-if="pageError" class="master-data__alert" role="alert">{{ pageError }}</p>
    <p v-if="successMessage" class="master-data__success" role="status">{{ successMessage }}</p>

    <section
      v-if="policy"
      class="master-data__panel"
      aria-labelledby="session-policy-title"
      data-testid="session-opening-policy"
    >
      <div class="master-data__panel-heading">
        <div>
          <p class="master-data__eyebrow">Kebijakan sesi</p>
          <h2 id="session-policy-title">Cara membuka presensi</h2>
        </div>
      </div>
      <form class="master-data__form session-view__policy-form" @submit.prevent="savePolicy">
        <label>
          Grace period kehadiran
          <span>
            <input
              v-model.number="policyForm.default_grace_period_minutes"
              type="number"
              min="0"
              max="1440"
              :disabled="!canManagePolicy || isSavingPolicy"
            />
            menit
          </span>
        </label>
        <label>
          Buka sebelum jadwal
          <span>
            <input
              v-model.number="policyForm.auto_open_minutes_before"
              type="number"
              min="0"
              max="15"
              :disabled="!canManagePolicy || isSavingPolicy"
            />
            menit
          </span>
        </label>
        <label>
          Buka setelah jadwal mulai
          <span>
            <input
              v-model.number="policyForm.auto_open_minutes_after"
              type="number"
              min="0"
              max="15"
              :disabled="!canManagePolicy || isSavingPolicy"
            />
            menit
          </span>
        </label>
        <p class="session-view__hint session-view__policy-hint">
          Mode pembukaan global tidak lagi diberlakukan dan dipertahankan hanya untuk
          kompatibilitas. Setiap guru mengatur modenya sendiri pada panel preferensi di bawah;
          backend membuka sesi otomatis hanya untuk guru dengan mode otomatis, dan selalu menutup
          sesi pada akhir jadwal. Grace period dihitung dari jam mulai jadwal untuk sesi otomatis,
          atau dari waktu buka untuk sesi manual.
        </p>
        <div v-if="canManagePolicy" class="master-data__form-actions session-view__policy-actions">
          <button class="button button--primary" type="submit" :disabled="isSavingPolicy">
            {{ isSavingPolicy ? 'Menyimpan…' : 'Simpan kebijakan' }}
          </button>
        </div>
      </form>
    </section>

    <section
      v-if="isTeacher"
      class="master-data__panel"
      aria-labelledby="opening-preference-title"
      data-testid="teacher-opening-preference"
    >
      <div class="master-data__panel-heading">
        <div>
          <p class="master-data__eyebrow">Preferensi guru</p>
          <h2 id="opening-preference-title">Mode pembukaan sesi saya</h2>
        </div>
      </div>
      <form class="master-data__form session-view__policy-form" @submit.prevent="savePreference">
        <label class="session-view__radio">
          <input
            v-model="preferenceMode"
            type="radio"
            value="manual"
            data-testid="opening-mode-manual"
            :disabled="isSavingPreference"
          />
          <span>Saya membuka sesi sendiri (manual)</span>
        </label>
        <label class="session-view__radio">
          <input
            v-model="preferenceMode"
            type="radio"
            value="automatic"
            data-testid="opening-mode-automatic"
            :disabled="isSavingPreference"
          />
          <span>Sesi saya dibuka otomatis sesuai jadwal</span>
        </label>
        <p v-if="preferenceMessage" class="master-data__success" role="status">
          {{ preferenceMessage }}
        </p>
        <div class="master-data__form-actions session-view__policy-actions">
          <button class="button button--primary" type="submit" :disabled="isSavingPreference">
            {{ isSavingPreference ? 'Menyimpan…' : 'Simpan preferensi' }}
          </button>
        </div>
      </form>
      <p class="session-view__hint">
        Admin dapat melihat mode tiap guru di daftar jadwal untuk keperluan operasional.
      </p>
    </section>

    <section class="master-data__panel" aria-labelledby="open-session-title">
      <div class="master-data__panel-heading">
        <div>
          <p class="master-data__eyebrow">Operasional guru</p>
          <h2 id="open-session-title">Jadwal yang dapat dibuka hari ini</h2>
        </div>
        <label class="session-view__grace-period">
          Grace period
          <span>
            <input
              v-model.number="gracePeriodMinutes"
              aria-label="Grace period dalam menit"
              type="number"
              min="0"
              max="1440"
            />
            menit
          </span>
        </label>
      </div>
      <p v-if="policy?.mode === 'automatic'" class="session-view__hint" role="note">
        Pembukaan otomatis aktif untuk guru dengan mode otomatis. Pembukaan manual tetap tersedia
        sebagai jalur override; pembukaan di luar jendela jadwal dicatat sebagai override manual.
      </p>
      <div v-if="schedules.length" class="session-view__schedule-list">
        <article
          v-for="schedule in schedules"
          :key="schedule.id"
          class="session-view__schedule-card"
        >
          <div>
            <p class="session-view__schedule-time">
              {{ weekdayName(schedule.weekday) }} · {{ displayTime(schedule.start_time) }}–{{
                displayTime(schedule.end_time)
              }}
            </p>
            <h3>{{ schedule.subject }}</h3>
            <p>{{ schedule.class_name }} · {{ schedule.laboratory_name }}</p>
            <p class="master-data__muted">Guru: {{ schedule.teacher_name }}</p>
          </div>
          <button
            class="button button--primary"
            :data-testid="'open-session-' + schedule.id"
            :disabled="openingScheduleId !== null"
            @click="openSession(schedule)"
          >
            {{ openingScheduleId === schedule.id ? 'Membuka…' : 'Buka sesi' }}
          </button>
        </article>
      </div>
      <p v-else class="master-data__muted" data-testid="no-openable-schedules">
        Tidak ada jadwal aktif yang dapat dibuka hari ini.
      </p>
    </section>

    <section class="master-data__panel" aria-labelledby="session-list-title">
      <div class="master-data__panel-heading">
        <div>
          <p class="master-data__eyebrow">Runtime presensi</p>
          <h2 id="session-list-title">Sesi terbaru</h2>
        </div>
        <button class="button button--secondary" type="button" @click="reload">Muat ulang</button>
      </div>
      <div class="master-data__table-wrap">
        <table class="master-data__table session-view__table">
          <thead>
            <tr>
              <th scope="col">Praktikum</th>
              <th scope="col">Kelas & laboratorium</th>
              <th scope="col">Dibuka</th>
              <th scope="col">Roster</th>
              <th scope="col">Status</th>
              <th scope="col">Aksi</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="isLoading">
              <td colspan="6" class="master-data__empty">Memuat sesi…</td>
            </tr>
            <tr v-else-if="sessions.length === 0">
              <td colspan="6" class="master-data__empty">Belum ada sesi presensi.</td>
            </tr>
            <tr v-for="item in sessions" v-else :key="item.id">
              <td data-label="Praktikum">
                <strong>{{ item.subject }}</strong>
                <small>{{ item.teacher_name }}</small>
              </td>
              <td data-label="Kelas & laboratorium">
                {{ item.class_name }}
                <small>{{ item.laboratory_name }}</small>
              </td>
              <td data-label="Dibuka">
                {{ displayDateTime(item.opened_at, item.timezone_name) }}
                <small>{{ item.opened_automatically ? 'Otomatis' : 'Manual' }}</small>
              </td>
              <td data-label="Roster">
                {{ item.student_count }} siswa · grace {{ item.grace_period_minutes }} menit
              </td>
              <td data-label="Status">
                <span
                  class="status-badge"
                  :class="sessionStatusClass(item.status)"
                  :data-testid="
                    item.status === 'manual_override' ? 'session-status-override' : undefined
                  "
                  >{{ sessionStatusLabel(item.status) }}</span
                >
              </td>
              <td class="master-data__actions" data-label="Aksi">
                <button class="button button--text" type="button" @click="showStatus(item)">
                  Status
                </button>
                <button
                  v-if="item.status === 'active' || item.status === 'manual_override'"
                  class="button button--text"
                  type="button"
                  :disabled="closingSessionId !== null"
                  @click="closeSession(item)"
                >
                  {{ closingSessionId === item.id ? 'Menutup…' : 'Tutup sesi' }}
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <section v-if="selected" class="master-data__panel" aria-labelledby="session-detail-title">
      <div class="master-data__panel-heading">
        <div>
          <p class="master-data__eyebrow">Status sesi</p>
          <h2 id="session-detail-title">{{ selected.subject }}</h2>
        </div>
        <button class="button button--text" type="button" @click="selected = null">Tutup</button>
      </div>
      <dl class="master-data__details session-view__details">
        <div>
          <dt>Status</dt>
          <dd>{{ sessionStatusLabel(selected.status) }}</dd>
        </div>
        <div>
          <dt>Peserta snapshot</dt>
          <dd>{{ selected.student_count }} siswa</dd>
        </div>
        <div>
          <dt>Grace period</dt>
          <dd>{{ selected.grace_period_minutes }} menit</dd>
        </div>
        <div>
          <dt>Waktu tutup jadwal</dt>
          <dd>{{ displayDateTime(selected.scheduled_end_at, selected.timezone_name) }}</dd>
        </div>
        <div>
          <dt>Guru</dt>
          <dd>{{ selected.teacher_name }}</dd>
        </div>
      </dl>
      <div class="session-view__roster-overview">
        <h3>Roster sesi</h3>
        <p class="session-view__hint">
          Semua peserta snapshot beserta status presensi terakhir, termasuk yang tercatat otomatis
          oleh face recognition.
        </p>
        <div class="session-view__roster-toolbar">
          <label class="session-view__roster-search">
            Cari siswa
            <input
              v-model="rosterSearch"
              type="search"
              placeholder="Nama atau NIS…"
              data-testid="roster-search"
              :disabled="isRosterLoading"
            />
          </label>
          <div class="session-view__roster-filters" role="group" aria-label="Filter status roster">
            <button
              v-for="option in rosterStatusFilters"
              :key="option.value"
              class="session-view__filter-chip"
              :class="{ 'session-view__filter-chip--active': rosterStatusFilter === option.value }"
              type="button"
              :data-testid="'roster-filter-' + option.value"
              :aria-pressed="rosterStatusFilter === option.value"
              @click="rosterStatusFilter = option.value"
            >
              {{ option.label }} ({{ rosterStatusCounts[option.value] }})
            </button>
          </div>
        </div>
        <p v-if="isRosterLoading" class="master-data__muted">Memuat roster…</p>
        <p v-else-if="rosterError" class="master-data__alert" role="alert">{{ rosterError }}</p>
        <p v-else-if="filteredRoster.length === 0" class="master-data__muted">
          Tidak ada siswa yang cocok dengan pencarian atau filter.
        </p>
        <div v-else class="master-data__table-wrap">
          <table class="master-data__table session-view__table" data-testid="roster-table">
            <thead>
              <tr>
                <th scope="col">Siswa</th>
                <th scope="col">Status</th>
                <th scope="col">Waktu / Terlambat</th>
                <th scope="col">Catatan</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="entry in filteredRoster" :key="entry.student_id" data-testid="roster-row">
                <td data-label="Siswa">
                  {{ entry.full_name }}
                  <small>{{ entry.student_number }}</small>
                </td>
                <td data-label="Status">
                  <span class="status-badge" :class="rosterStatusClass(entry.record_status)">{{
                    rosterStatusLabel(entry.record_status)
                  }}</span>
                  <span
                    v-if="entry.record_status === 'late'"
                    class="status-badge status-badge--warning"
                    data-testid="late-watermark"
                    >TERLAMBAT</span
                  >
                </td>
                <td data-label="Waktu / Terlambat">
                  <small v-if="entry.recorded_at">{{ entry.recorded_at }}</small>
                  <small v-else class="master-data__muted">–</small>
                  <small v-if="entry.minutes_late != null">
                    · telat {{ entry.minutes_late }} mnt</small
                  >
                </td>
                <td data-label="Catatan">
                  <small v-if="entry.record_note">{{ entry.record_note }}</small>
                  <span v-else class="master-data__muted">–</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
      <div class="session-view__manual-marks">
        <h3>Presensi manual vs koreksi — bedanya</h3>
        <p class="session-view__hint">
          <strong>Manual:</strong> membuat catatan awal untuk siswa roster yang <em>belum</em> punya
          record dan sesi masih berjalan. <strong>Koreksi:</strong> memperbaiki record yang
          <em>sudah terlanjur final</em> (salah kenali, harusnya late/izin, salah klik) atau siswa
          yang <em>dianggap absen karena tanpa record</em> setelah sesi ditutup. Koreksi selalu
          butuh alasan, berstatus pending, dan hanya ADMIN yang memutuskan.
        </p>
        <h3>Tandai kehadiran manual</h3>
        <p class="session-view__hint">
          Hanya untuk siswa roster yang belum memiliki catatan presensi. Pilihan guru langsung
          menjadi status akhir tanpa ambang batas otomatis.
        </p>
        <p v-if="manualMarkMessage" class="master-data__success" role="status">
          {{ manualMarkMessage }}
        </p>
        <p v-if="isRosterLoading" class="master-data__muted">Memuat roster…</p>
        <p v-else-if="rosterError" class="master-data__alert" role="alert">{{ rosterError }}</p>
        <p v-else-if="unmarkedRoster.length === 0" class="master-data__muted">
          Semua siswa roster sudah memiliki catatan presensi.
        </p>
        <ul v-else class="session-view__manual-list">
          <li
            v-for="entry in unmarkedRoster"
            :key="entry.student_id"
            class="session-view__manual-item"
          >
            <div>
              <strong>{{ entry.full_name }}</strong>
              <small>{{ entry.student_number }}</small>
            </div>
            <label>
              Status
              <select
                v-model="draftFor(entry.student_id).status"
                :disabled="draftFor(entry.student_id).saving"
                :aria-label="'Status untuk ' + entry.full_name"
              >
                <option value="present">Hadir</option>
                <option value="late">Terlambat</option>
                <option value="absent">Absen</option>
                <option value="excused">Izin</option>
              </select>
            </label>
            <label>
              Catatan (opsional)
              <input
                v-model="draftFor(entry.student_id).note"
                type="text"
                maxlength="500"
                placeholder="Alasan atau keterangan"
                :disabled="draftFor(entry.student_id).saving"
                :aria-label="'Catatan untuk ' + entry.full_name"
              />
            </label>
            <button
              class="button button--secondary"
              type="button"
              :disabled="draftFor(entry.student_id).saving"
              :data-testid="'manual-mark-' + entry.student_id"
              @click="submitManualMark(entry)"
            >
              {{ draftFor(entry.student_id).saving ? 'Menyimpan…' : 'Tandai manual' }}
            </button>
            <p v-if="draftFor(entry.student_id).error" class="master-data__alert" role="alert">
              {{ draftFor(entry.student_id).error }}
            </p>
          </li>
        </ul>
      </div>
      <div class="session-view__manual-marks" data-testid="correction-panel">
        <h3>Pengajuan koreksi kehadiran</h3>
        <p class="session-view__hint">
          Pilih status sebelumnya (otomatis), status yang diminta, dan alasan. Untuk siswa yang
          sudah punya record: koreksi record. Untuk siswa tanpa record setelah sesi ditutup: ajukan
          sebagai absen → status yang diminta.
        </p>
        <p v-if="correctionMessage" class="master-data__success" role="status">
          {{ correctionMessage }}
        </p>
        <p v-if="correctionsError" class="master-data__alert" role="alert">
          {{ correctionsError }}
        </p>
        <ul class="session-view__manual-list">
          <li
            v-for="entry in roster"
            :key="'corr-' + entry.student_id"
            class="session-view__manual-item"
          >
            <div>
              <strong>{{ entry.full_name }}</strong>
              <small
                >{{ entry.student_number }} · sebelumnya:
                {{ entry.record_status ?? 'absen (tanpa record)' }}</small
              >
            </div>
            <label>
              Status diminta
              <select
                v-model="
                  correctionDraftFor(
                    (entry.record_status ? 'record-' : 'missing-') + entry.student_id,
                  ).corrected_status
                "
              >
                <option value="present">Hadir</option>
                <option value="late">Terlambat</option>
                <option value="absent">Absen</option>
                <option value="excused">Izin</option>
              </select>
            </label>
            <label>
              Alasan (wajib)
              <input
                v-model="
                  correctionDraftFor(
                    (entry.record_status ? 'record-' : 'missing-') + entry.student_id,
                  ).reason
                "
                type="text"
                maxlength="2000"
                placeholder="Contoh: wajah salah kenali / ada surat izin"
              />
            </label>
            <button
              v-if="entry.record_status"
              class="button button--secondary"
              type="button"
              :disabled="correctionDraftFor('record-' + entry.student_id).saving"
              :data-testid="'correction-record-' + entry.student_id"
              @click="submitCorrectionForRecord(entry)"
            >
              Ajukan koreksi
            </button>
            <button
              v-else
              class="button button--secondary"
              type="button"
              :disabled="correctionDraftFor('missing-' + entry.student_id).saving"
              :data-testid="'correction-missing-' + entry.student_id"
              @click="submitCorrectionForMissing(entry)"
            >
              Ajukan koreksi (tanpa record)
            </button>
            <p
              v-if="
                correctionDraftFor(
                  (entry.record_status ? 'record-' : 'missing-') + entry.student_id,
                ).error
              "
              class="master-data__alert"
              role="alert"
            >
              {{
                correctionDraftFor(
                  (entry.record_status ? 'record-' : 'missing-') + entry.student_id,
                ).error
              }}
            </p>
          </li>
        </ul>
        <h3>Daftar pengajuan koreksi</h3>
        <p v-if="isCorrectionsLoading" class="master-data__muted">Memuat koreksi…</p>
        <ul v-else-if="corrections.length" class="session-view__manual-list">
          <li v-for="c in corrections" :key="c.id" class="session-view__manual-item">
            <div>
              <strong>{{ c.student_id }}</strong>
              <small
                >{{ c.previous_status }} → {{ c.corrected_status }} · {{ c.decision_status }} ·
                {{ c.reason }}</small
              >
            </div>
            <div v-if="isAdmin && c.decision_status === 'pending'">
              <button
                class="button button--primary"
                type="button"
                :data-testid="'correction-approve-' + c.id"
                @click="decideCorrection(c, 'approved')"
              >
                Setujui &amp; terapkan
              </button>
              <button
                class="button button--secondary"
                type="button"
                :data-testid="'correction-reject-' + c.id"
                @click="decideCorrection(c, 'rejected')"
              >
                Tolak
              </button>
            </div>
            <small v-else>{{ c.decision_status }}</small>
          </li>
        </ul>
        <p v-else class="master-data__muted">Belum ada pengajuan koreksi untuk sesi ini.</p>
      </div>
    </section>
  </section>
</template>
