<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useAuthStore } from '../stores/auth'
import {
  ApiError,
  closeAttendanceSession,
  getAttendanceSessionStatus,
  getOpeningPreference,
  getSessionOpeningPolicy,
  getSessionRoster,
  listAttendanceSessions,
  listOpenableSchedules,
  markManualAttendance,
  openAttendanceSession,
  saveOpeningPreference,
  saveSessionOpeningPolicy,
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
  return new Intl.DateTimeFormat('id-ID', {
    dateStyle: 'medium',
    timeStyle: 'short',
    timeZone: timezone,
  }).format(new Date(value))
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
    pageError.value = formatError(error)
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
  } catch (error) {
    pageError.value = formatError(error)
  }
}

async function loadRoster(sessionId: string): Promise<void> {
  isRosterLoading.value = true
  rosterError.value = null
  try {
    roster.value = await getSessionRoster(sessionId)
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
        <label>
          <input
            v-model="preferenceMode"
            type="radio"
            value="manual"
            data-testid="opening-mode-manual"
            :disabled="isSavingPreference"
          />
          Manual — saya membuka sesi dari halaman ini
        </label>
        <label>
          <input
            v-model="preferenceMode"
            type="radio"
            value="automatic"
            data-testid="opening-mode-automatic"
            :disabled="isSavingPreference"
          />
          Otomatis — sesi dibuka dalam jendela jadwal
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
      <div class="session-view__manual-marks">
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
    </section>
  </section>
</template>
