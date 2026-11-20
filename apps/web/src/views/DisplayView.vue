<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import CameraFrame from '../components/CameraFrame.vue'
import { useFaceLandmarks } from '../composables/useFaceLandmarks'
import { UiBadge, UiButton, UiInput } from '../components/ui'
import { shortDisplayName } from '../utils/displayName'
import {
  agentHintUrl as buildAgentHintUrl,
  agentStreamUrl as buildAgentStreamUrl,
  captureKioskStreamTokenFromQuery,
} from '../utils/agentPreview'
import { timeFormatterFor } from '../utils/dateFormat'
import {
  ApiError,
  getKioskDisplay,
  getPublicDisplay,
  kioskDisplayStreamPath,
  kioskDisplayStreamUrl,
  listPublicKioskScreens,
  listPublicLaboratories,
  openKioskDisplaySession,
  openPublicDisplaySession,
  publicDisplayStreamPath,
  publicDisplayStreamUrl,
  rotateKioskDisplaySession,
  rotatePublicDisplaySession,
  streamDisplayUpdates,
  type KioskLiveUpdate,
  type PublicDisplay,
  type PublicKioskOption,
  type PublicLaboratory,
} from '../api/client'

const DISPLAY_SESSION_STORAGE_KEY = 'presensi.display_session.v1'

interface PersistedDisplaySession {
  token: string
  laboratoryId: string
  deviceId: string
  expiresAt: number
}

function readPersistedDisplaySession(): PersistedDisplaySession | null {
  try {
    const raw = window.sessionStorage.getItem(DISPLAY_SESSION_STORAGE_KEY)
    if (!raw) return null
    const value = JSON.parse(raw) as Partial<PersistedDisplaySession>
    if (
      typeof value.token !== 'string' ||
      value.token.length < 16 ||
      typeof value.laboratoryId !== 'string' ||
      typeof value.deviceId !== 'string' ||
      typeof value.expiresAt !== 'number' ||
      value.expiresAt <= Date.now()
    ) {
      window.sessionStorage.removeItem(DISPLAY_SESSION_STORAGE_KEY)
      return null
    }
    return value as PersistedDisplaySession
  } catch {
    return null
  }
}

const restoredSession = readPersistedDisplaySession()

function persistDisplaySession(token: string, expiresInSeconds: number | undefined): void {
  if (!expiresInSeconds || expiresInSeconds <= 0) return
  try {
    window.sessionStorage.setItem(
      DISPLAY_SESSION_STORAGE_KEY,
      JSON.stringify({
        token,
        laboratoryId: labId.value,
        deviceId: deviceId.value,
        expiresAt: Date.now() + expiresInSeconds * 1000,
      } satisfies PersistedDisplaySession),
    )
  } catch {
    // Browser storage may be disabled; the current page session still works.
  }
}

function clearPersistedDisplaySession(): void {
  try {
    window.sessionStorage.removeItem(DISPLAY_SESSION_STORAGE_KEY)
  } catch {
    // Ignore unavailable browser storage.
  }
}

const labs = ref<PublicLaboratory[]>([])
const kiosks = ref<PublicKioskOption[]>([])
const labId = ref(restoredSession?.laboratoryId ?? '')
const deviceId = ref(restoredSession?.deviceId ?? '')
const pin = ref('')
const display = ref<PublicDisplay | null>(null)
const live = ref<KioskLiveUpdate | null>(null)
const seenSpotlightIds = ref<Set<string>>(new Set())
const displayToken = ref(restoredSession?.token ?? '')
const displayRoot = ref<HTMLElement | null>(null)
const error = ref<string | null>(null)
const fullscreenError = ref<string | null>(null)
const isLoadingLabs = ref(false)
const isLoadingDisplay = ref(false)
const isRestoringDisplay = ref(Boolean(restoredSession))
const isFullscreen = ref(false)
const streamState = ref<'off' | 'sse' | 'polling'>('off')
const cameraState = ref<'idle' | 'active' | 'unavailable' | 'insecure'>('idle')
const localFrameSize = ref({ width: 1280, height: 720 })
const agentStreamState = ref<'idle' | 'live' | 'failed'>('idle')
let initializingDisplay = true
// Upaya koneksi ulang stream MJPEG kios (cache-buster `retry=N` memaksa
// <img> request ulang). 503 awal = buffer JPEG agent belum ada, bukan kamera
// mati: tanpa retry, kios gagal permanen saat dibuka sebelum frame pertama.
const agentStreamAttempt = ref(0)
let agentStreamRetryTimer: ReturnType<typeof setTimeout> | undefined
const AGENT_STREAM_RETRY_BASE_MS = 1000
const AGENT_STREAM_RETRY_MAX_MS = 15000
function clearAgentStreamRetry(): void {
  if (agentStreamRetryTimer) {
    clearTimeout(agentStreamRetryTimer)
    agentStreamRetryTimer = undefined
  }
}
const showBrowserCamera = ref(false)
// Resolusi natural frame MJPEG (default = operasi 640x480); dikoreksi saat
// frame pertama termuat agar overlay mesh selaras dengan gambar object-fit contain.
const agentFrameSize = ref({ width: 640, height: 480 })
const agentImage = ref<HTMLImageElement | null>(null)
const agentHint = ref<AgentHint | null>(null)
// Kesegaran hint: poll gagal >3 dtk berarti agent tak menjawab (frame <img>
// bisa beku menampilkan gambar lama) -> tandai stale, jangan percaya gambar.
const hintFresh = ref(true)
let lastHintOkAt = 0
const agentCameraDown = computed(
  () => agentHint.value !== null && agentHint.value.camera_open === false,
)
const agentVideoStale = computed(() => agentStreamState.value === 'live' && !hintFresh.value)
const agentVideoVisible = computed(
  () =>
    agentStreamState.value !== 'failed' &&
    !agentCameraDown.value &&
    !agentDeviceMismatch.value &&
    !agentPairingUnverified.value,
)
function onAgentStreamLoad(): void {
  agentStreamState.value = 'live'
  // Frame tersedia kembali: reset hitungan retry agar error berikutnya
  // mulai dari backoff awal, bukan dari jeda maksimum.
  agentStreamAttempt.value = 0
  clearAgentStreamRetry()
  const img = agentImage.value
  if (img && img.naturalWidth > 0 && img.naturalHeight > 0) {
    agentFrameSize.value = { width: img.naturalWidth, height: img.naturalHeight }
  }
}
const agentFaces = computed(() => {
  if (!hintFresh.value) return []
  return agentHint.value?.faces ?? []
})
const localVideo = ref<HTMLVideoElement | null>(null)
let pollTimer: ReturnType<typeof setInterval> | undefined
let rotationTimer: ReturnType<typeof setTimeout> | undefined
let eventSource: EventSource | null = null
let fetchAbort: AbortController | null = null
let localStream: MediaStream | null = null
const ROTATE_AHEAD_SECONDS = 1800
const schoolLogoUrl = '/logo-sekolah.png'

// Sinyal generik dari agent di PC kiosk yang sama (tanpa identitas):
// wajah terlihat / kirim menunggu konfirmasi. Best-effort; SSE tetap
// sumber kebenaran hasil. Gagal fetch = indikator disembunyikan diam-diam.
// Token stream kios opsional (diset operator sekali via ?stream_token= lalu
// disimpan di localStorage; backend default kosong = loopback-only).
const agentStreamToken = ref('')
const agentHintUrl = computed(() => buildAgentHintUrl(agentStreamToken.value))
const agentStreamSrc = computed(() => {
  const base = buildAgentStreamUrl(agentStreamToken.value)
  if (agentStreamAttempt.value <= 0) return base
  const sep = base.includes('?') ? '&' : '?'
  return `${base}${sep}retry=${agentStreamAttempt.value}`
})
function onAgentStreamError(): void {
  agentStreamState.value = 'failed'
  if (!live.value) return
  // Reconnect otomatis berjadwal: kembali ke 'idle' agar <img> dipasang ulang
  // dengan URL berbeda (cache-buster). Backoff 1s,2s,4s,8s lalu 15s, tanpa
  // batas upaya karena kios berjalan seharian; dibersihkan saat sesi berhenti.
  clearAgentStreamRetry()
  const attempt = agentStreamAttempt.value + 1
  const backoff = Math.min(
    AGENT_STREAM_RETRY_BASE_MS * 2 ** Math.min(attempt - 1, 4),
    AGENT_STREAM_RETRY_MAX_MS,
  )
  agentStreamRetryTimer = setTimeout(() => {
    agentStreamAttempt.value = attempt
    agentStreamState.value = 'idle'
  }, backoff)
}
function loadKioskStreamToken(): void {
  agentStreamToken.value = captureKioskStreamTokenFromQuery()
}

type AgentHintFace = {
  x: number
  y: number
  width: number
  height: number
  landmarks?: number[][] | null
  acceptable?: boolean | null
  quality_score?: number | null
  reason_codes?: string[] | null
}

interface AgentHint {
  device_id: string | null
  session_active: boolean
  camera_open: boolean
  recognition_state: string | null
  face_present: boolean
  face_count: number
  faces: AgentHintFace[]
  attendance_result: string | null
}
// Verifikasi pairing (fail-closed): layar kios (deviceId) hanya menampilkan
// video setelah hint loopback membawa identitas agent lokal yang cocok.
// - device_id berbeda -> mismatch: video disembunyikan + kesalahan konfigurasi
//   (bukan video kamera lain yang menyesatkan).
// - hint belum segar / tanpa device_id padahal kios dipasangkan -> unverified:
//   video disembunyikan sampai identitas terverifikasi.
// - tanpa deviceId terpilih (layar rekap / belum memilih kamera) -> tidak ada
//   target pairing; video mengikuti perilaku lama (loopback PC yang sama).
const agentDeviceMismatch = computed(() => {
  if (!deviceId.value) return false
  const hinted = agentHint.value?.device_id
  if (typeof hinted !== 'string' || !hinted) return false
  return hinted.toLowerCase() !== deviceId.value.toLowerCase()
})
const agentPairingUnverified = computed(() => {
  // Hanya untuk kios yang dipasangkan eksplisit ke device. Layar rekap tanpa
  // device terpilih (mode lama) mempertahankan perilaku sebelumnya.
  if (!deviceId.value) return false
  if (!hintFresh.value) return true
  const hinted = agentHint.value?.device_id
  return typeof hinted !== 'string' || !hinted
})
const kioskMesh = useFaceLandmarks(
  agentImage,
  computed(() => agentVideoVisible.value && !agentVideoStale.value),
)
const kioskFaces = computed(() => {
  if (!kioskMesh.faces.value.length) return agentFaces.value
  return kioskMesh.faces.value.map((face, index) => ({
    ...agentFaces.value[index],
    ...face,
  }))
})
const kioskMeshSize = computed(() => kioskMesh.frameSize.value)
const kioskFrameSize = computed(() =>
  showBrowserCamera.value && localFrameSize.value.width > 0 && localFrameSize.value.height > 0
    ? localFrameSize.value
    : kioskMeshSize.value.width > 0 && kioskMeshSize.value.height > 0
      ? kioskMeshSize.value
      : agentFrameSize.value,
)
const agentFaceCount = computed(() => (hintFresh.value ? agentHint.value?.face_count : 0) ?? 0)
// The agent only publishes face counts while a session is active. Keep the
// kiosk's visible face indicator useful before that by using the same local
// dense mesh that draws the overlay. A detected face is not an identity match.
const kioskFaceCount = computed(() => Math.max(agentFaceCount.value, kioskMesh.faces.value.length))
const agentLargestOk = computed(() => agentFaces.value.some((face) => face.acceptable === true))
let hintTimer: ReturnType<typeof setInterval> | undefined
let hintAbort: AbortController | null = null

async function pollAgentHint(): Promise<void> {
  if (!live.value?.session_id) {
    agentHint.value = null
    return
  }
  hintAbort?.abort()
  hintAbort = new AbortController()
  const timer = setTimeout(() => hintAbort?.abort(), 900)
  try {
    const response = await fetch(agentHintUrl.value, {
      cache: 'no-store',
      signal: hintAbort.signal,
    })
    if (!response.ok) throw new Error('hint tidak tersedia')
    lastHintOkAt = Date.now()
    hintFresh.value = true
    const data = (await response.json()) as Partial<AgentHint>
    const rawFaces = Array.isArray(data.faces) ? data.faces.slice(0, 5) : []
    agentHint.value = {
      device_id: typeof data.device_id === 'string' ? data.device_id : null,
      session_active: data.session_active === true,
      camera_open: data.camera_open === true,
      recognition_state: typeof data.recognition_state === 'string' ? data.recognition_state : null,
      face_present: data.face_present === true,
      face_count: typeof data.face_count === 'number' ? data.face_count : 0,
      faces: rawFaces.filter(
        (face): face is AgentHintFace =>
          typeof face === 'object' &&
          face !== null &&
          typeof (face as AgentHintFace).x === 'number',
      ),
      attendance_result: typeof data.attendance_result === 'string' ? data.attendance_result : null,
    }
  } catch {
    // Gagal poll sesaat: PERTAHANKAN hint terakhir agar status mismatch tidak
    // hilang (fail-open) saat jaringan loopback tersendat; hanya tandai stale
    // bila jeda >3 dtk. Hint hanya dikosongkan saat tidak ada sesi aktif.
    if (Date.now() - lastHintOkAt > 3000) hintFresh.value = false
  } finally {
    clearTimeout(timer)
  }
}

function startHintPolling(): void {
  stopHintPolling()
  void pollAgentHint()
  hintTimer = setInterval(() => void pollAgentHint(), 1000)
}

function stopHintPolling(): void {
  if (hintTimer) clearInterval(hintTimer)
  hintTimer = undefined
  hintAbort?.abort()
  hintAbort = null
  agentHint.value = null
}

const STATUS_GUIDE = [
  { key: 'waiting', label: 'Menunggu', hint: 'Silakan berdiri di dalam bingkai' },
  {
    key: 'adjust',
    label: 'Perlu penyesuaian',
    hint: 'Hadapkan wajah / maju sedikit / satu orang dulu',
  },
  { key: 'processing', label: 'Memproses', hint: 'Sedang memeriksa…' },
  { key: 'present', label: 'Hadir ✓', hint: 'Presensi tercatat' },
  { key: 'late', label: 'Terlambat', hint: 'Badge TERLAMBAT + menit keterlambatan' },
  { key: 'duplicate', label: 'Sudah tercatat', hint: 'Anda sudah tercatat' },
  { key: 'retry', label: 'Coba ulang', hint: 'Wajah belum dapat dipastikan' },
  { key: 'unready', label: 'Belum dibuka', hint: 'Presensi belum dibuka. Tunggu petugas' },
] as const

function formatError(err: unknown): string {
  if (err instanceof ApiError) return err.message
  return 'Layar tidak dapat dimuat.'
}

async function loadLabs(): Promise<void> {
  isLoadingLabs.value = true
  try {
    labs.value = await listPublicLaboratories()
    if (!labId.value && labs.value.length) labId.value = labs.value[0].id
  } catch (err) {
    error.value = formatError(err)
  } finally {
    isLoadingLabs.value = false
  }
}

async function loadKiosks(preserveSelection = false): Promise<void> {
  const preferredDeviceId = deviceId.value
  kiosks.value = []
  if (!labId.value) {
    deviceId.value = ''
    return
  }
  try {
    kiosks.value = await listPublicKioskScreens(labId.value)
    if (preserveSelection) {
      deviceId.value = preferredDeviceId
    } else {
      deviceId.value = kiosks.value.length === 1 ? kiosks.value[0].device_id : ''
    }
  } catch {
    kiosks.value = []
    if (!preserveSelection) deviceId.value = ''
  }
}

async function initializeDisplay(): Promise<void> {
  loadKioskStreamToken()
  await loadLabs()
  await loadKiosks(Boolean(restoredSession))
  initializingDisplay = false

  if (!restoredSession) {
    isRestoringDisplay.value = false
    return
  }
  await loadDisplay()
  if (display.value) {
    connectStream()
    scheduleRotation(Math.ceil((restoredSession.expiresAt - Date.now()) / 1000))
  }
  isRestoringDisplay.value = false
}

function toLive(snapshot: PublicDisplay): KioskLiveUpdate {
  const rows = snapshot.students ?? []
  const present = rows.filter((r) => r.status === 'present').length
  const late = rows.filter((r) => r.status === 'late').length
  const latest = [...rows]
    .filter((r) => (r.status === 'present' || r.status === 'late') && r.recorded_at)
    .sort((a, b) => String(b.recorded_at).localeCompare(String(a.recorded_at)))[0]
  return {
    laboratory_id: snapshot.laboratory_id,
    laboratory_name: snapshot.laboratory_name,
    session_id: snapshot.session_id ?? null,
    subject: snapshot.subject ?? null,
    class_name: snapshot.class_name ?? null,
    status: snapshot.status ?? null,
    opened_at: snapshot.opened_at ?? null,
    present_count: snapshot.present_count ?? present,
    late_count: snapshot.late_count ?? late,
    waiting_count: Math.max((snapshot.total_roster ?? rows.length) - present - late, 0),
    total_roster: snapshot.total_roster ?? rows.length,
    spotlight: latest
      ? {
          full_name: latest.full_name,
          status: latest.status,
          recorded_at: latest.recorded_at ?? null,
          recognition_event_id: null,
          source: null,
        }
      : null,
    grace_period_minutes: null,
    server_time: new Date().toISOString(),
  }
}

function applyPollSnapshot(snapshot: PublicDisplay): void {
  display.value = { ...snapshot, students: [] }
  live.value = toLive(snapshot)
}

async function loadDisplay(silent = false): Promise<void> {
  if (!displayToken.value) return
  if (!silent) isLoadingDisplay.value = true
  try {
    const snapshot = deviceId.value
      ? await getKioskDisplay(displayToken.value)
      : await getPublicDisplay(displayToken.value)
    applyPollSnapshot(snapshot)
    error.value = null
  } catch (err) {
    if (!silent) error.value = formatError(err)
    if (err instanceof ApiError && (err.status === 401 || err.status === 404)) {
      stopLive()
      clearPersistedDisplaySession()
      displayToken.value = ''
      display.value = null
      live.value = null
      error.value = 'Sesi layar berakhir. Masukkan PIN petugas untuk mengaktifkan kembali.'
    }
  } finally {
    if (!silent) isLoadingDisplay.value = false
  }
}

function disconnectStream(): void {
  if (eventSource) {
    eventSource.close()
    eventSource = null
  }
  if (fetchAbort) {
    fetchAbort.abort()
    fetchAbort = null
  }
  if (pollTimer) clearInterval(pollTimer)
  pollTimer = undefined
}

function startPolling(): void {
  disconnectStream()
  streamState.value = 'polling'
  pollTimer = setInterval(() => void loadDisplay(true), 5000)
  startHintPolling()
}

function applySnapshotEvent(raw: string): void {
  try {
    const update = JSON.parse(raw) as KioskLiveUpdate
    const prevSession = live.value?.session_id ?? null
    const prevEvent = live.value?.spotlight?.recognition_event_id ?? null
    if (prevSession !== null && update.session_id !== null && update.session_id !== prevSession) {
      seenSpotlightIds.value.clear()
    }
    const incomingEvent = update.spotlight?.recognition_event_id ?? null
    if (incomingEvent !== null) {
      if (seenSpotlightIds.value.has(incomingEvent) && incomingEvent === prevEvent) {
        // Duplikat SSE (mis. reconnect mengirim sorotan lama yang sama):
        // pertahankan agregat terbaru tetapi jangan anggap sebagai scan baru.
        // Kesegaran tetap dihitung dari recorded_at, bukan waktu tiba.
        void 0
      }
      seenSpotlightIds.value.add(incomingEvent)
    }
    live.value = update
    // session_id bisa tiba lewat push pertama; segarkan hint generik.
    if (update.session_id) void pollAgentHint()
    if (display.value) {
      display.value = {
        ...display.value,
        laboratory_name: update.laboratory_name,
        session_id: update.session_id,
        subject: update.subject,
        class_name: update.class_name,
        status: update.status,
        opened_at: update.opened_at,
        students: [],
      }
    }
    error.value = null
  } catch {
    /* abaikan frame rusak */
  }
}

function connectEventSourceFallback(): void {
  // Fallback lawas: token di query URL (tercatat di riwayat/proxy).
  // Dipakai hanya bila fetch streaming tidak tersedia/gagal.
  try {
    const url = deviceId.value
      ? kioskDisplayStreamUrl(displayToken.value)
      : publicDisplayStreamUrl(displayToken.value)
    const src = new EventSource(url)
    eventSource = src
    streamState.value = 'sse'
    src.addEventListener('snapshot', (ev) => {
      applySnapshotEvent((ev as MessageEvent).data)
    })
    src.onerror = () => {
      if (eventSource === src) startPolling()
    }
    startHintPolling()
  } catch {
    startPolling()
  }
}

function connectStream(): void {
  disconnectStream()
  if (!displayToken.value) return
  if (typeof EventSource === 'undefined' && typeof ReadableStream === 'undefined') {
    startPolling()
    return
  }
  // Utama: fetch + ReadableStream agar token lewat header Authorization,
  // bukan query URL. EventSource (query token) hanya fallback.
  const path = deviceId.value ? kioskDisplayStreamPath() : publicDisplayStreamPath()
  const token = displayToken.value
  if (typeof ReadableStream !== 'undefined' && typeof fetch !== 'undefined') {
    const controller = new AbortController()
    fetchAbort = controller
    streamState.value = 'sse'
    startHintPolling()
    void streamDisplayUpdates(path, token, controller.signal, (event, data, done) => {
      if (event === 'error') {
        if (data.includes('display_token_invalid')) {
          done()
          void loadDisplay(true).then(() => {
            if (fetchAbort === controller) connectEventSourceFallback()
          })
          return
        }
        return
      }
      if (event === 'snapshot') applySnapshotEvent(data)
    }).catch((error: unknown) => {
      if (fetchAbort !== controller) return
      fetchAbort = null
      if (error instanceof ApiError && (error.status === 401 || error.status === 403)) {
        void loadDisplay(true)
      }
      connectEventSourceFallback()
    })
    return
  }
  connectEventSourceFallback()
}
function clearRotation(): void {
  if (rotationTimer) clearTimeout(rotationTimer)
  rotationTimer = undefined
}

async function rotateToken(): Promise<void> {
  if (!displayToken.value) return
  try {
    const rotated = deviceId.value
      ? await rotateKioskDisplaySession(displayToken.value)
      : await rotatePublicDisplaySession(displayToken.value)
    displayToken.value = rotated.display_token
    persistDisplaySession(rotated.display_token, rotated.expires_in_seconds)
    applyPollSnapshot(rotated.snapshot)
    connectStream()
    scheduleRotation(rotated.expires_in_seconds)
  } catch (err) {
    if (err instanceof ApiError && (err.status === 401 || err.status === 404)) {
      stopLive()
      clearPersistedDisplaySession()
      displayToken.value = ''
      display.value = null
      live.value = null
      error.value = 'Sesi layar berakhir. Masukkan PIN petugas untuk mengaktifkan kembali.'
    }
  }
}

function scheduleRotation(expiresInSeconds: number | undefined): void {
  clearRotation()
  if (!expiresInSeconds || expiresInSeconds <= 0) return
  const ahead = expiresInSeconds > ROTATE_AHEAD_SECONDS ? ROTATE_AHEAD_SECONDS : 0
  const delayMs = Math.max((expiresInSeconds - ahead) * 1000, 30_000)
  rotationTimer = setTimeout(() => void rotateToken(), delayMs)
}

function stopLive(): void {
  disconnectStream()
  clearRotation()
  stopHintPolling()
  stopLocalCamera()
  clearAgentStreamRetry()
  agentStreamAttempt.value = 0
  agentStreamState.value = 'idle'
  showBrowserCamera.value = false
  streamState.value = 'off'
}

async function startLocalCamera(): Promise<void> {
  cameraState.value = 'idle'
  if (typeof window === 'undefined' || !window.isSecureContext) {
    cameraState.value = 'insecure'
    return
  }
  const media = window.navigator as Navigator & { mediaDevices?: MediaDevices }
  if (!media.mediaDevices?.getUserMedia) {
    cameraState.value = 'unavailable'
    return
  }
  try {
    const stream = await media.mediaDevices.getUserMedia({
      video: { width: { ideal: 1280 }, height: { ideal: 720 }, facingMode: 'user' },
      audio: false,
    })
    localStream = stream
    await attachLocalStream(stream)
  } catch {
    stopLocalCameraTracks()
    cameraState.value = 'unavailable'
  }
}

async function attachLocalStream(stream: MediaStream): Promise<void> {
  // <video> hanya eksis setelah cameraState=active (v-if): render dulu,
  // baru pasang srcObject. Tanpa ini stream menguap dan preview hitam.
  cameraState.value = 'active'
  await nextTick()
  if (localVideo.value) {
    localVideo.value.srcObject = stream
    const updateFrameSize = (): void => {
      const video = localVideo.value
      if (video && video.videoWidth > 0 && video.videoHeight > 0) {
        localFrameSize.value = { width: video.videoWidth, height: video.videoHeight }
      }
    }
    localVideo.value.onloadedmetadata = updateFrameSize
    updateFrameSize()
    const play = localVideo.value.play() as unknown as Promise<void> | undefined
    if (play && typeof play.catch === 'function') await play.catch(() => undefined)
  }
}

function stopLocalCameraTracks(): void {
  if (localStream) {
    localStream.getTracks().forEach((track) => track.stop())
    localStream = null
  }
  if (localVideo.value) localVideo.value.srcObject = null
}

function stopLocalCamera(): void {
  stopLocalCameraTracks()
  cameraState.value = 'idle'
}

function enableBrowserFallback(): void {
  showBrowserCamera.value = true
  void startLocalCamera()
}

async function submit(): Promise<void> {
  if (!labId.value || !pin.value) return
  // Request fullscreen during the activation click. Browsers require a direct
  // user gesture and will reject an attempt made after the PIN request awaits.
  requestKioskFullscreen()
  isLoadingDisplay.value = true
  error.value = null
  try {
    const opened = deviceId.value
      ? await openKioskDisplaySession(deviceId.value, pin.value)
      : await openPublicDisplaySession(labId.value, pin.value)
    displayToken.value = opened.display_token
    clearPersistedDisplaySession()
    persistDisplaySession(opened.display_token, opened.expires_in_seconds)
    applyPollSnapshot(opened.snapshot)
    pin.value = ''
    connectStream()
    scheduleRotation(opened.expires_in_seconds)
    // Single-owner: browser TIDAK membuka kamera di PC lab. Video tampil
    // dari stream agent yang sama dengan inference; hint memberi overlay.
    clearAgentStreamRetry()
    agentStreamAttempt.value = 0
    agentStreamState.value = 'idle'
    showBrowserCamera.value = false
  } catch (err) {
    error.value = formatError(err)
  } finally {
    isLoadingDisplay.value = false
  }
}

function syncFullscreenState(): void {
  isFullscreen.value = Boolean(document.fullscreenElement)
  if (isFullscreen.value) fullscreenError.value = null
}

const fullscreenFailureMessage =
  'Browser menolak layar penuh. Coba tombol “Masuk layar penuh” sekali lagi. Untuk kiosk otomatis tanpa tab, jalankan Chrome dalam mode kiosk.'

function requestKioskFullscreen(): void {
  const root = displayRoot.value
  if (document.fullscreenElement) {
    syncFullscreenState()
    return
  }
  if (!root?.requestFullscreen) {
    fullscreenError.value = fullscreenFailureMessage
    return
  }
  try {
    void root
      .requestFullscreen({ navigationUI: 'hide' })
      .then(syncFullscreenState)
      .catch(() => {
        syncFullscreenState()
        fullscreenError.value = fullscreenFailureMessage
      })
  } catch {
    syncFullscreenState()
    fullscreenError.value = fullscreenFailureMessage
  }
}

async function toggleFullscreen(): Promise<void> {
  fullscreenError.value = null
  try {
    if (document.fullscreenElement) {
      await document.exitFullscreen()
    } else if (displayRoot.value?.requestFullscreen) {
      await displayRoot.value.requestFullscreen({ navigationUI: 'hide' })
    } else {
      throw new Error('Fullscreen tidak didukung browser ini.')
    }
    syncFullscreenState()
  } catch {
    syncFullscreenState()
    fullscreenError.value = fullscreenFailureMessage
  }
}

const now = ref(new Date())
let clockTimer: ReturnType<typeof setInterval> | undefined
const clockWib = computed(() => {
  try {
    return new Intl.DateTimeFormat('id-ID', {
      hour: '2-digit',
      minute: '2-digit',
      timeZone: 'Asia/Jakarta',
    })
      .format(now.value)
      .replace(':', '.')
  } catch {
    return ''
  }
})
const dateLine = computed(() => {
  try {
    return new Intl.DateTimeFormat('id-ID', {
      weekday: 'long',
      day: 'numeric',
      month: 'long',
      year: 'numeric',
      timeZone: 'Asia/Jakarta',
    }).format(now.value)
  } catch {
    return ''
  }
})
const terminalId = computed(() => {
  if (deviceId.value) {
    const k = kiosks.value.find((x) => x.device_id === deviceId.value)
    const base = (k?.display_name ?? deviceId.value)
      .toUpperCase()
      .replace(/[^A-Z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '')
      .replace(/^KIOSK-/, '')
      .slice(0, 24)
    return `KIOSK-${base || 'LAB-01'}`
  }
  const lab = labs.value.find((l) => l.id === labId.value)
  const code = (lab?.code ?? 'LAB').toUpperCase().replace(/[^A-Z0-9]+/g, '-')
  return `KIOSK-${code || 'LAB'}-01`
})
const sessionStateLabel = computed(() => {
  if (!display.value) return 'Menunggu aktivasi petugas'
  if (live.value?.status === 'scheduled') return 'Jadwal menunggu dibuka'
  if (live.value?.status === 'closed') return 'Sesi sudah ditutup'
  if (live.value?.status === 'cancelled') return 'Sesi dibatalkan'
  if (!live.value?.session_id) return 'Belum ada sesi aktif'
  return live.value.status === 'manual_override'
    ? 'Sesi aktif · dibuka manual'
    : 'Sesi aktif · sudah dibuka'
})
const sessionDetailsLabel = computed(() => {
  if (!display.value) return ''
  const details = [live.value?.subject, live.value?.class_name].filter((value): value is string =>
    Boolean(value),
  )
  return details.length
    ? `${details.join(' · ')} · ${display.value.laboratory_name}`
    : display.value.laboratory_name
})
const sessionOpenedLabel = computed(() => {
  if (!display.value) return ''
  if (live.value?.status === 'scheduled') {
    return 'Belum dibuka oleh guru atau laboran.'
  }
  if (!live.value?.session_id || !live.value.opened_at) return ''
  return `Dibuka ${formatRecordedTime(live.value.opened_at)} WIB`
})
const sessionStatsLabel = computed(() => {
  if (!live.value?.session_id) return ''
  return [
    `Hadir ${live.value.present_count}`,
    `Terlambat ${live.value.late_count}`,
    `Menunggu ${live.value.waiting_count} dari ${live.value.total_roster}`,
  ].join(' · ')
})

const spotlight = computed(() => live.value?.spotlight ?? null)
const kioskResultTitle = computed(() => {
  if (live.value?.status === 'scheduled') {
    return kioskFaceCount.value > 0 ? 'Wajah terdeteksi' : 'Menunggu petugas membuka sesi'
  }
  if (!live.value?.session_id) {
    return kioskFaceCount.value > 0 ? 'Wajah terdeteksi' : 'Kamera siap menunggu sesi'
  }
  if (agentHint.value?.recognition_state === 'waiting_for_calibration') {
    return 'Pengenalan belum siap'
  }
  if (
    agentHint.value?.recognition_state === 'checking' ||
    agentHint.value?.recognition_state === 'collecting' ||
    agentHint.value?.attendance_result === 'pending'
  ) {
    return 'Memeriksa kehadiran'
  }
  return kioskFaceCount.value > 0 ? 'Wajah terdeteksi' : 'Menunggu siswa'
})

const kioskRecognitionMessage = computed(() => {
  if (live.value?.status === 'scheduled') {
    return kioskFaceCount.value > 0
      ? 'Pencocokan identitas dimulai setelah guru atau laboran membuka jadwal ini.'
      : 'Jadwal tersedia. Guru atau laboran perlu membuka sesi sebelum presensi dimulai.'
  }
  if (!live.value?.session_id) {
    return kioskFaceCount.value > 0
      ? 'Wajah terlihat, tetapi belum dicocokkan. AI hanya mencari siswa pada roster sesi yang dibuka.'
      : 'Kamera menunggu guru atau laboran membuka sesi agar roster siswa dapat dimuat.'
  }
  if (agentDeviceMismatch.value) {
    return 'Perangkat kamera berbeda dari kiosk ini. Identitas tidak akan diperiksa sampai perangkatnya cocok.'
  }
  if (agentPairingUnverified.value) {
    return 'Menunggu verifikasi pasangan perangkat kamera kiosk.'
  }
  if (agentCameraDown.value) {
    return 'Kamera agent sedang dijeda atau tidak tersedia. Aktifkan kamera pada perangkat lab.'
  }
  if (agentHint.value?.recognition_state === 'waiting_for_calibration') {
    return 'Pengenalan wajah belum siap. Hubungi petugas untuk menyelesaikan kalibrasi.'
  }
  if (
    agentHint.value?.recognition_state === 'checking' ||
    agentHint.value?.recognition_state === 'collecting'
  ) {
    return 'AI sedang memeriksa beberapa frame. Tahan posisi dan pastikan hanya satu siswa di depan kamera.'
  }
  if (agentHint.value?.recognition_state === 'retry_frontal') {
    return 'Wajah belum cukup jelas untuk dicocokkan. Hadapkan wajah lurus ke kamera.'
  }
  if (agentHint.value?.recognition_state === 'rejected') {
    return 'Wajah terlihat, tetapi belum cocok atau kualitas frame belum cukup. Periksa posisi dan fokus kamera.'
  }
  if (agentHint.value?.recognition_state === 'accepted') {
    return 'Identitas cocok sementara. Menunggu Core API memvalidasi roster sebelum nama ditampilkan.'
  }
  if (agentHint.value && !agentHint.value.session_active) {
    return 'Agent belum menerima roster sesi aktif. Pastikan sesi dibuka untuk lab dan kelas yang benar.'
  }
  if (!hintFresh.value || !agentHint.value) {
    return 'Menunggu status AI dari agent kamera. Nama hanya tampil setelah hasil presensi dikonfirmasi.'
  }
  if (agentHint.value.attendance_result === 'pending') {
    return 'Wajah sedang diperiksa. Nama dan status akan tampil setelah Core API mengonfirmasi presensi.'
  }
  if (agentHint.value.face_present) {
    return 'Wajah terdeteksi. Nama kandidat tidak ditampilkan di kiosk; nama muncul setelah presensi cocok dan dikonfirmasi.'
  }
  return 'Sesi aktif. Berdiri satu orang di depan kamera; nama akan tampil setelah presensi dikonfirmasi.'
})

const spotlightFresh = computed(() => {
  void now.value
  const recorded = spotlight.value?.recorded_at
  if (!recorded) return false
  const ts = new Date(recorded).getTime()
  if (Number.isNaN(ts)) return false
  return Date.now() - ts < 4000
})

// Tampilkan progres hanya ketika pipeline benar-benar sedang memeriksa frame
// atau menunggu konfirmasi API. Deteksi wajah saja tidak berarti verifikasi
// sedang berlangsung (mis. saat menunggu kalibrasi).
const showVerifying = computed(() => {
  if (!live.value?.session_id || streamState.value === 'off') return false
  if (spotlightFresh.value) return false
  if (!hintFresh.value) return false
  const hint = agentHint.value
  if (!hint || !hint.session_active) return false
  if (hint.recognition_state === 'waiting_for_calibration') return false
  return (
    hint.recognition_state === 'checking' ||
    hint.recognition_state === 'collecting' ||
    hint.attendance_result === 'pending'
  )
})

function formatRecordedTime(value: string | null | undefined): string {
  if (!value) return '-'
  try {
    return timeFormatterFor('Asia/Jakarta').format(new Date(value))
  } catch {
    return '-'
  }
}

function resetSession(): void {
  stopLive()
  clearRotation()
  stopLocalCamera()
  clearPersistedDisplaySession()
  displayToken.value = ''
  display.value = null
  live.value = null
  seenSpotlightIds.value.clear()
}

watch(labId, () => {
  if (initializingDisplay) return
  resetSession()
  void loadKiosks()
})
watch(deviceId, () => {
  if (!initializingDisplay) resetSession()
})

onMounted(() => {
  void initializeDisplay()
  document.addEventListener('fullscreenchange', syncFullscreenState)
  clockTimer = setInterval(() => {
    now.value = new Date()
  }, 1000)
})
onBeforeUnmount(() => {
  document.removeEventListener('fullscreenchange', syncFullscreenState)
  stopLive()
  clearRotation()
  stopLocalCamera()
  if (clockTimer) clearInterval(clockTimer)
})
</script>

<template>
  <section ref="displayRoot" class="display-view kiosk" aria-label="Layar presensi publik">
    <header class="kiosk__top">
      <div class="kiosk__brand">
        <img
          class="kiosk__logo"
          :src="schoolLogoUrl"
          alt="Logo SMA Cimahi"
          width="56"
          height="56"
        />
        <span class="kiosk__brand-text">
          <strong>Presensi Praktikum</strong>
          <small>Layar Kiosk Siswa · SMA Taruna Nusantara Kampus Cimahi</small>
        </span>
      </div>
      <div class="kiosk__clock">
        <strong>{{ clockWib }} <small>WIB</small></strong>
        <small>{{ dateLine }}</small>
      </div>
    </header>

    <main v-if="isRestoringDisplay" class="kiosk__restore" role="status">
      Memulihkan sesi kiosk…
    </main>

    <main v-else-if="!display" class="kiosk__activate-wrap">
      <div class="kiosk__activate-info">
        <p class="kiosk__eyebrow">Kiosk mandiri · tanpa login staf</p>
        <h1>Aktivasi Layar Presensi Kiosk</h1>
        <p class="kiosk__desc">
          Pilih alokasi ruangan laboratorium dan pasangkan kamera sebelum siswa melakukan presensi.
        </p>
        <ol class="kiosk__steps">
          <li>Pilih laboratorium penempatan layar ini.</li>
          <li>Pilih kamera yang diizinkan untuk lab tersebut.</li>
          <li>Masukkan PIN petugas 6 digit, lalu mulai layar.</li>
        </ol>
        <p class="kiosk__note">
          Layar ini berjalan mandiri tanpa login staf. PIN hanya dimasukkan saat aktivasi awal atau
          pergantian perangkat. Hubungi Administrator bila PIN belum diterbitkan.
        </p>
      </div>
      <div class="kiosk__activate-card" data-testid="display-activate-card">
        <h2>Aktivasi petugas</h2>
        <form @submit.prevent="submit">
          <fieldset class="kiosk__field">
            <legend>Laboratorium Penempatan <span aria-hidden="true">*</span></legend>
            <div class="kiosk__radios" data-testid="display-lab-select">
              <label
                v-for="lab in labs"
                :key="lab.id"
                class="kiosk__radio"
                :class="{ 'kiosk__radio--active': labId === lab.id }"
              >
                <input v-model="labId" type="radio" :value="lab.id" name="kiosk-lab" required />
                <span
                  ><strong>{{ lab.code }}</strong
                  ><small>{{ lab.name }}</small></span
                >
              </label>
            </div>
            <p v-if="isLoadingLabs" class="kiosk__muted">Memuat laboratorium…</p>
          </fieldset>
          <fieldset class="kiosk__field">
            <legend>Kamera yang Diizinkan <span aria-hidden="true">*</span></legend>
            <div class="kiosk__radios">
              <label class="kiosk__radio" :class="{ 'kiosk__radio--active': deviceId === '' }">
                <input v-model="deviceId" type="radio" value="" name="kiosk-cam" />
                <span><strong>Otomatis</strong><small>Sesi lab · kamera default</small></span>
              </label>
              <label
                v-for="k in kiosks"
                :key="k.device_id"
                class="kiosk__radio"
                :class="{ 'kiosk__radio--active': deviceId === k.device_id }"
              >
                <input v-model="deviceId" type="radio" :value="k.device_id" name="kiosk-cam" />
                <span
                  ><strong>{{ k.display_name }}</strong
                  ><small>{{ k.camera_label ?? 'Pintu Masuk 01' }}</small></span
                >
              </label>
            </div>
            <p v-if="deviceId" class="kiosk__muted" role="note">
              Kamera kiosk dipilih otomatis - gunakan PIN kiosk layar ini, bukan PIN lab.
            </p>
          </fieldset>
          <label class="kiosk__field kiosk__pin">
            <span>PIN Petugas (6 Digit) <span aria-hidden="true">*</span></span>
            <small class="kiosk__muted">Otorisasi Laboran/Admin</small>
            <UiInput
              v-model="pin"
              type="password"
              inputmode="numeric"
              minlength="4"
              maxlength="32"
              placeholder="••••••"
              autocomplete="one-time-code"
              data-testid="display-pin-input"
              required
            />
          </label>
          <p v-if="error" class="kiosk__error" role="alert">{{ error }}</p>
          <p v-if="fullscreenError" class="kiosk__error" role="alert">
            {{ fullscreenError }}
          </p>
          <UiButton variant="primary" type="submit" :disabled="isLoadingDisplay" class="kiosk__cta">
            {{ isLoadingDisplay ? 'Memuat…' : 'Mulai Layar Presensi' }}
          </UiButton>
          <UiButton
            variant="secondary"
            type="button"
            class="kiosk__fullscreen-setup"
            :aria-pressed="isFullscreen"
            :aria-label="isFullscreen ? 'Keluar layar penuh' : 'Masuk layar penuh'"
            data-testid="display-activation-fullscreen"
            @click="void toggleFullscreen()"
          >
            <span class="st-material-icon" aria-hidden="true">
              {{ isFullscreen ? 'fullscreen_exit' : 'fullscreen' }}
            </span>
            {{ isFullscreen ? 'Keluar layar penuh' : 'Masuk layar penuh' }}
          </UiButton>
        </form>
        <footer class="kiosk__terminal">
          <span
            >Terminal ID: <strong>{{ terminalId }}</strong></span
          >
          <span>Core API Handshake Terhubung</span>
          <span>Keamanan Kiosk: Token Tanpa Akses Roster / Read-Only Biometrik</span>
        </footer>
      </div>
    </main>

    <main v-else class="kiosk__board" data-testid="display-board">
      <div class="kiosk__stage">
        <div class="kiosk__camera" aria-label="Bingkai kamera">
          <p class="kiosk__camera-badge">
            <span
              class="kiosk__dot"
              :class="{
                'kiosk__dot--live': cameraState === 'active',
                'kiosk__dot--idle': cameraState !== 'active',
              }"
              aria-hidden="true"
            />
            {{
              agentDeviceMismatch
                ? 'Kamera Tidak Sesuai'
                : agentPairingUnverified
                  ? 'Memverifikasi Kamera…'
                  : agentCameraDown
                    ? 'Kamera Lab Tidak Tersedia'
                    : agentVideoStale
                      ? 'Menghubungkan Ulang Kamera Lab…'
                      : agentStreamState === 'live'
                        ? 'Kamera Lab Aktif (Agent)'
                        : agentStreamState === 'failed'
                          ? showBrowserCamera && cameraState === 'active'
                            ? 'Kamera Perangkat (Diagnostik)'
                            : 'Stream Lab Terputus'
                          : 'Menghubungkan Kamera Lab…'
            }}
          </p>
          <CameraFrame
            :faces="agentVideoVisible && !agentVideoStale ? kioskFaces : []"
            :image-width="kioskFrameSize.width"
            :image-height="kioskFrameSize.height"
            :label="kioskFaceCount > 1 ? `Wajah utama · ${kioskFaceCount} wajah` : 'Wajah utama'"
          >
            <img
              v-if="agentVideoVisible && !agentVideoStale"
              ref="agentImage"
              :src="agentStreamSrc"
              crossorigin="anonymous"
              class="camera-frame__media"
              alt="Preview kamera lab dari agent (sumber inference yang sama)"
              data-testid="display-agent-video"
              @load="onAgentStreamLoad"
              @error="onAgentStreamError"
            />
            <span
              v-else-if="agentCameraDown || agentVideoStale"
              class="camera-frame__placeholder"
              aria-hidden="true"
              >{{ agentCameraDown ? 'Kamera tidak tersedia' : 'Menghubungkan ulang…' }}</span
            >
            <video
              v-else-if="showBrowserCamera && cameraState === 'active'"
              ref="localVideo"
              class="camera-frame__media"
              playsinline
              autoplay
              muted
              aria-label="Preview kamera perangkat (diagnostik)"
              data-testid="display-local-video"
            />
            <span v-else class="camera-frame__placeholder" aria-hidden="true"
              >Berdiri di dalam bingkai</span
            >
          </CameraFrame>
          <p v-if="agentDeviceMismatch" class="kiosk__muted" role="alert">
            Layar ini dipasangkan ke kamera lain. Video disembunyikan agar tidak menyesatkan.
            Hubungi operator untuk memasangkan ulang perangkat yang benar.
          </p>
          <p v-else-if="agentPairingUnverified" class="kiosk__muted" role="note">
            Memverifikasi identitas kamera lab sebelum menampilkan video. Pastikan agent di PC ini
            dikonfigurasi dengan device yang sama dengan layar kios.
          </p>
          <p class="kiosk__camera-meta">
            <UiBadge
              :tone="kioskFaceCount > 1 ? 'late' : kioskFaceCount === 1 ? 'present' : 'neutral'"
            >
              {{
                kioskFaceCount > 1
                  ? `${kioskFaceCount} wajah`
                  : kioskFaceCount === 1
                    ? '1 wajah'
                    : 'Belum ada wajah'
              }}
            </UiBadge>
            <span v-if="kioskFaceCount > 1" class="kiosk__muted">Satu siswa di depan kamera.</span>
            <span v-else-if="agentLargestOk" class="kiosk__muted"
              >Bingkai hijau siap diverifikasi.</span
            >
          </p>
          <p
            v-if="agentStreamState === 'failed' && !showBrowserCamera"
            class="kiosk__muted"
            role="note"
          >
            Stream kamera lab tidak tersedia di PC ini. Mencoba menghubungkan ulang otomatis. Hasil
            presensi tetap tampil.
            <UiButton variant="text" type="button" @click="enableBrowserFallback()">
              Pakai kamera perangkat (diagnostik)
            </UiButton>
          </p>
          <p v-if="streamState === 'polling'" class="kiosk__muted" role="note">
            Mode polling 5 detik (stream realtime tidak tersedia).
          </p>
          <div class="kiosk__board-actions">
            <UiButton
              variant="secondary"
              type="button"
              :aria-pressed="isFullscreen"
              :aria-label="isFullscreen ? 'Keluar layar penuh' : 'Masuk layar penuh'"
              data-testid="display-fullscreen-toggle"
              @click="void toggleFullscreen()"
            >
              <span class="st-material-icon" aria-hidden="true">
                {{ isFullscreen ? 'fullscreen_exit' : 'fullscreen' }}
              </span>
              {{ isFullscreen ? 'Keluar layar penuh' : 'Masuk layar penuh' }}
            </UiButton>
            <UiButton
              class="kiosk__icon-button"
              variant="text"
              type="button"
              aria-label="Ganti layar"
              title="Ganti layar"
              data-testid="display-change-screen"
              @click="resetSession"
            >
              <span class="st-material-icon" aria-hidden="true">close</span>
            </UiButton>
          </div>
          <p
            v-if="fullscreenError"
            class="kiosk__error"
            role="alert"
            data-testid="fullscreen-error"
          >
            {{ fullscreenError }}
          </p>
        </div>
        <div class="kiosk__result">
          <div v-if="spotlight" class="kiosk__result-card" data-testid="display-spotlight">
            <p class="kiosk__eyebrow">
              {{ spotlightFresh ? 'Hasil Dikonfirmasi' : 'Hasil terakhir' }} ·
              {{ formatRecordedTime(spotlight.recorded_at) }} WIB
            </p>
            <p class="kiosk__session-context" data-testid="display-session-details">
              {{ sessionDetailsLabel }}
            </p>
            <p v-if="sessionOpenedLabel" class="kiosk__muted" data-testid="display-session-opened">
              {{ sessionOpenedLabel }}
            </p>
            <p class="kiosk__session-state" data-testid="display-session-state">
              {{ sessionStateLabel }}
            </p>
            <p
              v-if="sessionStatsLabel"
              class="kiosk__session-stats"
              data-testid="display-session-stats"
            >
              {{ sessionStatsLabel }}
            </p>
            <p class="kiosk__date">{{ dateLine }}</p>
            <p class="kiosk__avatar" aria-hidden="true">
              {{
                shortDisplayName(spotlight.full_name)
                  .split(' ')
                  .map((w) => w[0])
                  .join('')
                  .slice(0, 2)
                  .toUpperCase()
              }}
            </p>
            <p class="kiosk__name">{{ shortDisplayName(spotlight.full_name) }}</p>
            <UiBadge :tone="spotlight.status === 'late' ? 'late' : 'present'">
              {{ spotlight.status === 'late' ? 'TERLAMBAT' : 'HADIR' }}
            </UiBadge>
            <dl v-if="spotlight.status === 'late'" class="kiosk__facts">
              <div>
                <dt>Waktu Kedatangan</dt>
                <dd>{{ formatRecordedTime(spotlight.recorded_at) }} WIB</dd>
              </div>
              <div>
                <dt>Status</dt>
                <dd>Terlambat</dd>
              </div>
            </dl>
            <p v-if="spotlight.status === 'late'" class="kiosk__muted">
              Presensi tercatat dengan catatan keterlambatan melewati batas toleransi
              {{ live?.grace_period_minutes ?? '-' }} menit.
            </p>
            <p v-else-if="spotlight.source === 'manual'" class="kiosk__muted">
              Dicatat manual oleh petugas pada roster praktikum.
            </p>
            <p v-else class="kiosk__muted">Kehadiran Anda tercatat pada roster praktikum.</p>
            <p v-if="spotlightFresh" class="kiosk__countdown">
              Layar kembali ke daftar menunggu otomatis.
            </p>
          </div>
          <div v-else class="kiosk__result-card kiosk__result-card--waiting">
            <p class="kiosk__eyebrow" data-testid="display-session-state">
              {{ sessionStateLabel }}
            </p>
            <h2 data-testid="display-recognition-title">{{ kioskResultTitle }}</h2>
            <p class="kiosk__session-context" data-testid="display-session-details">
              {{ sessionDetailsLabel }}
            </p>
            <p
              v-if="sessionStatsLabel"
              class="kiosk__session-stats"
              data-testid="display-session-stats"
            >
              {{ sessionStatsLabel }}
            </p>
            <p v-if="sessionOpenedLabel" class="kiosk__muted" data-testid="display-session-opened">
              {{ sessionOpenedLabel }}
            </p>
            <p class="kiosk__muted" data-testid="display-recognition-status">
              {{ kioskRecognitionMessage }}
            </p>
            <p
              v-if="live?.session_id"
              class="kiosk__muted"
              data-testid="display-recognition-policy"
            >
              Nama siswa hanya ditampilkan setelah presensi dikonfirmasi oleh Core API.
            </p>
            <p
              v-if="showVerifying"
              class="kiosk__verifying"
              role="status"
              data-testid="display-verifying"
            >
              <span class="kiosk__dot kiosk__dot--live" aria-hidden="true" />
              Memverifikasi kehadiran - tahan posisi wajah…
            </p>
          </div>
          <details class="kiosk__guide">
            <summary>Panduan status layar</summary>
            <ul>
              <li v-for="g in STATUS_GUIDE" :key="g.key">
                <strong>{{ g.label }}</strong> - {{ g.hint }}
              </li>
            </ul>
          </details>
        </div>
      </div>
    </main>
  </section>
</template>

<style scoped>
.display-view.kiosk {
  min-height: 100vh;
  background: #0b2036;
  color: #f1f5f9;
  font-family: var(--st-font);
  padding: 0;
}
.kiosk__top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px 16px;
  flex-wrap: wrap;
  min-height: 88px;
  padding: 12px 32px;
  background: var(--st-primary-container);
  border-bottom: 1px solid #1e3a52;
}
.kiosk__brand {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}
.kiosk__logo {
  display: block;
  width: 72px;
  height: 72px;
  border: 0;
  border-radius: 0;
  box-shadow: none;
  background: none;
  object-fit: contain;
  flex-shrink: 0;
}
.kiosk__brand-text {
  display: grid;
  line-height: 1.25;
}
.kiosk__brand-text strong {
  font-size: 1rem;
}
.kiosk__brand-text small {
  color: #a9bccd;
  font-size: 0.72rem;
}
.kiosk__dot {
  width: 10px;
  height: 10px;
  border-radius: 999px;
  background: #a9bccd;
  flex-shrink: 0;
}
.kiosk__dot--live {
  background: #22c55e;
}
.kiosk__dot--idle {
  background: #fbbf24;
}
.kiosk__clock {
  text-align: right;
  padding-left: 16px;
  border-left: 1px solid #1e3a52;
}
.kiosk__clock strong {
  display: block;
  font-family: monospace;
  font-size: 1.4rem;
}
.kiosk__clock strong small {
  font-size: 0.7rem;
  color: #a9bccd;
}
.kiosk__clock > small {
  color: #a9bccd;
  font-size: 0.75rem;
}
.kiosk__activate-wrap {
  display: grid;
  grid-template-columns: minmax(280px, 5fr) minmax(320px, 7fr);
  gap: 24px;
  align-items: start;
  max-width: 1060px;
  margin: 32px auto 0;
  padding: 0 24px;
}
.kiosk__restore {
  display: grid;
  min-height: calc(100vh - 88px);
  place-items: center;
  padding: 24px;
  color: #c6d4d3;
  font-size: 1rem;
}
.kiosk__activate-info h1 {
  margin: 8px 0;
  font-size: 1.6rem;
  letter-spacing: -0.01em;
}
.kiosk__eyebrow {
  margin: 0;
  font-size: 0.7rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--st-gold);
}
.kiosk__desc {
  color: #c6d4d3;
}
.kiosk__steps {
  display: grid;
  gap: 8px;
  padding-left: 20px;
  color: #c6d4d3;
}
.kiosk__note {
  color: #a9bccd;
  font-size: 0.8rem;
}
.kiosk__activate-card {
  background: var(--st-primary-container);
  border: 1px solid #1e3a52;
  border-radius: 16px;
  padding: 24px;
  box-shadow: 0 8px 24px rgb(0 0 0 / 0.35);
}
.kiosk__activate-card h2 {
  margin: 0 0 12px;
  font-size: 1.1rem;
}
.kiosk__activate-card form {
  display: grid;
  gap: 16px;
}
.kiosk__field {
  border: 0;
  padding: 0;
  margin: 0;
  display: grid;
  gap: 8px;
}
.kiosk__field legend,
.kiosk__pin > span {
  font-size: 0.82rem;
  font-weight: 700;
}
.kiosk__radios {
  display: grid;
  gap: 8px;
}
.kiosk__radio {
  display: flex;
  align-items: center;
  gap: 10px;
  border: 1px solid #1e3a52;
  border-radius: 12px;
  padding: 10px 12px;
  cursor: pointer;
  min-height: 44px;
  background: #0b2036;
}
.kiosk__radio input {
  accent-color: var(--st-gold);
  width: 18px;
  height: 18px;
}
.kiosk__radio span {
  display: grid;
}
.kiosk__radio strong {
  font-size: 0.88rem;
}
.kiosk__radio small {
  color: #a9bccd;
  font-size: 0.75rem;
}
.kiosk__radio--active {
  border-color: var(--st-gold);
}
.kiosk__pin {
  display: grid;
  gap: 6px;
}
.kiosk__muted {
  color: #a9bccd;
  font-size: 0.78rem;
  margin: 0;
}

.kiosk__verifying {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  margin: 0.6rem 0 0;
  padding: 0.45rem 0.8rem;
  border: 1px solid #2dd4bf;
  border-radius: 999px;
  background: rgb(45 212 191 / 0.12);
  color: #99f6e4;
  font-size: 0.82rem;
  font-weight: 600;
  animation: kiosk-verify-pulse 1.2s ease-in-out infinite;
}

@keyframes kiosk-verify-pulse {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.55;
  }
}

@media (prefers-reduced-motion: reduce) {
  .kiosk__verifying {
    animation: none;
  }
}
.kiosk__error {
  margin: 0;
  border-radius: 8px;
  padding: 10px 14px;
  background: #3f1d20;
  color: #ffb4ab;
  font-size: 0.85rem;
}
.kiosk__cta {
  width: 100%;
  min-height: 48px;
  font-size: 0.95rem;
}
.kiosk__fullscreen-setup {
  width: 100%;
  min-height: 44px;
}
.kiosk__terminal {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 16px;
  margin-top: 16px;
  padding-top: 12px;
  border-top: 1px solid #1e3a52;
  color: #a9bccd;
  font-size: 0.72rem;
}
.kiosk__terminal strong {
  color: #f1f5f9;
}
.kiosk__board {
  box-sizing: border-box;
  width: 100%;
  height: calc(100vh - 88px);
  min-height: 0;
  max-width: none;
  margin: 0;
  padding: 16px clamp(16px, 2vw, 32px);
}
.kiosk__stage {
  display: grid;
  width: 100%;
  height: 100%;
  min-height: 0;
  grid-template-columns: minmax(0, 1fr) minmax(260px, 25vw);
  gap: clamp(16px, 1.5vw, 24px);
  align-items: stretch;
}
.kiosk__camera {
  box-sizing: border-box;
  width: 100%;
  height: 100%;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  background: #152223;
  border: 1px solid #1e3a52;
  border-radius: 16px;
  padding: clamp(12px, 1.25vw, 20px);
  display: flex;
  flex-direction: column;
  gap: 12px;
  justify-items: stretch;
}
.kiosk__camera :deep(.camera-frame) {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  min-height: 0;
  flex: 1 1 0;
  align-content: center;
  justify-items: center;
}
.kiosk__camera :deep(.camera-frame__viewport) {
  width: auto;
  height: 100%;
  flex: 0 1 auto;
  align-self: center;
  max-width: 100%;
  min-height: 0;
  border-radius: var(--radius-lg, 16px);
}
.kiosk__camera :deep(.camera-frame__media) {
  object-fit: contain;
  border-radius: inherit;
}
.kiosk__camera-badge {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  margin: 0;
  padding: 6px 12px;
  border-radius: 8px;
  background: rgb(16 27 28 / 0.8);
  font-size: 0.75rem;
  font-weight: 700;
  color: var(--st-gold);
  align-self: start;
}
.kiosk__camera-meta {
  margin: 0;
  color: #a9bccd;
  font-size: 0.8rem;
  text-align: center;
}
.kiosk__board-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 12px;
  justify-content: flex-start;
  margin-top: auto;
}
.kiosk__board-actions .kiosk__icon-button {
  width: 44px;
  min-width: 44px;
  min-height: 44px;
  padding: 0;
  border: 1px solid #35516b;
  border-radius: 10px;
  color: #c6d4d3;
}
.kiosk__board-actions .kiosk__icon-button:hover {
  border-color: #8bd4c6;
  background: rgb(139 212 198 / 10%);
}
.kiosk__board-actions .st-material-icon {
  font-size: 1.25rem;
}
.kiosk__result {
  display: grid;
  gap: 12px;
  min-width: 0;
  min-height: 0;
  height: 100%;
  align-content: start;
  overflow-y: auto;
}
.kiosk__result-card {
  background: var(--st-primary-container);
  border: 1px solid #1e3a52;
  border-radius: 16px;
  padding: 24px;
  text-align: center;
  display: grid;
  gap: 8px;
  justify-items: center;
}
.kiosk__result-card .kiosk__eyebrow {
  color: var(--st-gold);
}
.kiosk__session-context {
  margin: 0;
  color: #c6d4d3;
  font-size: 0.84rem;
  line-height: 1.45;
  overflow-wrap: anywhere;
}
.kiosk__session-state {
  margin: 0;
  color: #a9bccd;
  font-size: 0.76rem;
}
.kiosk__session-stats {
  width: 100%;
  box-sizing: border-box;
  margin: 4px 0;
  padding: 10px 12px;
  border: 1px solid #1e3a52;
  border-radius: 8px;
  background: #0b2036;
  color: #f1f5f9;
  font-size: 0.78rem;
  line-height: 1.45;
  font-weight: 600;
}
.kiosk__date {
  margin: 0;
  color: #a9bccd;
  font-size: 0.8rem;
}
.kiosk__avatar {
  width: 80px;
  height: 80px;
  border-radius: 999px;
  margin: 8px 0 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 1.5rem;
  font-weight: 800;
  background: #0f2a28;
  border: 2px solid var(--st-gold);
  color: #f1f5f9;
}
.kiosk__name {
  margin: 0;
  font-size: 1.4rem;
  font-weight: 800;
}
.kiosk__facts {
  display: grid;
  gap: 8px;
  margin: 8px 0 0;
  width: 100%;
}
.kiosk__facts > div {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  background: #0b2036;
  border: 1px solid #1e3a52;
  border-radius: 8px;
  padding: 8px 12px;
}
.kiosk__facts dt {
  color: #a9bccd;
  font-size: 0.72rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.06em;
}
.kiosk__facts dd {
  margin: 0;
  font-weight: 700;
}
.kiosk__countdown {
  color: #fbbf24;
  font-size: 0.8rem;
  margin: 4px 0 0;
}
.kiosk__result-card--waiting h2 {
  margin: 4px 0;
}
.kiosk__guide {
  background: var(--st-primary-container);
  border: 1px solid #1e3a52;
  border-radius: 12px;
  padding: 12px 16px;
  color: #c6d4d3;
}
.kiosk__guide summary {
  cursor: pointer;
  font-weight: 700;
  font-size: 0.85rem;
}
.kiosk__guide ul {
  margin: 8px 0 0;
  padding-left: 18px;
  display: grid;
  gap: 4px;
  font-size: 0.8rem;
}
.kiosk :deep(.st-empty__title) {
  color: #f1f5f9;
}
.kiosk :deep(.st-empty__desc) {
  color: #c6d4d3;
}
.kiosk :deep(.st-empty__icon) {
  color: var(--st-gold);
}
.kiosk .st-btn--text {
  color: #8bd4c6;
}
.kiosk .st-btn--secondary {
  background: #e6f7f6;
  border-color: #e6f7f6;
  color: #0f2a28;
}
.display-view.kiosk:fullscreen,
.display-view.kiosk:-webkit-full-screen {
  position: fixed;
  z-index: 2147483000;
  inset: 0;
  box-sizing: border-box;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  width: 100vw;
  height: 100vh;
  height: 100dvh;
  min-width: 100vw;
  min-height: 100dvh;
  max-width: none;
  margin: 0;
  overflow: hidden;
  padding: 0;
}
.display-view.kiosk:fullscreen .kiosk__top,
.display-view.kiosk:-webkit-full-screen .kiosk__top {
  box-sizing: border-box;
  width: 100%;
  min-height: 72px;
  padding: 8px clamp(16px, 2vw, 32px);
  flex-wrap: nowrap;
}
.display-view.kiosk:fullscreen .kiosk__board,
.display-view.kiosk:-webkit-full-screen .kiosk__board {
  height: 100%;
  margin: 0;
  padding: 12px clamp(16px, 2vw, 32px);
}
.display-view.kiosk:fullscreen .kiosk__stage,
.display-view.kiosk:-webkit-full-screen .kiosk__stage {
  height: 100%;
  min-height: 0;
}
.display-view.kiosk:fullscreen .kiosk__result,
.display-view.kiosk:-webkit-full-screen .kiosk__result {
  align-content: center;
}
@media (max-width: 850px) {
  .kiosk__activate-wrap,
  .kiosk__stage {
    grid-template-columns: minmax(0, 1fr);
  }
  .kiosk__board {
    height: auto;
    min-height: calc(100vh - 160px);
    padding: 16px;
  }
  .kiosk__stage {
    height: auto;
  }
  .kiosk__camera {
    height: auto;
    min-height: 0;
  }
  .kiosk__camera :deep(.camera-frame) {
    flex: 0 0 auto;
    height: auto;
  }
  .kiosk__camera :deep(.camera-frame__viewport) {
    width: 100%;
    height: auto;
  }
  .kiosk__result {
    height: auto;
    overflow: visible;
  }
  .display-view.kiosk:fullscreen,
  .display-view.kiosk:-webkit-full-screen {
    height: 100dvh;
    overflow: auto;
  }
  .display-view.kiosk:fullscreen .kiosk__top,
  .display-view.kiosk:-webkit-full-screen .kiosk__top {
    flex-wrap: wrap;
  }
  .display-view.kiosk:fullscreen .kiosk__board,
  .display-view.kiosk:-webkit-full-screen .kiosk__board {
    height: auto;
    min-height: calc(100dvh - 160px);
  }
  .kiosk__top {
    padding: 12px 16px;
  }
  .kiosk__clock {
    border-left: 0;
    padding-left: 0;
    text-align: left;
  }
  .kiosk__board,
  .kiosk__activate-wrap {
    padding: 0 16px;
  }
}
</style>
