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
import { formatApiError } from '../utils/apiError'
import UiSearchInput from '../components/ui/UiSearchInput.vue'
import UiSelect from '../components/ui/UiSelect.vue'
import { useRoute } from 'vue-router'
import { formatDateTime } from '../utils/dateFormat'
import { useAuthStore } from '../stores/auth'
import {
  ApiError,
  closeAttendanceSession,
  getAttendanceSessionStatus,
  getSessionOpeningPolicy,
  getSessionRoster,
  listAttendanceSessions,
  listOpenableSchedules,
  markManualAttendance,
  openAttendanceSession,
  type AttendanceSession,
  type ManualMarkRequest,
  type OpenableSchedule,
  type SessionRosterEntry,
} from '../api/client'

const weekdays = ['Senin', 'Selasa', 'Rabu', 'Kamis', 'Jumat', 'Sabtu', 'Minggu']
const auth = useAuthStore()
const route = useRoute() as unknown as { params: Record<string, unknown> } | undefined
const isTeacher = computed(() => auth.account?.roles.includes('TEACHER') ?? false)
const isLaborant = computed(
  () => !isAdmin.value && (auth.account?.roles ?? []).includes('LABORANT'),
)
const schedules = ref<OpenableSchedule[]>([])
const sessions = ref<AttendanceSession[]>([])
// Grace period sesi baru: default 15 menit, dapat diubah per pembukaan.
// Nilai baku diambil dari Kebijakan Presensi (satu sumber kebenaran);
// backend tetap menerapkannya saat sesi dibuka tanpa override eksplisit.
const gracePeriodMinutes = ref(15)

async function loadPolicyGraceDefault(): Promise<void> {
  try {
    const policy = await getSessionOpeningPolicy()
    const raw = policy.default_grace_period_minutes
    if (typeof raw === 'number' && Number.isFinite(raw) && raw >= 0 && raw <= 1440) {
      gracePeriodMinutes.value = Math.floor(raw)
    }
  } catch {
    // Tanpa akses baca kebijakan (atau backend lama): tetap 15 menit.
  }
}
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
const isAdmin = computed(() => auth.account?.roles.includes('ADMIN') ?? false)
const staffPermissions = computed(() => (auth.account?.permissions ?? []) as string[])
const canOperateSessions = computed(
  () => isAdmin.value || isTeacher.value || staffPermissions.value.includes('session_operate'),
)
const canManualMark = computed(
  () =>
    isAdmin.value ||
    isTeacher.value ||
    staffPermissions.value.includes('attendance_manual') ||
    staffPermissions.value.includes('attendance_correct_closed'),
)
// Sesi terpilih yang sudah ditutup/dibatalkan: form manual menjadi
// koreksi pascasesi (alasan wajib, tercatat audit, butuh izin khusus).
const isClosedSelected = computed(
  () => selected.value?.status === 'closed' || selected.value?.status === 'cancelled',
)

function formatError(error: unknown): string {
  return formatApiError(error, 'Permintaan tidak dapat diproses. Coba lagi.')
}

function manualMarkError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.code === 'attendance_already_recorded') {
      return 'Presensi siswa ini sudah tercatat. Muat ulang daftar.'
    }
    if (error.code === 'session_inactive') {
      return 'Sesi sudah ditutup. Koreksi pascasesi memerlukan izin Koreksi Sesi Tertutup.'
    }
    if (error.code === 'reason_required') {
      return 'Alasan wajib diisi untuk koreksi sesi tertutup.'
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
const markedRoster = computed(() =>
  roster.value.filter((entry) => entry.record_status !== null && entry.record_status !== undefined),
)

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
    const [available, page] = await Promise.all([
      listOpenableSchedules(),
      listAttendanceSessions({ limit: 50, offset: 0 }),
    ])
    schedules.value = available
    sessions.value = page.items
    void refreshLiveRoster(
      page.items.filter((s) => s.status !== 'closed' && s.status !== 'cancelled'),
    )
  } catch (error) {
    pageError.value = formatError(error)
  } finally {
    isLoading.value = false
  }
}

onMounted(async () => {
  await loadPolicyGraceDefault()
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
  if (isClosedSelected.value && !trimmedNote) {
    draft.error = 'Sesi sudah ditutup: alasan wajib diisi untuk koreksi pascasesi.'
    return
  }
  if (entry.record_status && !trimmedNote) {
    draft.error = 'Alasan perubahan wajib diisi saat memperbarui catatan.'
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
    manualMarkMessage.value =
      'Kehadiran ' +
      entry.full_name +
      (entry.record_status ? ' diperbarui langsung.' : ' ditandai manual.')
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
            data-testid="open-grace-input"
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
          {{ selected.laboratory_name }}. Tindakan buka sesi, tutup sesi, dan ubah kehadiran
          merupakan wewenang Guru Pengampu ({{ selected.teacher_name }}).
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
                  <span v-else class="st-table__muted">-</span>
                  <span v-if="entry.minutes_late != null">
                    · telat {{ entry.minutes_late }} mnt</span
                  >
                </td>
                <td class="st-table__muted">{{ entry.record_note ?? '-' }}</td>
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
        <p v-if="isClosedSelected" class="st-alert" role="note">
          Sesi sudah ditutup: penandaan di sini adalah koreksi pascasesi. Alasan wajib diisi dan
          tercatat pada audit.
        </p>
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
      <p v-else class="st-table__muted">
        Tandai manual membutuhkan izin Tandai Kehadiran Manual atau Koreksi Sesi Tertutup.
      </p>

      <div v-if="canManualMark" class="st-card" data-testid="direct-update-panel">
        <h3 class="st-card__title">Ubah kehadiran langsung</h3>
        <p v-if="isClosedSelected" class="st-alert" role="note">
          Sesi sudah ditutup: perubahan di sini adalah koreksi pascasesi. Alasan wajib diisi dan
          tercatat pada audit.
        </p>
        <p class="st-table__muted">
          Pengganti koreksi berjenjang: guru/aslab berwenang langsung memperbarui catatan yang sudah
          ada (termasuk hasil face recognition) tanpa persetujuan admin. Setiap perubahan dicatat
          pada audit.
        </p>
        <p v-if="manualMarkMessage" class="st-alert st-alert--success" role="status">
          {{ manualMarkMessage }}
        </p>
        <p v-if="markedRoster.length === 0" class="st-table__muted">
          Belum ada catatan pada sesi ini. Gunakan “Tandai kehadiran manual” di atas.
        </p>
        <ul v-else class="st-list">
          <li v-for="entry in markedRoster" :key="'upd-' + entry.student_id" class="st-list__item">
            <span class="st-identity">
              <UiAvatar :name="entry.full_name" />
              <span
                ><strong>{{ entry.full_name }}</strong
                ><br /><span class="st-table__muted"
                  >{{ entry.student_number }} · saat ini:
                  {{ rosterStatusLabel(entry.record_status) }}</span
                ></span
              >
            </span>
            <UiSelect
              v-model="draftFor(entry.student_id).status"
              :disabled="draftFor(entry.student_id).saving"
              :aria-label="'Status baru untuk ' + entry.full_name"
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
              placeholder="Alasan perubahan"
              :disabled="draftFor(entry.student_id).saving"
              :aria-label="'Catatan untuk ' + entry.full_name"
            />
            <UiButton
              variant="secondary"
              :disabled="draftFor(entry.student_id).saving"
              :data-testid="'direct-update-' + entry.student_id"
              @click="submitManualMark(entry)"
              >{{ draftFor(entry.student_id).saving ? 'Menyimpan…' : 'Ubah langsung' }}</UiButton
            >
            <p
              v-if="draftFor(entry.student_id).error"
              class="st-alert st-alert--error"
              role="alert"
            >
              {{ draftFor(entry.student_id).error }}
            </p>
          </li>
        </ul>
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
            {{ displayTime(confirmOpenSchedule.start_time) }}-{{
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
