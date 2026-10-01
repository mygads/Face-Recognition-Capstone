<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import {
  ApiError,
  getSessionDashboardSnapshot,
  listAttendanceSessions,
  sessionDashboardWebSocketUrl,
  type AttendanceSession,
  type SessionDashboardSnapshot,
  type SessionRecentActivity,
} from '../api/client'
import { useAuthStore } from '../stores/auth'
import { useRouter } from 'vue-router'

type DashboardMessage = {
  type: 'snapshot'
  data: SessionDashboardSnapshot
}

const auth = useAuthStore()
const router = useRouter()
const sessions = ref<AttendanceSession[]>([])
const selectedSessionId = ref('')
const snapshot = ref<SessionDashboardSnapshot | null>(null)
const isLoading = ref(false)
const pageError = ref<string | null>(null)
const connectionState = ref<'connecting' | 'live' | 'reconnecting' | 'disconnected'>('disconnected')

let socket: WebSocket | null = null
let reconnectTimer: ReturnType<typeof setTimeout> | undefined
let connectionEpoch = 0
let mounted = false

function formatError(error: unknown): string {
  if (error instanceof ApiError) return error.message
  return 'Ringkasan belum dapat dimuat. Periksa koneksi lalu coba lagi.'
}

function formatTime(value: string): string {
  return new Intl.DateTimeFormat('id-ID', {
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}

function activityTitle(activity: SessionRecentActivity): string {
  if (activity.attendance_status === 'present') return 'Hadir'
  if (activity.attendance_status === 'late') return 'Terlambat'
  if (activity.attendance_status === 'excused') return 'Izin'
  if (activity.attendance_status === 'absent') return 'Belum hadir'
  if (activity.decision_reason === 'attendance_already_recorded') {
    return 'Presensi sudah tercatat'
  }
  if (activity.decision_reason === 'liveness_failed') return 'Verifikasi perlu diulang'
  if (activity.recognition_outcome === 'ambiguous') return 'Wajah perlu diposisikan ulang'
  if (activity.recognition_outcome === 'no_match') return 'Belum dikenali'
  if (activity.recognition_outcome === 'error') return 'Pemrosesan gagal'
  if (activity.recognition_outcome === 'matched') return 'Identitas cocok'
  return 'Aktivitas presensi'
}

function activityDetail(activity: SessionRecentActivity): string {
  return activity.student_name ?? 'Siswa belum teridentifikasi'
}

function sessionLabel(session: AttendanceSession): string {
  return `${session.subject} · ${session.class_name} · ${session.laboratory_name}`
}

function clearReconnectTimer(): void {
  if (reconnectTimer !== undefined) clearTimeout(reconnectTimer)
  reconnectTimer = undefined
}

function closeSocket(): void {
  connectionEpoch += 1
  clearReconnectTimer()
  if (socket && socket.readyState < WebSocket.CLOSING) socket.close()
  socket = null
}

function connect(sessionId: string): void {
  const epoch = ++connectionEpoch
  connectionState.value = 'connecting'
  const currentSocket = new WebSocket(sessionDashboardWebSocketUrl(sessionId))
  socket = currentSocket

  currentSocket.onopen = () => {
    if (epoch !== connectionEpoch) return
    const token = auth.getValidAccessToken()
    if (!token) {
      void router.replace({ name: 'login' })
      currentSocket.close()
      return
    }
    currentSocket.send(JSON.stringify({ type: 'authenticate', access_token: token }))
  }

  currentSocket.onmessage = (event: MessageEvent<string>) => {
    if (epoch !== connectionEpoch) return
    try {
      const message = JSON.parse(event.data) as DashboardMessage
      if (message.type !== 'snapshot' || message.data.session_id !== sessionId) return
      snapshot.value = message.data
      connectionState.value = 'live'
      pageError.value = null
    } catch {
      pageError.value = 'Pembaruan dashboard tidak dapat dibaca.'
    }
  }

  currentSocket.onerror = () => currentSocket.close()
  currentSocket.onclose = () => {
    if (epoch !== connectionEpoch || !mounted || selectedSessionId.value !== sessionId) return
    socket = null
    connectionState.value = 'reconnecting'
    clearReconnectTimer()
    reconnectTimer = setTimeout(() => connect(sessionId), 1500)
  }
}

async function selectSession(sessionId: string): Promise<void> {
  closeSocket()
  selectedSessionId.value = sessionId
  snapshot.value = null
  pageError.value = null
  if (!sessionId) {
    connectionState.value = 'disconnected'
    return
  }

  isLoading.value = true
  connectionState.value = 'connecting'
  try {
    const initialSnapshot = await getSessionDashboardSnapshot(sessionId)
    if (selectedSessionId.value !== sessionId) return
    snapshot.value = initialSnapshot
    connect(sessionId)
  } catch (error) {
    pageError.value = formatError(error)
    connectionState.value = 'disconnected'
  } finally {
    isLoading.value = false
  }
}

async function loadDashboard(): Promise<void> {
  isLoading.value = true
  pageError.value = null
  try {
    const page = await listAttendanceSessions({ status: 'active', limit: 100, offset: 0 })
    sessions.value = page.items
    const retainedSession = page.items.find((item) => item.id === selectedSessionId.value)
    const nextSessionId = (retainedSession ?? page.items[0])?.id ?? ''
    await selectSession(nextSessionId)
  } catch (error) {
    pageError.value = formatError(error)
    connectionState.value = 'disconnected'
  } finally {
    isLoading.value = false
  }
}

function onSessionChange(event: Event): void {
  const element = event.target
  if (element instanceof HTMLSelectElement) void selectSession(element.value)
}

function connectionLabel(): string {
  if (connectionState.value === 'live') return 'Live'
  if (connectionState.value === 'connecting') return 'Menyambungkan'
  if (connectionState.value === 'reconnecting') return 'Menyambungkan ulang'
  return 'Terputus'
}

onMounted(() => {
  mounted = true
  void loadDashboard()
})

onBeforeUnmount(() => {
  mounted = false
  closeSocket()
})
</script>

<template>
  <section class="dashboard-view" aria-label="Dashboard presensi">
    <div class="dashboard-view__toolbar">
      <label v-if="sessions.length" class="dashboard-view__session-picker">
        <span>Sesi aktif</span>
        <select aria-label="Pilih sesi aktif" :value="selectedSessionId" @change="onSessionChange">
          <option v-for="item in sessions" :key="item.id" :value="item.id">
            {{ sessionLabel(item) }}
          </option>
        </select>
      </label>
      <button class="button button--secondary" type="button" @click="loadDashboard">
        Muat ulang
      </button>
    </div>

    <p v-if="pageError" class="dashboard-view__alert" role="alert">{{ pageError }}</p>

    <section v-if="isLoading && !snapshot" class="dashboard-view__empty" aria-live="polite">
      Memuat ringkasan sesi…
    </section>
    <section
      v-else-if="!sessions.length"
      class="dashboard-view__empty"
      data-testid="no-active-session"
    >
      <span class="dashboard-view__empty-mark" aria-hidden="true">✓</span>
      <h2>Belum ada sesi aktif</h2>
      <p>Buka sesi praktikum dari menu Sesi presensi untuk mulai memantau kehadiran.</p>
    </section>

    <template v-else-if="snapshot">
      <div class="dashboard-view__session-heading">
        <div>
          <p class="dashboard-view__eyebrow">
            {{ snapshot.session_status === 'active' ? 'Sedang berlangsung' : 'Sesi berakhir' }}
          </p>
          <h2>{{ sessions.find((item) => item.id === selectedSessionId)?.subject }}</h2>
          <p>
            {{ sessions.find((item) => item.id === selectedSessionId)?.class_name }}
            · {{ sessions.find((item) => item.id === selectedSessionId)?.laboratory_name }}
          </p>
        </div>
        <span
          class="dashboard-view__connection"
          :class="'dashboard-view__connection--' + connectionState"
          role="status"
          data-testid="realtime-status"
        >
          <span aria-hidden="true" />{{ connectionLabel() }}
        </span>
      </div>

      <section class="dashboard-view__metrics" aria-label="Ringkasan kehadiran">
        <article class="dashboard-view__metric" data-testid="metric-roster">
          <span>Total roster</span>
          <strong>{{ snapshot.summary.total_roster }}</strong>
          <small>Siswa terdaftar di sesi</small>
        </article>
        <article
          class="dashboard-view__metric dashboard-view__metric--present"
          data-testid="metric-present"
        >
          <span>Hadir</span>
          <strong>{{ snapshot.summary.present }}</strong>
          <small>Presensi tepat waktu</small>
        </article>
        <article
          class="dashboard-view__metric dashboard-view__metric--late"
          data-testid="metric-late"
        >
          <span>Terlambat</span>
          <strong>{{ snapshot.summary.late }}</strong>
          <small>Di luar grace period</small>
        </article>
        <article
          class="dashboard-view__metric dashboard-view__metric--pending"
          data-testid="metric-not-present"
        >
          <span>Belum hadir</span>
          <strong>{{ snapshot.summary.not_present }}</strong>
          <small>Belum ada presensi hadir</small>
        </article>
      </section>

      <div class="dashboard-view__columns">
        <section class="dashboard-view__panel" aria-labelledby="devices-heading">
          <div class="dashboard-view__panel-heading">
            <div>
              <p class="dashboard-view__eyebrow">Konektivitas laboratorium</p>
              <h2 id="devices-heading">Perangkat</h2>
            </div>
            <span class="dashboard-view__count">{{ snapshot.devices.length }}</span>
          </div>
          <ul v-if="snapshot.devices.length" class="dashboard-view__device-list">
            <li v-for="device in snapshot.devices" :key="device.id">
              <div class="dashboard-view__device-icon" aria-hidden="true">
                <svg viewBox="0 0 24 24" fill="none">
                  <rect x="3.5" y="4.5" width="17" height="12" rx="1.5" />
                  <path d="M8 20h8m-4-3.5V20" />
                </svg>
              </div>
              <div class="dashboard-view__device-copy">
                <strong>{{ device.name }}</strong>
                <small>{{
                  device.last_seen_at
                    ? 'Terakhir terhubung ' + formatTime(device.last_seen_at)
                    : 'Belum pernah terhubung'
                }}</small>
              </div>
              <span
                class="dashboard-view__device-status"
                :class="
                  device.is_online
                    ? 'dashboard-view__device-status--online'
                    : 'dashboard-view__device-status--offline'
                "
              >
                {{ device.is_online ? 'Online' : 'Offline' }}
              </span>
            </li>
          </ul>
          <p v-else class="dashboard-view__muted">
            Belum ada perangkat terdaftar di laboratorium ini.
          </p>
        </section>

        <section class="dashboard-view__panel" aria-labelledby="activity-heading">
          <div class="dashboard-view__panel-heading">
            <div>
              <p class="dashboard-view__eyebrow">Pembaruan sesi</p>
              <h2 id="activity-heading">Aktivitas terbaru</h2>
            </div>
          </div>
          <ol v-if="snapshot.recent_activity.length" class="dashboard-view__activity-list">
            <li v-for="activity in snapshot.recent_activity" :key="activity.kind + activity.id">
              <span
                class="dashboard-view__activity-marker"
                :class="
                  activity.attendance_status === 'late'
                    ? 'dashboard-view__activity-marker--late'
                    : ''
                "
                aria-hidden="true"
              />
              <div class="dashboard-view__activity-copy">
                <strong>{{ activityDetail(activity) }}</strong>
                <small>{{ activityTitle(activity) }}</small>
              </div>
              <time :datetime="activity.occurred_at">{{ formatTime(activity.occurred_at) }}</time>
            </li>
          </ol>
          <p v-else class="dashboard-view__muted">Belum ada aktivitas pada sesi ini.</p>
        </section>
      </div>
    </template>
  </section>
</template>

<style lang="scss" scoped>
.dashboard-view {
  display: grid;
  gap: 20px;
  min-width: 0;
}

.dashboard-view__toolbar,
.dashboard-view__session-heading,
.dashboard-view__panel-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.dashboard-view__toolbar {
  justify-content: flex-end;
}

.dashboard-view__session-picker {
  display: grid;
  width: min(100%, 440px);
  gap: 6px;
  margin-right: auto;
  color: var(--text-muted);
  font-size: 0.75rem;
  font-weight: 600;
}

.dashboard-view__session-picker select {
  width: 100%;
  min-height: 42px;
  padding: 0 12px;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  color: var(--text);
  background: var(--bg-surface);
  font: inherit;
}

.dashboard-view__alert,
.dashboard-view__empty,
.dashboard-view__panel,
.dashboard-view__metric {
  border: 1px solid var(--border-color-light);
  border-radius: var(--radius);
  background: var(--bg-surface);
  box-shadow: var(--shadow-sm);
}

.dashboard-view__alert {
  margin: 0;
  padding: 12px 16px;
  color: var(--danger, #b42318);
}

.dashboard-view__empty {
  display: grid;
  min-height: 250px;
  align-content: center;
  justify-items: center;
  padding: 32px 20px;
  text-align: center;
}

.dashboard-view__empty h2,
.dashboard-view__session-heading h2,
.dashboard-view__panel-heading h2 {
  margin: 0;
  color: var(--text);
  font-size: 1.05rem;
  font-weight: 650;
}

.dashboard-view__empty p,
.dashboard-view__session-heading p:last-child {
  margin: 7px 0 0;
  color: var(--text-muted);
  font-size: 0.82rem;
}

.dashboard-view__empty-mark {
  display: grid;
  width: 44px;
  height: 44px;
  place-items: center;
  margin-bottom: 14px;
  border-radius: 50%;
  color: var(--primary);
  background: var(--primary-lt);
  font-size: 1.15rem;
  font-weight: 700;
}

.dashboard-view__eyebrow {
  margin: 0 0 5px;
  color: var(--text-muted);
  font-size: 0.65rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.dashboard-view__session-heading {
  min-height: 46px;
}

.dashboard-view__connection {
  display: inline-flex;
  min-height: 30px;
  align-items: center;
  gap: 8px;
  padding: 0 11px;
  border: 1px solid var(--border-color-light);
  border-radius: 999px;
  color: var(--text-muted);
  background: var(--bg-surface);
  font-size: 0.7rem;
  font-weight: 650;
  white-space: nowrap;
}

.dashboard-view__connection > span {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: currentColor;
}

.dashboard-view__connection--live {
  color: #157347;
}

.dashboard-view__connection--live > span {
  box-shadow: 0 0 0 3px color-mix(in srgb, currentColor 15%, transparent);
}

.dashboard-view__connection--connecting,
.dashboard-view__connection--reconnecting {
  color: #8a5b00;
}

.dashboard-view__metrics {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
}

.dashboard-view__metric {
  display: grid;
  min-width: 0;
  gap: 7px;
  padding: 17px 18px;
}

.dashboard-view__metric > span {
  color: var(--text-muted);
  font-size: 0.76rem;
  font-weight: 600;
}

.dashboard-view__metric strong {
  color: var(--text);
  font-size: clamp(1.65rem, 3vw, 2rem);
  line-height: 1;
  font-weight: 700;
}

.dashboard-view__metric small {
  color: var(--text-muted);
  font-size: 0.68rem;
}

.dashboard-view__metric--present strong {
  color: #157347;
}

.dashboard-view__metric--late strong {
  color: #ad6800;
}

.dashboard-view__metric--pending strong {
  color: var(--primary-dk);
}

.dashboard-view__columns {
  display: grid;
  grid-template-columns: minmax(240px, 0.82fr) minmax(0, 1.18fr);
  gap: 14px;
  align-items: start;
}

.dashboard-view__panel {
  min-width: 0;
  padding: 19px;
}

.dashboard-view__count {
  display: grid;
  min-width: 28px;
  height: 28px;
  place-items: center;
  border-radius: 999px;
  color: var(--primary-dk);
  background: var(--primary-lt);
  font-size: 0.72rem;
  font-weight: 700;
}

.dashboard-view__device-list,
.dashboard-view__activity-list {
  display: grid;
  margin: 16px 0 0;
  padding: 0;
  list-style: none;
}

.dashboard-view__device-list li,
.dashboard-view__activity-list li {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 11px;
  padding: 12px 0;
  border-top: 1px solid var(--border-color-light);
}

.dashboard-view__device-icon {
  display: grid;
  width: 36px;
  height: 36px;
  flex: 0 0 auto;
  place-items: center;
  border-radius: var(--radius-sm);
  color: var(--primary-dk);
  background: var(--primary-lt);
}

.dashboard-view__device-icon svg {
  width: 19px;
  stroke: currentColor;
  stroke-linecap: round;
  stroke-linejoin: round;
  stroke-width: 1.6;
}

.dashboard-view__device-copy,
.dashboard-view__activity-copy {
  display: grid;
  min-width: 0;
  flex: 1;
  gap: 3px;
}

.dashboard-view__device-copy strong,
.dashboard-view__activity-copy strong {
  overflow: hidden;
  color: var(--text);
  font-size: 0.78rem;
  font-weight: 650;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dashboard-view__device-copy small,
.dashboard-view__activity-copy small,
.dashboard-view__activity-list time {
  color: var(--text-muted);
  font-size: 0.68rem;
}

.dashboard-view__device-status {
  flex: 0 0 auto;
  font-size: 0.68rem;
  font-weight: 700;
}

.dashboard-view__device-status--online {
  color: #157347;
}

.dashboard-view__device-status--offline {
  color: var(--text-muted);
}

.dashboard-view__activity-marker {
  width: 9px;
  height: 9px;
  flex: 0 0 auto;
  border: 2px solid var(--primary);
  border-radius: 50%;
  background: var(--bg-surface);
}

.dashboard-view__activity-marker--late {
  border-color: #ad6800;
}

.dashboard-view__activity-list time {
  flex: 0 0 auto;
}

.dashboard-view__muted {
  margin: 18px 0 0;
  color: var(--text-muted);
  font-size: 0.78rem;
}

@media (max-width: 1050px) {
  .dashboard-view__metrics {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .dashboard-view__columns {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 560px) {
  .dashboard-view {
    gap: 14px;
  }

  .dashboard-view__toolbar,
  .dashboard-view__session-heading {
    align-items: stretch;
  }

  .dashboard-view__toolbar {
    flex-wrap: wrap;
  }

  .dashboard-view__session-picker {
    width: 100%;
  }

  .dashboard-view__metrics {
    gap: 9px;
  }

  .dashboard-view__metric {
    padding: 14px;
  }

  .dashboard-view__panel {
    padding: 15px;
  }
}
</style>
