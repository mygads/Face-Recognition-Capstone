<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import UiAvatar from '../components/ui/UiAvatar.vue'
import UiBadge from '../components/ui/UiBadge.vue'
import UiButton from '../components/ui/UiButton.vue'
import UiCard from '../components/ui/UiCard.vue'
import UiField from '../components/ui/UiField.vue'
import UiInput from '../components/ui/UiInput.vue'
import UiModal from '../components/ui/UiModal.vue'
import UiPageHeader from '../components/ui/UiPageHeader.vue'
import { attendanceStatusLabel, correctionDecisionLabel } from '../utils/attendanceStatus'
import { formatApiError } from '../utils/apiError'
import UiSearchInput from '../components/ui/UiSearchInput.vue'
import UiSelect from '../components/ui/UiSelect.vue'
import { useRoute } from 'vue-router'
import { formatDateTime } from '../utils/dateFormat'
import { useAuthStore } from '../stores/auth'
import {
  ApiError,
  closeAttendanceSession,
  decideAttendanceCorrection,
  getAttendanceSessionStatus,
  getSessionOpeningPolicy,
  getSessionRoster,
  listAttendanceCorrections,
  listAttendanceSessions,
  listOpenableSchedules,
  markManualAttendance,
  openAttendanceSession,
  requestAttendanceCorrection,
  saveSessionOpeningPolicy,
  type AttendanceCorrectionResponse,
  type AttendanceSession,
  type ManualMarkRequest,
  type OpenableSchedule,
  type SessionOpeningPolicy,
  type SessionOpeningPolicyResponse,
  type SessionRosterEntry,
} from '../api/client'

const weekdays = ['Senin', 'Selasa', 'Rabu', 'Kamis', 'Jumat', 'Sabtu', 'Minggu']
const auth = useAuthStore()
const route = useRoute() as unknown as { params: Record<string, unknown> } | undefined
const canManagePolicy = computed(() => auth.account?.roles.includes('ADMIN') ?? false)
const isTeacher = computed(() => auth.account?.roles.includes('TEACHER') ?? false)
const isLaborant = computed(
  () => !isAdmin.value && (auth.account?.roles ?? []).includes('LABORANT'),
)
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
const staffPermissions = computed(() => (auth.account?.permissions ?? []) as string[])
const canOperateSessions = computed(
  () => isAdmin.value || isTeacher.value || staffPermissions.value.includes('session_operate'),
)
const canManualMark = computed(
  () => isAdmin.value || isTeacher.value || staffPermissions.value.includes('attendance_manual'),
)
const canProposeCorrection = computed(
  () => isAdmin.value || isTeacher.value || staffPermissions.value.includes('attendance_correct'),
)
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
const decisionNotes = reactive<Record<string, string>>({})

async function decideCorrection(
  item: AttendanceCorrectionResponse,
  decision: 'approved' | 'rejected',
): Promise<void> {
  const note = (decisionNotes[item.id] ?? '').trim()
  if (decision === 'rejected' && !note) {
    correctionsError.value = 'Alasan penolakan wajib diisi pada catatan keputusan.'
    return
  }
  try {
    await decideAttendanceCorrection(item.id, { decision, decision_note: note || null })
    correctionMessage.value =
      decision === 'approved' ? 'Koreksi disetujui & diterapkan.' : 'Koreksi ditolak.'
    await loadCorrections()
    if (selected.value) await loadRoster(selected.value.id)
  } catch (error) {
    correctionsError.value = formatError(error)
  }
}

function formatError(error: unknown): string {
  return formatApiError(error, 'Permintaan tidak dapat diproses. Coba lagi.')
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
  return weekdays[day] ?? '-'
}

function displayTime(value: string): string {
  return value.slice(0, 5)
}

function sessionOpenTime(item: { opened_at: string; timezone_name: string }): string {
  const parsed = new Date(item.opened_at)
  if (Number.isNaN(parsed.getTime())) return displayTime(item.opened_at.slice(11, 16))
  return parsed.toLocaleTimeString('id-ID', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
    timeZone: item.timezone_name || 'Asia/Jakarta',
  })
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

function correctionErrorFor(entry: SessionRosterEntry): string | null {
  const key = (entry.record_status ? 'record-' : 'missing-') + entry.student_id
  return correctionDraftFor(key).error
}

function rosterName(studentId: string | null | undefined): string {
  if (!studentId) return '-'
  return (
    roster.value.find((entry) => entry.student_id === studentId)?.full_name ?? studentId.slice(0, 8)
  )
}

function rosterStatusLabel(status: SessionRosterEntry['record_status']): string {
  if (status === 'present') return 'Hadir'
  if (status === 'late') return 'Terlambat'
  if (status === 'absent') return 'Absen'
  if (status === 'excused') return 'Izin'
  return 'Belum tercatat'
}

const activeSessions = computed(() =>
  sessions.value.filter((item) => item.status === 'active' || item.status === 'manual_override'),
)
const historySessions = computed(() =>
  sessions.value.filter((item) => item.status !== 'active' && item.status !== 'manual_override'),
)
const closingSession = computed(
  () => sessions.value.find((item) => item.id === confirmCloseId.value) ?? null,
)
const closeUnmarked = computed(() => {
  if (closingSession.value && selected.value?.id === closingSession.value.id) {
    return roster.value.filter((entry) => entry.record_status === null).length
  }
  return confirmUnmarked.value ?? 0
})
const closePresent = computed(() => {
  if (closingSession.value && selected.value?.id === closingSession.value.id) {
    return roster.value.filter((entry) => entry.record_status === 'present').length
  }
  return 0
})
const closeLate = computed(() => {
  if (closingSession.value && selected.value?.id === closingSession.value.id) {
    return roster.value.filter((entry) => entry.record_status === 'late').length
  }
  return 0
})
const closeAbsent = computed(() => {
  if (!closingSession.value) return 0
  const total = closingSession.value.student_count
  if (selected.value?.id === closingSession.value.id && roster.value.length) {
    const known = roster.value.filter(
      (entry) => entry.record_status === 'present' || entry.record_status === 'late',
    ).length
    return Math.max(0, total - known)
  }
  return 0
})

const liveRoster = ref<Record<string, { present: number; late: number; total: number }>>({})

async function refreshLiveRoster(items: AttendanceSession[]): Promise<void> {
  const next: Record<string, { present: number; late: number; total: number }> = {}
  await Promise.all(
    items.map(async (item) => {
      try {
        const entries = await getSessionRoster(item.id)
        let present = 0
        let late = 0
        for (const e of entries) {
          if (e.record_status === 'present') present += 1
          else if (e.record_status === 'late') late += 1
        }
        next[item.id] = { present, late, total: entries.length || item.student_count }
      } catch {
        /* panel live roster disembunyikan bila gagal dimuat */
      }
    }),
  )
  liveRoster.value = next
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
    void refreshLiveRoster(
      page.items.filter((s) => s.status !== 'closed' && s.status !== 'cancelled'),
    )
    policy.value = latestPolicy
    policyForm.value = {
      mode: latestPolicy.mode,
      auto_open_minutes_before: latestPolicy.auto_open_minutes_before,
      auto_open_minutes_after: latestPolicy.auto_open_minutes_after,
      default_grace_period_minutes: latestPolicy.default_grace_period_minutes,
    }
    gracePeriodMinutes.value = latestPolicy.default_grace_period_minutes
  } catch (error) {
    pageError.value = formatError(error)
  } finally {
    isLoading.value = false
  }
}

onMounted(async () => {
  await reload()
  // Route detail (/app/sessions/:sessionId) harus bisa dibuka ulang langsung:
  // pilih sesi dari URL bila tersedia.
  const rawSessionId = route?.params.sessionId
  const routeSessionId = typeof rawSessionId === 'string' ? rawSessionId : ''
  if (routeSessionId) {
    const match = sessions.value.find((item) => item.id === routeSessionId)
    if (match) await showStatus(match)
  }
})

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

function askOpenSession(schedule: OpenableSchedule): void {
  pageError.value = null
  confirmOpenSchedule.value = schedule
}

async function confirmOpenSession(): Promise<void> {
  const schedule = confirmOpenSchedule.value
  confirmOpenSchedule.value = null
  if (schedule) await openSession(schedule)
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

const confirmOpenSchedule = ref<OpenableSchedule | null>(null)
const confirmCloseId = ref<string | null>(null)
const confirmUnmarked = ref<number | null>(null)

async function askClose(item: AttendanceSession): Promise<void> {
  confirmCloseId.value = item.id
  confirmUnmarked.value = null
  try {
    if (selected.value?.id !== item.id) {
      selected.value = await getAttendanceSessionStatus(item.id)
      await loadRoster(item.id)
    }
    confirmUnmarked.value = roster.value.filter((entry) => entry.record_status === null).length
  } catch {
    confirmUnmarked.value = null
  }
}

async function closeSession(item: AttendanceSession): Promise<void> {
  closingSessionId.value = item.id
  pageError.value = null
  confirmCloseId.value = null
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
  <div class="st-page">
    <UiPageHeader
      title="Sesi Presensi"
      description="Kelola sesi presensi praktikum: yang sedang berjalan, siap dibuka hari ini, dan riwayat sesi."
    >
      <template #actions>
        <UiButton variant="secondary" @click="reload">Muat ulang</UiButton>
      </template>
    </UiPageHeader>

    <p v-if="pageError" class="st-alert st-alert--error" role="alert">{{ pageError }}</p>
    <p v-if="successMessage" class="st-alert st-alert--success" role="status">
      {{ successMessage }}
    </p>

    <div v-if="policy" class="st-card" data-testid="session-opening-policy">
      <h2 class="st-card__title">Cara membuka presensi</h2>
      <form @submit.prevent="savePolicy">
        <div class="st-grid3">
          <UiField label="Grace period kehadiran (menit)">
            <UiInput
              :model-value="String(policyForm.default_grace_period_minutes)"
              type="number"
              :disabled="!canManagePolicy || isSavingPolicy"
              @update:model-value="policyForm.default_grace_period_minutes = Number($event)"
            />
          </UiField>
          <UiField label="Buka sebelum jadwal (menit)">
            <UiInput
              :model-value="String(policyForm.auto_open_minutes_before)"
              type="number"
              :disabled="!canManagePolicy || isSavingPolicy"
              @update:model-value="policyForm.auto_open_minutes_before = Number($event)"
            />
          </UiField>
          <UiField label="Buka setelah jadwal mulai (menit)">
            <UiInput
              :model-value="String(policyForm.auto_open_minutes_after)"
              type="number"
              :disabled="!canManagePolicy || isSavingPolicy"
              @update:model-value="policyForm.auto_open_minutes_after = Number($event)"
            />
          </UiField>
        </div>
        <p class="st-table__muted">
          Mode pembukaan global tidak lagi diberlakukan. Setiap guru mengatur modenya sendiri di
          Profil dan Preferensi; backend membuka sesi otomatis hanya untuk guru dengan mode
          otomatis.
        </p>
        <p v-if="canManagePolicy">
          <UiButton variant="primary" type="submit" :disabled="isSavingPolicy">
            {{ isSavingPolicy ? 'Menyimpan…' : 'Simpan kebijakan' }}
          </UiButton>
        </p>
      </form>
    </div>

    <div v-if="isTeacher" class="st-card" data-testid="teacher-opening-preference">
      <h2 class="st-card__title">Mode pembukaan sesi saya</h2>
      <p class="st-table__muted">
        Pilihan mode (“Saya membuka sesi sendiri” / “Sesi saya dibuka otomatis sesuai jadwal”)
        dikelola di <RouterLink to="/app/profile">Profil &amp; Preferensi</RouterLink>.
      </p>
    </div>

    <!-- Siap dibuka hari ini -->
    <section aria-labelledby="openable-title">
      <div class="st-sectionrow">
        <h2 id="openable-title" class="st-section">Siap Dibuka Hari Ini</h2>
        <p class="st-table__muted">Jadwal terverifikasi · kamera siaga</p>
      </div>
      <div class="st-toolbar">
        <UiField label="Grace period (menit)">
          <UiInput
            :model-value="String(gracePeriodMinutes)"
            type="number"
            aria-label="Grace period dalam menit"
            @update:model-value="gracePeriodMinutes = Number($event)"
          />
        </UiField>
      </div>
      <div v-if="schedules.length" class="st-grid2">
        <article v-for="schedule in schedules" :key="schedule.id" class="st-card st-schedule">
          <div class="st-schedule__time">
            <strong>{{ displayTime(schedule.start_time) }}</strong>
            <small>sampai</small>
            <strong>{{ displayTime(schedule.end_time) }} WIB</strong>
          </div>
          <div class="st-schedule__main">
            <div class="st-schedule__tags">
              <UiBadge tone="info">{{ weekdayName(schedule.weekday) }}</UiBadge>
              <UiBadge tone="neutral">Menunggu Pembukaan</UiBadge>
            </div>
            <h3 class="st-card__title">{{ schedule.subject }}</h3>
            <p class="st-table__muted">
              {{ schedule.class_name }} · {{ schedule.laboratory_name }} ·
              {{ schedule.teacher_name }}
            </p>
            <p v-if="canOperateSessions">
              <UiButton
                variant="primary"
                :data-testid="'open-session-' + schedule.id"
                :disabled="openingScheduleId !== null"
                @click="askOpenSession(schedule)"
              >
                <span class="st-material-icon" aria-hidden="true">door_open</span
                >{{ openingScheduleId === schedule.id ? 'Membuka…' : 'Buka Sesi Presensi' }}
              </UiButton>
            </p>
            <p v-else class="st-table__muted">
              Membutuhkan izin Operasikan Sesi untuk membuka pertemuan ini.
            </p>
            <p class="st-table__muted">Aktivasi pemindaian wajah &amp; log kehadiran otomatis.</p>
          </div>
        </article>
      </div>
      <p v-else class="st-table__muted" data-testid="no-openable-schedules">
        Tidak ada jadwal aktif yang dapat dibuka hari ini.
      </p>
    </section>

    <!-- Sedang berlangsung -->
    <section aria-labelledby="active-title">
      <div class="st-sectionrow">
        <h2 id="active-title" class="st-section">Sedang Berlangsung</h2>
        <p class="st-table__muted">Real-time sinkronisasi kamera laboratorium</p>
      </div>
      <div v-if="activeSessions.length" class="st-grid2">
        <article v-for="item in activeSessions" :key="item.id" class="st-card st-session-live">
          <div class="st-session-live__main">
            <div class="st-schedule__tags">
              <UiBadge tone="present">Sesi Aktif</UiBadge>
              <UiBadge tone="neutral">{{ sessionOpenTime(item) }} WIB · berjalan</UiBadge>
              <span
                v-if="item.status === 'manual_override'"
                class="status-badge status-badge--warning"
                data-testid="session-status-override"
                >{{ sessionStatusLabel(item.status) }}</span
              >
            </div>
            <h3 class="st-card__title">{{ item.subject }}</h3>
            <p class="st-table__muted">
              Guru Pengampu: {{ item.teacher_name }} · Dibuka
              {{ displayDateTime(item.opened_at, item.timezone_name) }} ·
              {{ item.opened_automatically ? 'Otomatis' : 'Manual' }}
            </p>
            <div class="st-session-live__tiles">
              <div class="st-session-live__tile">
                <span class="st-material-icon" aria-hidden="true">groups</span>
                <span
                  ><small>Kelas</small
                  ><strong>{{ item.class_name }} ({{ item.student_count }} Siswa)</strong></span
                >
              </div>
              <div class="st-session-live__tile">
                <span class="st-material-icon" aria-hidden="true">science</span>
                <span
                  ><small>Ruang</small><strong>{{ item.laboratory_name }}</strong></span
                >
              </div>
              <div class="st-session-live__tile">
                <span class="st-material-icon" aria-hidden="true">videocam</span>
                <span><small>Pemindai AI</small><strong>Kamera: Pintu Masuk 01</strong></span>
              </div>
            </div>
          </div>
          <aside
            v-if="liveRoster[item.id]"
            class="st-session-live__roster"
            aria-label="Roster langsung"
          >
            <p class="st-session-live__roster-head">
              Live roster kehadiran
              <strong
                >{{ liveRoster[item.id].present + liveRoster[item.id].late }} /
                {{ liveRoster[item.id].total }} Terdata</strong
              >
            </p>
            <div
              class="st-session-live__bar"
              role="presentation"
              :style="{
                '--done-pct':
                  Math.round(
                    ((liveRoster[item.id].present + liveRoster[item.id].late) /
                      Math.max(1, liveRoster[item.id].total)) *
                      100,
                  ) + '%',
              }"
            />
            <div class="st-session-live__counts">
              <span
                ><strong>{{ liveRoster[item.id].present }}</strong
                ><small>Hadir</small></span
              >
              <span
                ><strong>{{ liveRoster[item.id].late }}</strong
                ><small>Terlambat</small></span
              >
              <span
                ><strong>{{
                  liveRoster[item.id].total - liveRoster[item.id].present - liveRoster[item.id].late
                }}</strong
                ><small>Belum Masuk</small></span
              >
            </div>
            <UiButton
              variant="primary"
              :data-testid="'show-status-' + item.id"
              class="st-session-live__cta"
              @click="showStatus(item)"
              ><span class="st-material-icon" aria-hidden="true">visibility</span>Pantau Sesi &amp;
              Roster</UiButton
            >
            <UiButton
              v-if="canOperateSessions"
              variant="danger-soft"
              :data-testid="'close-session-' + item.id"
              :disabled="closingSessionId !== null"
              @click="askClose(item)"
              >Tutup sesi</UiButton
            >
          </aside>
          <div v-else class="st-schedule__actions">
            <UiButton
              variant="primary"
              :data-testid="'show-status-' + item.id"
              @click="showStatus(item)"
              >Pantau Sesi &amp; Roster</UiButton
            >
            <UiButton
              v-if="canOperateSessions"
              variant="danger-soft"
              :data-testid="'close-session-' + item.id"
              :disabled="closingSessionId !== null"
              @click="askClose(item)"
              >Tutup sesi</UiButton
            >
          </div>
        </article>
      </div>
      <p v-else class="st-table__muted">Tidak ada sesi yang sedang berjalan.</p>
    </section>

    <!-- Riwayat -->
    <section aria-labelledby="history-title">
      <div class="st-sectionrow">
        <h2 id="history-title" class="st-section">Riwayat Sesi Terakhir</h2>
        <RouterLink class="st-link" to="/app/reports">Lihat Semua Laporan →</RouterLink>
      </div>
      <div class="st-card">
        <div class="st-tablewrap">
          <table class="st-table">
            <thead>
              <tr>
                <th scope="col">Tanggal &amp; Waktu</th>
                <th scope="col">Judul Praktikum</th>
                <th scope="col">Ruang Lab</th>
                <th scope="col">Statistik Siswa</th>
                <th scope="col">Status Sesi</th>
                <th scope="col" class="st-table__actions">Aksi</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="isLoading">
                <td colspan="6" class="st-table__muted">Memuat sesi…</td>
              </tr>
              <tr v-else-if="!historySessions.length">
                <td colspan="6" class="st-table__muted">Belum ada riwayat sesi.</td>
              </tr>
              <tr v-for="item in historySessions" v-else :key="item.id">
                <td>{{ displayDateTime(item.opened_at, item.timezone_name) }}</td>
                <td>
                  <strong>{{ item.subject }}</strong
                  ><br />
                  <span class="st-table__muted">{{ item.class_name }}</span>
                </td>
                <td>{{ item.laboratory_name }}</td>
                <td>{{ item.student_count }} siswa · grace {{ item.grace_period_minutes }} mnt</td>
                <td>
                  <span
                    class="status-badge"
                    :class="sessionStatusClass(item.status)"
                    :data-testid="
                      item.status === 'manual_override' ? 'session-status-override' : undefined
                    "
                    >{{ sessionStatusLabel(item.status) }}</span
                  >
                </td>
                <td class="st-table__actions">
                  <button
                    type="button"
                    class="st-link"
                    :data-testid="'show-status-' + item.id"
                    @click="showStatus(item)"
                  >
                    Lihat Rekap →
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </section>

    <!-- Detail sesi -->
    <section v-if="selected" aria-labelledby="session-detail-title">
      <UiButton variant="text" size="sm" @click="selected = null"
        >← Kembali ke daftar sesi</UiButton
      >
      <div
        v-if="!canOperateSessions"
        class="st-monitorbanner"
        role="note"
        data-testid="session-monitor-banner"
      >
        <span class="st-monitorbanner__icon" aria-hidden="true"
          ><span class="st-material-icon">visibility</span></span
        >
        <p>
          <strong>Mode Pantau Sesi Aktif</strong>
          <UiBadge tone="info">Izin terbatas</UiBadge><br />
          Anda memiliki izin memantau data kehadiran waktu nyata sesi
          {{ selected.laboratory_name }}. Tindakan buka sesi, tutup sesi, tandai manual, atau ajukan
          koreksi merupakan wewenang Guru Pengampu ({{ selected.teacher_name }}).
        </p>
        <span class="st-monitorbanner__chip">
          <span class="st-material-icon" aria-hidden="true">lock</span>
          {{ isLaborant ? 'Akses Pantau Saja (Delegasi Laboran)' : 'Akses baca saja' }}
        </span>
      </div>
      <UiPageHeader
        :title="`Detail Sesi: ${selected.subject}`"
        :description="`${selected.laboratory_name} · ${selected.class_name} · Pengampu ${selected.teacher_name}`"
      />
      <div class="st-grid3">
        <UiCard title="Total Siswa" :subtitle="`${selected.student_count} Kadet`">
          <p class="st-kpi">{{ selected.student_count }}</p>
        </UiCard>
        <UiCard
          title="Terdata"
          :subtitle="`${rosterStatusCounts.present + rosterStatusCounts.late} dari ${roster.length}`"
        >
          <p class="st-kpi">
            {{ rosterStatusCounts.present + rosterStatusCounts.late
            }}<small> / {{ roster.length }}</small>
          </p>
        </UiCard>
        <UiCard title="Belum Tercatat" subtitle="Akan menjadi absen saat tutup">
          <p class="st-kpi">{{ rosterStatusCounts.unmarked }}</p>
        </UiCard>
      </div>

      <div class="st-card">
        <h3 class="st-card__title">Roster sesi</h3>
        <form class="st-toolbar" @submit.prevent>
          <UiSearchInput
            v-model="rosterSearch"
            placeholder="Nama atau NIS…"
            aria-label="Cari siswa"
            data-testid="roster-search"
            :disabled="isRosterLoading"
          />
          <div class="st-scope" role="group" aria-label="Filter status roster">
            <button
              v-for="option in rosterStatusFilters"
              :key="option.value"
              type="button"
              :class="{ 'st-scope--active': rosterStatusFilter === option.value }"
              :data-testid="'roster-filter-' + option.value"
              :aria-pressed="rosterStatusFilter === option.value"
              @click="rosterStatusFilter = option.value"
            >
              {{ option.label }} ({{ rosterStatusCounts[option.value] }})
            </button>
          </div>
        </form>
        <p v-if="isRosterLoading" class="st-table__muted">Memuat roster…</p>
        <p v-else-if="rosterError" class="st-alert st-alert--error" role="alert">
          {{ rosterError }}
        </p>
        <p v-else-if="filteredRoster.length === 0" class="st-table__muted">
          Tidak ada siswa yang cocok dengan pencarian atau filter.
        </p>
        <div v-else class="st-tablewrap">
          <table class="st-table" data-testid="roster-table">
            <thead>
              <tr>
                <th scope="col">No</th>
                <th scope="col">Nama Siswa</th>
                <th scope="col">Waktu Presensi</th>
                <th scope="col">Verifikasi</th>
                <th scope="col">Status</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="(entry, idx) in filteredRoster"
                :key="entry.student_id"
                data-testid="roster-row"
              >
                <td>{{ idx + 1 }}</td>
                <td>
                  <span class="st-identity">
                    <UiAvatar :name="entry.full_name" />
                    <span
                      ><strong>{{ entry.full_name }}</strong
                      ><br /><span class="st-table__muted">{{ entry.student_number }}</span></span
                    >
                  </span>
                </td>
                <td>
                  <span v-if="entry.recorded_at">{{
                    displayDateTime(entry.recorded_at, selected?.timezone_name ?? 'Asia/Jakarta')
                  }}</span>
                  <span v-else class="st-table__muted">–</span>
                  <span v-if="entry.minutes_late != null">
                    · telat {{ entry.minutes_late }} mnt</span
                  >
                </td>
                <td class="st-table__muted">{{ entry.record_note ?? '–' }}</td>
                <td>
                  <UiBadge
                    :tone="
                      entry.record_status === 'present'
                        ? 'present'
                        : entry.record_status === 'late'
                          ? 'late'
                          : entry.record_status === 'excused'
                            ? 'info'
                            : entry.record_status === 'absent'
                              ? 'absent'
                              : 'neutral'
                    "
                  >
                    {{ rosterStatusLabel(entry.record_status) }}
                  </UiBadge>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div v-if="canManualMark" class="st-card">
        <h3 class="st-card__title">Tandai kehadiran manual</h3>
        <p class="st-table__muted">
          Hanya untuk siswa roster yang belum memiliki catatan presensi. Pilihan guru langsung
          menjadi status akhir tanpa ambang batas otomatis.
        </p>
        <p v-if="manualMarkMessage" class="st-alert st-alert--success" role="status">
          {{ manualMarkMessage }}
        </p>
        <p v-if="unmarkedRoster.length === 0" class="st-table__muted">
          Semua siswa roster sudah memiliki catatan presensi.
        </p>
        <ul v-else class="st-list">
          <li v-for="entry in unmarkedRoster" :key="entry.student_id" class="st-list__item">
            <span class="st-identity">
              <UiAvatar :name="entry.full_name" />
              <span
                ><strong>{{ entry.full_name }}</strong
                ><br /><span class="st-table__muted">{{ entry.student_number }}</span></span
              >
            </span>
            <UiSelect
              v-model="draftFor(entry.student_id).status"
              :disabled="draftFor(entry.student_id).saving"
              :aria-label="'Status untuk ' + entry.full_name"
            >
              <option value="present">Hadir</option>
              <option value="late">Terlambat</option>
              <option value="absent">Absen</option>
              <option value="excused">Izin</option>
            </UiSelect>
            <UiInput
              v-model="draftFor(entry.student_id).note"
              type="text"
              maxlength="500"
              placeholder="Alasan atau keterangan"
              :disabled="draftFor(entry.student_id).saving"
              :aria-label="'Catatan untuk ' + entry.full_name"
            />
            <UiButton
              variant="secondary"
              :disabled="draftFor(entry.student_id).saving"
              :data-testid="'manual-mark-' + entry.student_id"
              @click="submitManualMark(entry)"
            >
              {{ draftFor(entry.student_id).saving ? 'Menyimpan…' : 'Tandai manual' }}
            </UiButton>
          </li>
        </ul>
        <p
          v-if="unmarkedRoster.length && draftFor(unmarkedRoster[0].student_id).error"
          class="st-alert st-alert--error"
          role="alert"
        >
          {{ draftFor(unmarkedRoster[0].student_id).error }}
        </p>
      </div>
      <p v-else class="st-table__muted">Tandai manual membutuhkan izin Tandai Kehadiran Manual.</p>

      <div class="st-card" data-testid="correction-panel">
        <h3 class="st-card__title">Pengajuan koreksi kehadiran</h3>
        <p v-if="!canProposeCorrection" class="st-table__muted">
          Pengajuan koreksi membutuhkan izin Ajukan Koreksi atau Pantau Sesi + Lihat Laporan.
        </p>
        <p class="st-table__muted">
          Untuk record final yang perlu diperbaiki, atau siswa tanpa record setelah sesi ditutup
          (diajukan sebagai absen → status yang diminta). Selalu butuh alasan dan diputuskan admin.
        </p>
        <p v-if="correctionMessage" class="st-alert st-alert--success" role="status">
          {{ correctionMessage }}
        </p>
        <p v-if="correctionsError" class="st-alert st-alert--error" role="alert">
          {{ correctionsError }}
        </p>
        <ul class="st-list">
          <li v-for="entry in roster" :key="'corr-' + entry.student_id" class="st-list__item">
            <span class="st-identity">
              <UiAvatar :name="entry.full_name" />
              <span
                ><strong>{{ entry.full_name }}</strong
                ><br /><span class="st-table__muted"
                  >{{ entry.student_number }} · sebelumnya:
                  {{
                    entry.record_status
                      ? attendanceStatusLabel(entry.record_status)
                      : 'absen (tanpa record)'
                  }}</span
                ></span
              >
            </span>
            <UiSelect
              v-model="
                correctionDraftFor(
                  (entry.record_status ? 'record-' : 'missing-') + entry.student_id,
                ).corrected_status
              "
              aria-label="Status diminta"
            >
              <option value="present">Hadir</option>
              <option value="late">Terlambat</option>
              <option value="absent">Absen</option>
              <option value="excused">Izin</option>
            </UiSelect>
            <UiInput
              v-model="
                correctionDraftFor(
                  (entry.record_status ? 'record-' : 'missing-') + entry.student_id,
                ).reason
              "
              type="text"
              maxlength="2000"
              placeholder="Alasan wajib"
              aria-label="Alasan koreksi"
            />
            <UiButton
              v-if="canProposeCorrection && entry.record_status"
              variant="secondary"
              :disabled="correctionDraftFor('record-' + entry.student_id).saving"
              :data-testid="'correction-record-' + entry.student_id"
              @click="submitCorrectionForRecord(entry)"
              >Ajukan koreksi</UiButton
            >
            <UiButton
              v-else-if="canProposeCorrection"
              variant="secondary"
              :disabled="correctionDraftFor('missing-' + entry.student_id).saving"
              :data-testid="'correction-missing-' + entry.student_id"
              @click="submitCorrectionForMissing(entry)"
              >Ajukan koreksi (tanpa record)</UiButton
            >
            <p v-if="correctionErrorFor(entry)" class="st-alert st-alert--error" role="alert">
              {{ correctionErrorFor(entry) }}
            </p>
          </li>
        </ul>
        <h3 class="st-section">Daftar pengajuan koreksi</h3>
        <p v-if="isCorrectionsLoading" class="st-table__muted">Memuat koreksi…</p>
        <ul v-else-if="corrections.length" class="st-list">
          <li v-for="c in corrections" :key="c.id" class="st-list__item">
            <span
              ><strong>{{ rosterName(c.student_id) }}</strong
              ><br /><span class="st-table__muted"
                >{{ attendanceStatusLabel(c.previous_status) }} →
                {{ attendanceStatusLabel(c.corrected_status) }} ·
                {{ correctionDecisionLabel(c.decision_status) }} · {{ c.reason }}</span
              ></span
            >
            <span v-if="isAdmin && c.decision_status === 'pending'">
              <UiInput
                v-model="decisionNotes[c.id]"
                type="text"
                maxlength="2000"
                placeholder="Catatan keputusan (wajib bila menolak)"
                aria-label="Catatan keputusan"
                :data-testid="'correction-decision-note-' + c.id"
                class="st-decision-note"
              />
              <UiButton
                variant="primary"
                size="sm"
                :data-testid="'correction-approve-' + c.id"
                @click="decideCorrection(c, 'approved')"
                >Setujui &amp; terapkan</UiButton
              >
              <UiButton
                variant="secondary"
                size="sm"
                :data-testid="'correction-reject-' + c.id"
                @click="decideCorrection(c, 'rejected')"
                >Tolak</UiButton
              >
            </span>
            <UiBadge v-else tone="info">{{ correctionDecisionLabel(c.decision_status) }}</UiBadge>
          </li>
        </ul>
        <p v-else class="st-table__muted">Belum ada pengajuan koreksi untuk sesi ini.</p>
      </div>
    </section>

    <!-- Modal tutup sesi (B03-05) -->
    <UiModal
      v-if="confirmOpenSchedule"
      title="Buka sesi presensi?"
      @close="confirmOpenSchedule = null"
    >
      <p class="st-table__muted">
        Periksa kembali pertemuan sebelum pemindaian wajah diaktifkan. Roster dikunci saat sesi
        dibuka.
      </p>
      <dl class="st-def">
        <div>
          <dt>Mata pelajaran</dt>
          <dd>{{ confirmOpenSchedule.subject }}</dd>
        </div>
        <div>
          <dt>Kelas</dt>
          <dd>{{ confirmOpenSchedule.class_name }}</dd>
        </div>
        <div>
          <dt>Laboratorium</dt>
          <dd>{{ confirmOpenSchedule.laboratory_name }}</dd>
        </div>
        <div>
          <dt>Pengampu</dt>
          <dd>{{ confirmOpenSchedule.teacher_name }}</dd>
        </div>
        <div>
          <dt>Waktu</dt>
          <dd>
            {{ weekdayName(confirmOpenSchedule.weekday) }} ·
            {{ displayTime(confirmOpenSchedule.start_time) }}–{{
              displayTime(confirmOpenSchedule.end_time)
            }}
            WIB · grace {{ gracePeriodMinutes }} mnt
          </dd>
        </div>
      </dl>
      <template #footer>
        <UiButton variant="secondary" @click="confirmOpenSchedule = null">Batal</UiButton>
        <UiButton
          variant="primary"
          data-testid="confirm-open-session"
          :disabled="openingScheduleId !== null"
          @click="confirmOpenSession"
        >
          {{ openingScheduleId ? 'Membuka…' : 'Konfirmasi & Buka Sesi' }}
        </UiButton>
      </template>
    </UiModal>
    <UiModal
      v-if="confirmCloseId && closingSession"
      title="Tutup Sesi Presensi?"
      :subtitle="`Sesi Praktikum ${closingSession.class_name}`"
      @close="confirmCloseId = null"
    >
      <p>
        Sesi praktikum akan <strong>diakhiri dan dikunci secara permanen</strong>. Kamera pemindai
        wajah lab akan dinonaktifkan untuk rombel ini.
      </p>
      <div class="st-alert st-alert--error" role="alert">
        Terdapat {{ closeUnmarked }} siswa belum tercatat akan menjadi absen. Semua siswa yang Belum
        Tercatat akan otomatis ditetapkan berstatus Absen (Alpha) tanpa rekaman kehadiran.
      </div>
      <h3 class="st-section">
        Proyeksi Rekapitulasi Akhir · Total: {{ closingSession.student_count }} Siswa
      </h3>
      <div class="st-grid3">
        <UiCard title="Hadir"
          ><p class="st-kpi">{{ closePresent }}<small> Siswa</small></p></UiCard
        >
        <UiCard title="Terlambat"
          ><p class="st-kpi">{{ closeLate }}<small> Siswa</small></p></UiCard
        >
        <UiCard title="Absen (Alpha)"
          ><p class="st-kpi">{{ closeAbsent }}<small> Siswa</small></p></UiCard
        >
      </div>
      <p class="st-table__muted">
        Ketentuan SOP: Setelah sesi ditutup, perubahan status hanya dapat dilakukan melalui prosedur
        Pengajuan Koreksi Kehadiran yang disetujui admin.
      </p>
      <template #footer>
        <UiButton variant="secondary" @click="confirmCloseId = null">Batal</UiButton>
        <UiButton
          variant="danger"
          data-testid="confirm-close-session"
          :disabled="closingSessionId !== null"
          @click="closeSession(closingSession)"
        >
          {{ closingSessionId ? 'Menutup…' : 'Tutup Sesi Presensi' }}
        </UiButton>
      </template>
    </UiModal>
  </div>
</template>
