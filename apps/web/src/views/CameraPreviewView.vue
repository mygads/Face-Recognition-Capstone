<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { fetchWithPreviewTimeout } from '../utils/previewFetch'
import { deviceHealthLabel } from '../utils/attendanceStatus'
import { useAuthStore } from '../stores/auth'
import { listDevices, type Device } from '../api/client'
import CameraFrame from '../components/CameraFrame.vue'
import { useFaceLandmarks } from '../composables/useFaceLandmarks'
import { UiBadge, UiButton, UiCard, UiPageHeader, UiSelect } from '../components/ui'
import { associateFaceRoles } from '../utils/faceLandmarks'

type PreviewStatus = {
  device_id?: string | null
  camera_open: boolean
  session_active: boolean
  recognition_state: string
  recognition_reason_code?: string | null
  display_name: string | null
  diagnostic_candidate?: DiagnosticCandidate | null
  updated_at: number | null
  camera_observation?: CameraObservation
  camera_metrics?: CameraRuntimeMetrics
  attendance_result?: AttendanceResult | null
}

type CameraRuntimeMetrics = {
  frame_width: number | null
  frame_height: number | null
  capture_fps: number | null
  requested_fps: number | null
  driver_fps: number | null
  quality_state: string
  quality_source: 'face_check' | 'frame_filter' | null
  quality_checked_at: string | null
  measured_at: string | null
}

type CameraFaceObservation = {
  x: number
  y: number
  width: number
  height: number
  landmarks?: number[][] | null
  role?: 'primary' | 'background' | 'ambiguous' | null
  is_primary?: boolean
  detection_confidence?: number
  acceptable: boolean
  quality_score?: number
  reason_codes: string[]
  face_pixels?: number
  sharpness?: number
  brightness?: number
  min_face_pixels?: number
  min_sharpness?: number
  min_brightness?: number
  max_brightness?: number
  [key: string]: unknown
}

type CameraObservation = {
  state: 'pending' | 'ready' | 'adjust' | 'no_face' | 'multiple_faces' | 'unavailable'
  message: string
  frame_width: number
  frame_height: number
  face_count: number
  faces: CameraFaceObservation[]
}

type AttendanceResult = {
  decision: 'pending' | 'recorded' | 'already_recorded' | 'not_recorded' | 'delivery_failed'
  attendance_status: 'present' | 'late' | null
  display_name?: string | null
  class_name?: string | null
  updated_at: number
}

type DiagnosticCandidate = {
  display_name: string
  class_name: string
  similarity: number
  updated_at: number
}

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const pageRoot = ref<HTMLElement | null>(null)
const previewToken = ref<string | null>(null)
const devices = ref<Device[]>([])
const selectedDeviceId = ref('')
const deviceLoadError = ref<string | null>(null)
const selectedDevice = computed(
  () => devices.value.find((device) => device.device_id === selectedDeviceId.value) ?? null,
)

function syncSelectionToUrl(): void {
  void router.replace({
    query: {
      ...route.query,
      lab: selectedDevice.value?.laboratory_id || undefined,
      device: selectedDeviceId.value || undefined,
    },
  })
}

async function loadDevices(): Promise<void> {
  try {
    const devicePage = await listDevices({ limit: 100, offset: 0, is_active: true })
    devices.value = devicePage.items
    const queryDevice = typeof route.query.device === 'string' ? route.query.device : ''
    if (queryDevice && devices.value.some((d) => d.device_id === queryDevice)) {
      selectedDeviceId.value = queryDevice
    } else {
      selectedDeviceId.value = devices.value[0]?.device_id ?? ''
    }
    syncSelectionToUrl()
  } catch (err) {
    deviceLoadError.value =
      err instanceof Error ? err.message : 'Daftar perangkat AI_EDGE tidak dapat dimuat.'
  }
}

function onDeviceChange(event: Event): void {
  const el = event.target
  if (el instanceof HTMLSelectElement) {
    selectedDeviceId.value = el.value
    resetPreviewFeed()
    void refreshStatus().catch((error) => {
      errorMessage.value = error instanceof Error ? error.message : 'Status kamera tidak tersedia.'
    })
    syncSelectionToUrl()
  }
}
const frameUrl = ref<string | null>(null)
const previewStatus = ref<PreviewStatus | null>(null)
const cameraObservation = computed(() => previewStatus.value?.camera_observation ?? null)
const selectedDeviceMatchesAgent = computed(() => {
  const agentDeviceId = previewStatus.value?.device_id
  return Boolean(
    selectedDeviceId.value &&
    agentDeviceId &&
    agentDeviceId.toLowerCase() === selectedDeviceId.value.toLowerCase(),
  )
})
const devicePairingMismatch = computed(() => {
  const agentDeviceId = previewStatus.value?.device_id
  return Boolean(
    selectedDeviceId.value &&
    agentDeviceId &&
    agentDeviceId.toLowerCase() !== selectedDeviceId.value.toLowerCase(),
  )
})
const devicePairingUnverified = computed(() =>
  Boolean(selectedDeviceId.value && previewStatus.value && !previewStatus.value.device_id),
)
const localAgentDeviceName = computed(() => {
  const agentDeviceId = previewStatus.value?.device_id?.toLowerCase()
  return devices.value.find((device) => device.device_id.toLowerCase() === agentDeviceId)?.name
})
const previewPlaceholderMessage = computed(() => {
  if (!selectedDeviceId.value) return 'Daftarkan dan siapkan perangkat AI_EDGE terlebih dahulu.'
  if (previewStatus.value?.recognition_state === 'camera_disabled') {
    return 'Kamera sedang dijeda. Lanjutkan kamera dari halaman Perangkat untuk mengaktifkan preview.'
  }
  if (devicePairingMismatch.value) {
    return localAgentDeviceName.value
      ? `Agent pada komputer ini milik ${localAgentDeviceName.value}. Buka preview dari komputer perangkat yang dipilih.`
      : 'Agent pada komputer ini terpasang untuk perangkat lain. Buka preview dari komputer perangkat yang dipilih.'
  }
  if (devicePairingUnverified.value) {
    return 'Agent belum melaporkan identitas perangkat. Periksa provisioning agent sebelum menampilkan video.'
  }
  return 'Pastikan agent AI_EDGE berjalan pada komputer kamera yang dipilih.'
})
const faceOverlayLabel = computed(() => {
  return 'Wajah yang dipindai'
})

const diagnosticCandidate = computed(() => {
  const candidate = previewStatus.value?.diagnostic_candidate
  if (!candidate || Date.now() / 1000 - candidate.updated_at > 3) return null
  return candidate
})
const unmatchedObservedFace = computed(
  () =>
    cameraRunning.value &&
    previewStatus.value?.session_active === true &&
    ((cameraObservation.value?.face_count ?? 0) > 0 || faceMesh.faces.value.length > 0) &&
    !diagnosticCandidate.value,
)
const sessionRequired = computed(
  () =>
    Boolean(previewStatus.value) &&
    previewStatus.value?.session_active === false &&
    previewStatus.value?.recognition_state !== 'camera_disabled',
)
const errorMessage = ref<string | null>(null)
const isStarting = ref(true)
const isFullscreen = ref(false)
// Transport utama: satu koneksi MJPEG /v1/stream (tanpa handshake per-frame).
// polling /v1/frame.jpg hanya sebagai fallback (agent lama / ?transport=poll).
const routeTransport = typeof route.query.transport === 'string' ? route.query.transport : ''
const transport = ref<'stream' | 'poll'>(routeTransport === 'poll' ? 'poll' : 'stream')
const streamAlive = ref(false)
const streamRetry = ref(0)
let reconnectTimer: ReturnType<typeof setTimeout> | undefined
let feedGeneration = 0
const streamUrl = computed(() => {
  if (!previewBaseUrl.value || !previewToken.value) return null
  return `${previewBaseUrl.value}/v1/stream?token=${encodeURIComponent(previewToken.value)}&retry=${streamRetry.value}`
})
const hasFeed = computed(
  () =>
    selectedDeviceMatchesAgent.value &&
    ((transport.value === 'poll' && frameUrl.value !== null) ||
      (transport.value === 'stream' && streamUrl.value !== null)),
)
const cameraRunning = computed(() => hasFeed.value && previewStatus.value?.camera_open === true)
const previewImage = ref<HTMLImageElement | null>(null)
const faceMesh = useFaceLandmarks(previewImage, cameraRunning)
// The agent's sparse recognition landmarks are not a visual face mesh.
// Draw only dense local FaceLandmarker results, as on the kiosk.
const activeCameraFaces = computed(() =>
  associateFaceRoles(faceMesh.faces.value, cameraObservation.value?.faces ?? []),
)
const previewFrameWidth = computed(
  () => faceMesh.frameSize.value.width || cameraObservation.value?.frame_width || undefined,
)
const previewFrameHeight = computed(
  () => faceMesh.frameSize.value.height || cameraObservation.value?.frame_height || undefined,
)
const placeholderTitle = computed(() => {
  if (previewStatus.value?.recognition_state === 'camera_disabled') return 'Kamera dijeda'
  if (devicePairingMismatch.value) return 'Perangkat kamera berbeda'
  if (devicePairingUnverified.value) return 'Identitas kamera belum terverifikasi'
  if (!selectedDeviceId.value) return 'Belum ada perangkat kamera'
  if (errorMessage.value) return 'Preview belum tersedia'
  if (transport.value === 'stream' && !streamAlive.value) return 'Menghubungkan ke stream…'
  return isStarting.value ? 'Menghubungkan ke agent…' : 'Preview belum tersedia'
})
const lastFrameAt = ref<number | null>(null)
const FRAME_STALE_AFTER_MS = 3000
// Gangguan sesaat (satu-dua 503) tidak langsung menghapus frame bagus terakhir;
// frame baru dibuang setelah 3 respons tak-tersedia beruntun (~200 ms).
const CONSECUTIVE_UNAVAILABLE_BEFORE_CLEAR = 3
let consecutiveUnavailable = 0

function resetPreviewFeed(): void {
  // Ganti sumber harus membuang gambar + status lama agar tidak disalahartikan
  // sebagai feed kamera yang baru; stream/polling yang berjalan mengisi ulang.
  feedGeneration += 1
  if (reconnectTimer) clearTimeout(reconnectTimer)
  if (frameUrl.value) {
    URL.revokeObjectURL(frameUrl.value)
    frameUrl.value = null
  }
  transport.value = routeTransport === 'poll' ? 'poll' : 'stream'
  streamAlive.value = false
  previewStatus.value = null
  lastFrameAt.value = null
  consecutiveUnavailable = 0
  errorMessage.value = null
  isStarting.value = true
}

function onStreamLoad(): void {
  if (stopped) return
  streamAlive.value = true
  errorMessage.value = null
  isStarting.value = false
}

function onStreamError(): void {
  if (stopped) return
  streamAlive.value = false
  if (transport.value === 'stream') {
    // Fallback keeps the picture visible while a one-connection MJPEG stream
    // is retried; a temporary stream error must not strand preview in polling.
    transport.value = 'poll'
    void pollFrame()
  }
  scheduleStreamReconnect()
}

function scheduleStreamReconnect(): void {
  if (reconnectTimer) clearTimeout(reconnectTimer)
  const generation = feedGeneration
  reconnectTimer = setTimeout(() => {
    if (stopped || generation !== feedGeneration) return
    void reconnectStream()
  }, 3000)
}

async function reconnectStream(): Promise<void> {
  if (stopped) return
  const generation = feedGeneration
  try {
    previewToken.value = await openPreviewSession()
    if (stopped || generation !== feedGeneration) return
    feedGeneration += 1
    if (frameTimer) clearTimeout(frameTimer)
    frameTimer = undefined
    if (frameUrl.value) {
      URL.revokeObjectURL(frameUrl.value)
      frameUrl.value = null
    }
    streamRetry.value += 1
    transport.value = 'stream'
    errorMessage.value = null
  } catch (error) {
    if (!stopped && generation === feedGeneration) {
      errorMessage.value = error instanceof Error ? error.message : 'Preview kamera tidak tersedia.'
      scheduleStreamReconnect()
    }
  }
}

const frameAgeMs = computed(() => {
  // Bergantung pada previewStatus agar dievaluasi ulang tiap status poll 500 ms.
  void previewStatus.value
  if (!frameUrl.value || lastFrameAt.value === null) return null
  return Date.now() - lastFrameAt.value
})
const frameStale = computed(() => (frameAgeMs.value ?? 0) > FRAME_STALE_AFTER_MS)
const frameAgeLabel = computed(() => {
  if (frameAgeMs.value === null) return ''
  return `${Math.max(0, Math.round(frameAgeMs.value / 1000))} dtk`
})
let frameTimer: ReturnType<typeof setTimeout> | undefined
let statusTimer: ReturnType<typeof setTimeout> | undefined
let stopped = false

const recentAttendanceResult = computed(() => {
  const result = previewStatus.value?.attendance_result
  if (!result) return null
  if (result.decision === 'recorded' && Date.now() / 1000 - result.updated_at > 15) {
    return null
  }
  return result
})
const identityMatched = computed(
  () =>
    previewStatus.value?.recognition_state === 'accepted' ||
    recentAttendanceResult.value?.decision === 'recorded' ||
    recentAttendanceResult.value?.decision === 'already_recorded',
)
const identityPanelClass = computed(() => {
  const decision = recentAttendanceResult.value?.decision
  if (decision === 'delivery_failed' || decision === 'not_recorded') return 'is-rejected'
  if (decision === 'recorded' || decision === 'already_recorded') return 'is-recorded'
  if (identityMatched.value) return 'is-matched'
  if (decision === 'pending') return 'is-pending'
  return ''
})

const cameraObservationLabel = computed(() => {
  switch (cameraObservation.value?.state) {
    case 'ready':
      return 'Wajah terlihat jelas'
    case 'adjust':
      return 'Atur posisi atau kualitas'
    case 'no_face':
      return 'Arahkan wajah ke kamera'
    case 'multiple_faces':
      return 'Satu orang per bingkai'
    case 'unavailable':
      return 'Kamera belum siap diperiksa'
    default:
      return 'Menyiapkan kamera'
  }
})
const cameraFrameMessage = computed(() => {
  if (previewStatus.value?.recognition_state === 'camera_disabled') {
    return 'Kamera sedang dijeda. Lanjutkan dari halaman Perangkat untuk menampilkan preview.'
  }
  return cameraObservation.value?.message ?? 'Menghubungkan ke kamera…'
})

const identityTitle = computed(() => {
  if (recentAttendanceResult.value?.decision === 'recorded') {
    return recentAttendanceResult.value.display_name ?? 'Presensi tercatat'
  }
  if (recentAttendanceResult.value?.decision === 'already_recorded') {
    return recentAttendanceResult.value.display_name ?? 'Presensi sudah tercatat'
  }
  if (recentAttendanceResult.value?.decision === 'not_recorded') {
    return previewStatus.value?.display_name ?? 'Presensi belum tercatat'
  }
  if (recentAttendanceResult.value?.decision === 'delivery_failed') {
    return recentAttendanceResult.value.display_name ?? 'Presensi belum tercatat'
  }
  if (previewStatus.value?.recognition_state === 'accepted') {
    return previewStatus.value.display_name ?? 'Identitas cocok'
  }
  if (sessionRequired.value) {
    return 'Sesi belum dibuka'
  }
  if (previewStatus.value?.recognition_state === 'camera_disabled') return 'Kamera dijeda'
  if (previewStatus.value?.recognition_reason_code === 'single_identity_gallery') {
    return 'Butuh identitas pembanding'
  }
  if (diagnosticCandidate.value) return diagnosticCandidate.value.display_name
  if (cameraObservation.value?.state === 'no_face') return 'Arahkan wajah ke kamera'
  if (cameraObservation.value?.state === 'multiple_faces') return 'Satu orang per bingkai'
  if (!isFullscreen.value) {
    if (previewStatus.value?.recognition_state === 'waiting_for_calibration') {
      return 'Pengenalan belum siap'
    }
    return 'Menunggu wajah'
  }
  if (previewStatus.value?.recognition_state === 'waiting_for_calibration') {
    return 'Pengenalan belum siap'
  }
  if (
    recentAttendanceResult.value?.decision === 'pending' ||
    previewStatus.value?.recognition_state === 'accepted'
  )
    return 'Memeriksa presensi'
  if (cameraObservation.value?.state === 'ready') return 'Memeriksa wajah'
  return 'Posisikan wajah di kamera'
})

const identityDisplayMessage = computed(() => {
  if (recentAttendanceResult.value?.decision === 'recorded') {
    const className = recentAttendanceResult.value.class_name
    const prefix = className ? `${className} · ` : ''
    return recentAttendanceResult.value.attendance_status === 'late'
      ? `${prefix}Presensi sudah tercatat sebagai terlambat.`
      : `${prefix}Presensi sudah tercatat sebagai hadir.`
  }
  if (recentAttendanceResult.value?.decision === 'already_recorded') {
    return 'Presensi siswa ini sudah tercatat pada sesi aktif. Tidak perlu memindai ulang.'
  }
  if (recentAttendanceResult.value?.decision === 'not_recorded') {
    return 'Identitas cocok, tetapi sesi atau aturan server belum mengizinkan presensi. Minta petugas memeriksa.'
  }
  if (recentAttendanceResult.value?.decision === 'delivery_failed') {
    return 'Identitas cocok, tetapi server menolak data presensi. Minta petugas memeriksa status perangkat.'
  }
  if (sessionRequired.value) {
    return 'Buka sesi untuk kelas siswa. AI hanya memeriksa siswa yang ada di daftar sesi tersebut.'
  }
  if (diagnosticCandidate.value) {
    return 'Nama ini masih kandidat. Presensi belum tercatat sampai hasil dikonfirmasi server.'
  }
  if (!isFullscreen.value) {
    return recognitionMessage.value
  }
  if (!previewStatus.value?.session_active) return recognitionMessage.value
  if (previewStatus.value?.recognition_state === 'waiting_for_calibration') {
    return recognitionMessage.value
  }
  if (previewStatus.value?.recognition_reason_code === 'single_identity_gallery') {
    return recognitionMessage.value
  }
  if (
    recentAttendanceResult.value?.decision === 'pending' ||
    previewStatus.value?.recognition_state === 'accepted'
  ) {
    return 'Kecocokan sedang divalidasi server. Tunggu sebentar.'
  }
  return cameraObservation.value?.message ?? recognitionMessage.value
})

const previewHost = computed(() => {
  const hostname = window.location.hostname
  return hostname === 'localhost' || hostname === '127.0.0.1' ? hostname : null
})
const previewBaseUrl = computed(() =>
  previewHost.value ? `http://${previewHost.value}:8765` : null,
)

const recognitionMessage = computed(() => {
  if (!previewStatus.value) return 'Menghubungkan ke kamera pada komputer ini…'
  if (previewStatus.value.recognition_state === 'camera_disabled') {
    return 'Kamera sedang dijeda dari halaman Perangkat. Lanjutkan kamera jika ingin melihat preview.'
  }
  if (!previewStatus.value.camera_open)
    return 'Kamera belum terbuka. Periksa agent dan koneksi kamera.'
  if (!previewStatus.value.session_active)
    return 'Kamera aktif. Buka sesi presensi untuk mulai memeriksa identitas siswa.'
  switch (previewStatus.value.recognition_state) {
    case 'waiting_for_calibration':
      return 'Pengenalan belum siap. Minta admin memeriksa pengaturan AI.'
    case 'preview_only':
      return 'Pencocokan preview berjalan untuk kelas terjadwal di laboratorium ini. Hasilnya belum menjadi presensi.'
    case 'checking':
    case 'collecting':
      return 'Menyesuaikan wajah. Hadapkan wajah ke kamera dan tahan sebentar.'
    case 'accepted':
      return previewStatus.value.display_name
        ? 'Identitas cocok. Mengirim presensi untuk konfirmasi server.'
        : 'Identitas cocok, tetapi nama roster tidak tersedia.'
    case 'retry_frontal':
      if (previewStatus.value.recognition_reason_code === 'single_identity_gallery') {
        return 'Belum cukup pembanding untuk memastikan identitas. Gunakan sesi dengan lebih dari satu siswa terdaftar.'
      }
      return 'Belum cukup yakin. Minta siswa menghadap lurus ke kamera.'
    case 'rejected':
      return 'Belum cocok atau kualitas gambar belum cukup. Periksa posisi dan pencahayaan.'
    case 'camera_unavailable':
      return 'Kamera terputus. Agent akan mencoba menyambungkan kembali.'
    case 'stopped':
      return 'Agent kamera sedang berhenti.'
    default:
      return 'Kamera siap; menunggu frame berikutnya.'
  }
})

async function openPreviewSession(): Promise<string> {
  if (!previewBaseUrl.value) {
    throw new Error('Buka dashboard dari browser pada komputer AI_EDGE yang menjalankan kamera.')
  }
  const accessToken = auth.getValidAccessToken()
  if (!accessToken) throw new Error('Sesi login sudah berakhir. Masuk kembali lalu buka preview.')
  const response = await fetchWithPreviewTimeout(`${previewBaseUrl.value}/v1/session`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${accessToken}`,
    },
    cache: 'no-store',
  })
  if (!response.ok) {
    if (response.status === 403)
      throw new Error('Preview hanya tersedia untuk ADMIN atau LABORANT.')
    throw new Error('Agent preview tidak merespons. Pastikan AI_EDGE aktif di komputer ini.')
  }
  const result = (await response.json()) as { preview_token?: unknown }
  if (typeof result.preview_token !== 'string') {
    throw new Error('Agent mengirim respons preview yang tidak valid.')
  }
  return result.preview_token
}

async function authorizedFetch(
  path: string,
  init: Parameters<typeof fetch>[1] = {},
): Promise<Response> {
  if (!previewBaseUrl.value || !previewToken.value) throw new Error('Sesi preview belum aktif.')
  const headers = new Headers(init.headers)
  headers.set('X-Presensi-Preview-Token', previewToken.value)
  const response = await fetchWithPreviewTimeout(`${previewBaseUrl.value}${path}`, {
    ...init,
    headers,
    cache: 'no-store',
  })
  if (response.status === 401) {
    previewToken.value = await openPreviewSession()
    headers.set('X-Presensi-Preview-Token', previewToken.value)
    return fetchWithPreviewTimeout(`${previewBaseUrl.value}${path}`, {
      ...init,
      headers,
      cache: 'no-store',
    })
  }
  return response
}

async function refreshStatus(): Promise<void> {
  const response = await authorizedFetch('/v1/status')
  if (!response.ok) throw new Error('Status kamera belum tersedia.')
  previewStatus.value = (await response.json()) as PreviewStatus
  if (previewStatus.value.camera_open) errorMessage.value = null
}

async function toggleFullscreen(): Promise<void> {
  const preview = pageRoot.value
  if (!preview) return
  try {
    if (document.fullscreenElement) {
      await document.exitFullscreen()
    } else if (preview.requestFullscreen) {
      await preview.requestFullscreen()
    } else {
      errorMessage.value = 'Mode layar penuh tidak didukung browser ini.'
    }
  } catch {
    errorMessage.value = 'Mode layar penuh tidak dapat diaktifkan.'
  }
}

function syncFullscreenState(): void {
  isFullscreen.value = Boolean(document.fullscreenElement)
}

async function pollFrame(): Promise<void> {
  if (stopped) return
  const generation = feedGeneration
  const requestStartedAt = performance.now()
  try {
    const response = await authorizedFetch('/v1/frame.jpg')
    if (!response.ok) {
      if (response.status === 503) {
        consecutiveUnavailable += 1
        if (consecutiveUnavailable >= CONSECUTIVE_UNAVAILABLE_BEFORE_CLEAR && frameUrl.value) {
          URL.revokeObjectURL(frameUrl.value)
          frameUrl.value = null
        }
      }
      throw new Error('Frame kamera belum tersedia.')
    }
    consecutiveUnavailable = 0
    const nextUrl = URL.createObjectURL(await response.blob())
    if (stopped || generation !== feedGeneration) {
      URL.revokeObjectURL(nextUrl)
      return
    }
    const previousUrl = frameUrl.value
    frameUrl.value = nextUrl
    lastFrameAt.value = Date.now()
    if (previousUrl) URL.revokeObjectURL(previousUrl)
    errorMessage.value = null
    isStarting.value = false
  } catch (error) {
    if (!stopped && !frameUrl.value) {
      errorMessage.value = error instanceof Error ? error.message : 'Preview kamera tidak tersedia.'
    }
  } finally {
    const targetFrameIntervalMs = 1000 / 30
    const waitMs = Math.max(0, targetFrameIntervalMs - (performance.now() - requestStartedAt))
    if (!stopped && generation === feedGeneration) {
      frameTimer = setTimeout(() => void pollFrame(), waitMs)
    }
  }
}

async function pollStatus(): Promise<void> {
  if (stopped) return
  try {
    await refreshStatus()
  } catch (error) {
    if (!stopped) {
      errorMessage.value = error instanceof Error ? error.message : 'Status kamera tidak tersedia.'
    }
  } finally {
    if (!stopped) statusTimer = setTimeout(() => void pollStatus(), 500)
  }
}

onMounted(async () => {
  document.addEventListener('fullscreenchange', syncFullscreenState)
  void loadDevices()
  try {
    previewToken.value = await openPreviewSession()
    if (stopped) return
    if (transport.value === 'poll') void pollFrame()
    void pollStatus()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : 'Tidak dapat membuka preview.'
  } finally {
    isStarting.value = false
  }
})

onBeforeUnmount(() => {
  document.removeEventListener('fullscreenchange', syncFullscreenState)
  stopped = true
  if (frameTimer) clearTimeout(frameTimer)
  if (statusTimer) clearTimeout(statusTimer)
  if (reconnectTimer) clearTimeout(reconnectTimer)
  if (frameUrl.value) URL.revokeObjectURL(frameUrl.value)
  const token = previewToken.value
  if (previewBaseUrl.value && token) {
    void fetch(`${previewBaseUrl.value}/v1/session`, {
      method: 'DELETE',
      headers: { 'X-Presensi-Preview-Token': token },
      keepalive: true,
    }).catch(() => undefined)
  }
  previewToken.value = null
})
</script>

<template>
  <div
    ref="pageRoot"
    class="st-page camera-preview-view"
    aria-label="Preview kamera AI_EDGE"
    data-testid="camera-preview-page"
  >
    <UiPageHeader
      eyebrow="AI_EDGE · perangkat kamera"
      title="Preview Kamera Presensi"
      description="Periksa posisi wajah dan kesiapan kamera. Pengenalan dimulai setelah sesi presensi dibuka."
    >
      <template #actions>
        <UiBadge :tone="previewStatus?.camera_open ? 'present' : 'neutral'">
          {{
            previewStatus?.camera_open
              ? 'Kamera aktif'
              : isStarting
                ? 'Menghubungkan…'
                : 'Menunggu kamera'
          }}
        </UiBadge>
        <UiButton variant="secondary" type="button" @click="toggleFullscreen">
          {{ isFullscreen ? 'Keluar layar penuh' : 'Layar penuh' }}
        </UiButton>
      </template>
    </UiPageHeader>
    <UiCard
      v-if="!isFullscreen"
      title="Perangkat kamera"
      subtitle="Pilih kamera yang akan diperiksa."
    >
      <label v-if="devices.length > 1" class="st-field">
        <span>Pilih perangkat kamera</span>
        <UiSelect
          :model-value="selectedDeviceId"
          aria-label="Pilih perangkat kamera"
          data-testid="preview-device-select"
          @change="onDeviceChange"
        >
          <option v-for="device in devices" :key="device.device_id" :value="device.device_id">
            {{ device.name }} · {{ device.laboratory_name }} ·
            {{ deviceHealthLabel(device.health_status) }}
          </option>
        </UiSelect>
      </label>
      <p v-else-if="selectedDevice" class="st-table__muted" data-testid="preview-single-device">
        <strong>{{ selectedDevice.name }}</strong> · {{ selectedDevice.laboratory_name }} ·
        {{ deviceHealthLabel(selectedDevice.health_status) }}
      </p>
      <p v-else class="st-alert st-alert--error" role="status">
        Belum ada perangkat aktif.
        <RouterLink to="/app/devices">Daftarkan perangkat AI_EDGE</RouterLink>
        terlebih dahulu.
      </p>
      <p v-if="deviceLoadError" class="st-alert st-alert--error" role="alert">
        {{ deviceLoadError }}
      </p>
    </UiCard>
    <p v-if="errorMessage" class="st-alert st-alert--error" role="alert">{{ errorMessage }}</p>

    <div class="camera-preview-view__layout">
      <figure class="camera-preview-view__frame">
        <CameraFrame
          :faces="cameraRunning ? activeCameraFaces : []"
          :image-width="previewFrameWidth"
          :image-height="previewFrameHeight"
          :label="identityMatched ? 'Cocok galeri' : faceOverlayLabel"
          fit="contain"
        >
          <img
            v-if="cameraRunning && transport === 'stream' && streamUrl"
            ref="previewImage"
            :src="streamUrl"
            crossorigin="anonymous"
            class="camera-frame__media"
            alt="Preview langsung kamera presensi"
            data-testid="preview-stream-img"
            @load="onStreamLoad"
            @error="onStreamError"
          />
          <img
            v-else-if="cameraRunning && transport === 'poll' && frameUrl"
            ref="previewImage"
            :src="frameUrl"
            class="camera-frame__media"
            alt="Preview langsung kamera presensi"
          />
          <div
            v-if="cameraRunning"
            class="camera-preview-view__guidance"
            :class="`is-${cameraObservation?.state ?? 'pending'}`"
            role="status"
          >
            <strong>{{ cameraObservationLabel }}</strong>
            <span>{{ cameraFrameMessage }}</span>
          </div>
          <div
            v-else
            class="camera-frame__placeholder camera-preview-view__placeholder"
            role="status"
            data-testid="preview-camera-placeholder"
          >
            <strong>{{ placeholderTitle }}</strong>
            <p>{{ previewPlaceholderMessage }}</p>
          </div>
        </CameraFrame>
        <p
          v-if="transport === 'poll' && frameStale"
          class="st-table__muted"
          role="status"
          data-testid="preview-stale-warning"
        >
          <UiBadge tone="late">Frame beku</UiBadge>
          <span>Frame terakhir {{ frameAgeLabel }} lalu - koneksi mungkin beku.</span>
        </p>
        <figcaption>Video hanya ditampilkan sementara dan tidak disimpan.</figcaption>
      </figure>

      <aside
        class="camera-preview-view__identity"
        :class="identityPanelClass"
        aria-label="Status pengenalan siswa"
      >
        <p class="master-data__eyebrow">Status presensi</p>
        <h3>{{ identityTitle }}</h3>
        <span v-if="identityMatched" class="camera-preview-view__match-badge" role="status">
          <span aria-hidden="true">✓</span>
          {{
            recentAttendanceResult?.decision === 'recorded' ||
            recentAttendanceResult?.decision === 'already_recorded'
              ? 'Presensi tercatat'
              : recentAttendanceResult?.decision === 'delivery_failed' ||
                  recentAttendanceResult?.decision === 'not_recorded'
                ? 'Identitas cocok · presensi belum tercatat'
                : 'Identitas cocok · menunggu konfirmasi server'
          }}
        </span>
        <p v-if="!sessionRequired">{{ identityDisplayMessage }}</p>
        <div
          v-if="sessionRequired"
          class="camera-preview-view__next-step"
          role="status"
          data-testid="preview-session-required"
        >
          <span>Langkah selanjutnya</span>
          <strong>Buka sesi untuk memeriksa nama</strong>
          <p>
            Acuan wajah yang sudah terdaftar dipakai saat siswa ada di daftar sesi aktif. Pilih
            jadwal dan kelas siswa yang benar.
          </p>
          <RouterLink
            v-if="!isFullscreen"
            class="button button--primary camera-preview-view__settings-link"
            to="/app/sessions"
          >
            Buka sesi presensi
          </RouterLink>
        </div>
        <div
          v-if="diagnosticCandidate && !sessionRequired"
          class="camera-preview-view__candidate"
          role="status"
          aria-live="polite"
        >
          <span>Nama kandidat · menunggu konfirmasi</span>
          <strong>{{ diagnosticCandidate.display_name }}</strong>
          <b>{{ diagnosticCandidate.class_name || 'Kelas tidak tersedia' }}</b>
          <small>Presensi baru tercatat setelah hasil dikonfirmasi server.</small>
        </div>
        <div
          v-else-if="unmatchedObservedFace && !identityMatched"
          class="camera-preview-view__candidate-empty"
          role="status"
          data-testid="preview-unmatched-face"
        >
          <strong>Belum menemukan kecocokan</strong>
          <small v-if="previewStatus?.recognition_state === 'waiting_for_calibration'">
            Minta admin menyiapkan pengenalan AI sebelum mencoba lagi.
          </small>
          <small
            v-else-if="
              previewStatus?.recognition_state === 'rejected' ||
              previewStatus?.recognition_state === 'retry_frontal'
            "
          >
            Pastikan wajah terlihat jelas dan siswa tercantum di kelas pada sesi ini.
          </small>
          <small v-else>{{ recognitionMessage }}</small>
        </div>
        <div
          v-else-if="previewStatus?.recognition_state === 'preview_only' && !sessionRequired"
          class="camera-preview-view__candidate-empty"
          role="status"
        >
          <strong>Mencari kecocokan</strong>
          <small v-if="cameraObservation?.state !== 'ready'">
            {{ cameraObservation?.message ?? 'Menunggu satu wajah dengan kualitas yang cukup.' }}
          </small>
          <small v-else> Hadapkan wajah ke kamera dan tahan sebentar. </small>
        </div>
        <RouterLink
          v-if="auth.account?.roles.includes('ADMIN') && !isFullscreen"
          class="button button--secondary camera-preview-view__settings-link"
          to="/app/ai-setup"
        >
          Atur kualitas &amp; pengenalan
        </RouterLink>
        <dl v-if="!sessionRequired">
          <div>
            <dt>Sesi praktikum</dt>
            <dd>{{ previewStatus?.session_active ? 'Aktif' : 'Belum aktif' }}</dd>
          </div>
          <div>
            <dt>Kondisi kamera</dt>
            <dd>{{ previewStatus?.camera_open ? 'Terhubung' : 'Tidak terhubung' }}</dd>
          </div>
        </dl>
        <p v-if="previewStatus?.session_active" class="camera-preview-view__privacy">
          Presensi tercatat setelah server mengonfirmasi hasil.
        </p>
      </aside>
    </div>
  </div>
</template>
