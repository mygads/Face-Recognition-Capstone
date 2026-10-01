<script setup lang="ts">
import { onMounted, ref } from 'vue'
import {
  ApiError,
  closeAttendanceSession,
  getAttendanceSessionStatus,
  listAttendanceSessions,
  listOpenableSchedules,
  openAttendanceSession,
  type AttendanceSession,
  type OpenableSchedule,
} from '../api/client'

const weekdays = ['Senin', 'Selasa', 'Rabu', 'Kamis', 'Jumat', 'Sabtu', 'Minggu']
const schedules = ref<OpenableSchedule[]>([])
const sessions = ref<AttendanceSession[]>([])
const gracePeriodMinutes = ref(15)
const openingScheduleId = ref<string | null>(null)
const closingSessionId = ref<string | null>(null)
const isLoading = ref(false)
const pageError = ref<string | null>(null)
const successMessage = ref<string | null>(null)
const selected = ref<AttendanceSession | null>(null)

function formatError(error: unknown): string {
  if (error instanceof ApiError) {
    const details = error.details?.map((item) => item.field + ': ' + item.message)
    return details?.length ? details.join(' · ') : error.message
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
  } catch (error) {
    pageError.value = formatError(error)
  } finally {
    isLoading.value = false
  }
}

onMounted(() => void reload())

async function openSession(schedule: OpenableSchedule): Promise<void> {
  openingScheduleId.value = schedule.id
  pageError.value = null
  successMessage.value = null
  try {
    const created = await openAttendanceSession(schedule.id, gracePeriodMinutes.value)
    successMessage.value =
      'Sesi ' + created.subject + ' dibuka dengan ' + created.student_count + ' siswa di roster.'
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
  try {
    selected.value = await getAttendanceSessionStatus(item.id)
  } catch (error) {
    pageError.value = formatError(error)
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
              <td data-label="Dibuka">{{ displayDateTime(item.opened_at, item.timezone_name) }}</td>
              <td data-label="Roster">
                {{ item.student_count }} siswa · grace {{ item.grace_period_minutes }} menit
              </td>
              <td data-label="Status">
                <span
                  class="status-badge"
                  :class="
                    item.status === 'active' ? 'status-badge--active' : 'status-badge--inactive'
                  "
                  >{{ item.status === 'active' ? 'Aktif' : 'Ditutup' }}</span
                >
              </td>
              <td class="master-data__actions" data-label="Aksi">
                <button class="button button--text" type="button" @click="showStatus(item)">
                  Status
                </button>
                <button
                  v-if="item.status === 'active'"
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
          <dd>{{ selected.status === 'active' ? 'Aktif' : 'Ditutup' }}</dd>
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
    </section>
  </section>
</template>
