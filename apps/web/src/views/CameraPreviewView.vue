<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { fetchWithPreviewTimeout } from '../utils/previewFetch'
import { deviceHealthLabel } from '../utils/attendanceStatus'
import { useAuthStore } from '../stores/auth'
import { listDevices, listLaboratories, type Device, type Laboratory } from '../api/client'
import { UiBadge, UiButton, UiCard, UiPageHeader, UiSelect } from '../components/ui'

type PreviewStatus = {
  camera_open: boolean
  session_active: boolean
  recognition_state: string
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
const previewToken = ref<string | null>(null)
const openedRemotely = ref(false)
const devices = ref<Device[]>([])
const laboratories = ref<Laboratory[]>([])
const selectedDeviceId = ref('')
const selectedLabId = ref('')
const deviceLoadError = ref<string | null>(null)

function syncSelectionToUrl(): void {
  void router.replace({
    query: {
      ...route.query,
      lab: selectedLabId.value || undefined,
      device: selectedDeviceId.value || undefined,
    },
  })
}

async function loadDevicesAndLabs(): Promise<void> {
  try {
    const [devicePage, labPage] = await Promise.all([
      listDevices({ limit: 100, offset: 0 }),
      listLaboratories({ limit: 100, offset: 0 }),
    ])
    devices.value = devicePage.items
    laboratories.value = labPage.items
    const queryLab = typeof route.query.lab === 'string' ? route.query.lab : ''
    const queryDevice = typeof route.query.device === 'string' ? route.query.device : ''
    if (queryDevice && devices.value.some((d) => d.device_id === queryDevice)) {
      selectedDeviceId.value = queryDevice
      const dev = devices.value.find((d) => d.device_id === queryDevice)
      selectedLabId.value = queryLab || dev?.laboratory_id || ''
    } else {
      if (!selectedDeviceId.value && devices.value.length)
        selectedDeviceId.value = devices.value[0].device_id
      const firstLab = devices.value[0]?.laboratory_id ?? laboratories.value[0]?.id
      if (!selectedLabId.value && firstLab) selectedLabId.value = firstLab
      syncSelectionToUrl()
    }
  } catch (err) {
    deviceLoadError.value =
      err instanceof Error ? err.message : 'Daftar perangkat tidak dapat dimuat.'
  }
}

function onDeviceChange(event: Event): void {
  const el = event.target
  if (el instanceof HTMLSelectElement) {
    selectedDeviceId.value = el.value
    const dev = devices.value.find((d) => d.device_id === el.value)
    if (dev) selectedLabId.value = dev.laboratory_id
    openedRemotely.value = false
    syncSelectionToUrl()
  }
}

function onLabChange(event: Event): void {
  const el = event.target
  if (el instanceof HTMLSelectElement) {
    selectedLabId.value = el.value
    openedRemotely.value = false
    syncSelectionToUrl()
  }
}

function openOnLabDevice(): void {
  // Feed kamera hanya bisa dibuka dari PC lab yang dipasangi agent (loopback companion);
  // tombol ini menandai admin sudah membuka halaman ini di perangkat lab tersebut.
  openedRemotely.value = true
}
const frameUrl = ref<string | null>(null)
const previewStatus = ref<PreviewStatus | null>(null)
const cameraObservation = computed(() => previewStatus.value?.camera_observation ?? null)
const cameraMetrics = computed(() => previewStatus.value?.camera_metrics ?? null)
const previewFps = ref<number | null>(null)
const previewFrameTimes: number[] = []
let lastPreviewFpsUpdate = 0
const cameraFaceMetrics = computed(() => {
  const face = cameraObservation.value?.faces[0]
  if (!face) return []
  const metrics: string[] = []
  if (face.quality_score !== undefined) {
    metrics.push(`Kualitas frame ${(face.quality_score * 100).toFixed(0)}% · bukan akurasi`)
  }
  if (face.detection_confidence !== undefined) {
    metrics.push(
      `Confidence deteksi ${Math.round(face.detection_confidence * 100)}% · bukan akurasi identitas`,
    )
  }
  if (face.face_pixels !== undefined) {
    const minimum = face.min_face_pixels
    metrics.push(
      `Ukuran wajah ${Math.round(face.face_pixels)} px${minimum === undefined ? '' : ` · min ${Math.round(minimum)} px`}`,
    )
  }
  if (face.sharpness !== undefined) {
    const minimum = face.min_sharpness
    metrics.push(
      `Ketajaman ${face.sharpness.toFixed(1)}${minimum === undefined ? '' : ` · min ${minimum.toFixed(1)}`}`,
    )
  }
  if (face.brightness !== undefined) {
    const range =
      face.min_brightness === undefined || face.max_brightness === undefined
        ? ''
        : ` · target ${Math.round(face.min_brightness)}-${Math.round(face.max_brightness)}`
    metrics.push(`Cahaya ${face.brightness.toFixed(1)}${range}`)
  }
  return metrics
})
const detectionLabel = (face: CameraFaceObservation) => {
  const observation = cameraObservation.value
  if (!observation) return null
  const fontSize = Math.max(16, Math.min(30, observation.frame_width / 55))
  const width = fontSize * 7.8
  const height = fontSize * 1.55
  const x = Math.max(0, Math.min(face.x * observation.frame_width, observation.frame_width - width))
  const y = Math.max(0, face.y * observation.frame_height - height)
  return {
    x,
    y,
    width,
    height,
    fontSize,
    textX: x + fontSize * 0.45,
    textY: y + height * 0.68,
    text: `DETEKSI ${Math.round((face.detection_confidence ?? 0) * 100)}%`,
  }
}
const diagnosticCandidate = computed(() => {
  const candidate = previewStatus.value?.diagnostic_candidate
  if (!candidate || Date.now() / 1000 - candidate.updated_at > 3) return null
  return candidate
})
const diagnosticSimilarityPercent = computed(() => {
  const similarity = diagnosticCandidate.value?.similarity
  return similarity === undefined ? null : `${(similarity * 100).toFixed(1)}%`
})
const errorMessage = ref<string | null>(null)
const isStarting = ref(true)
const isFullscreen = ref(false)
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
      return 'Frame siap diperiksa'
    case 'adjust':
      return 'Atur posisi atau kualitas'
    case 'no_face':
      return 'Mencari wajah'
    case 'multiple_faces':
      return 'Pastikan satu orang di frame'
    case 'unavailable':
      return 'Pemeriksaan kamera tidak tersedia'
    default:
      return 'Menyiapkan pemeriksaan kamera'
  }
})

const cameraQualityLabel = computed(() => {
  const state = cameraObservation.value?.state ?? cameraMetrics.value?.quality_state
  switch (state) {
    case 'ready':
      return 'Wajah siap diperiksa'
    case 'adjust':
      return 'Perlu atur posisi atau cahaya'
    case 'no_face':
      return 'Wajah belum terdeteksi'
    case 'multiple_faces':
      return 'Lebih dari satu wajah'
    case 'unavailable':
      return 'Pemeriksaan tidak tersedia'
    default:
      return 'Belum diuji'
  }
})

const cameraResolutionLabel = computed(() => {
  const width = cameraMetrics.value?.frame_width ?? cameraObservation.value?.frame_width
  const height = cameraMetrics.value?.frame_height ?? cameraObservation.value?.frame_height
  return width && height ? `${width} × ${height}` : 'Belum tersedia'
})

const cameraFpsLabel = computed(() => {
  const fps = cameraMetrics.value?.capture_fps
  return typeof fps === 'number' ? `${fps.toFixed(1)} FPS` : 'Mengukur…'
})

function recordPreviewFrame(): void {
  const now = performance.now()
  previewFrameTimes.push(now)
  while (previewFrameTimes.length > 1 && now - previewFrameTimes[0] > 3000) {
    previewFrameTimes.shift()
  }
  if (previewFrameTimes.length < 2 || now - lastPreviewFpsUpdate < 500) return
  const elapsed = now - previewFrameTimes[0]
  if (elapsed > 0) previewFps.value = Math.round(((previewFrameTimes.length - 1) * 1000) / elapsed)
  lastPreviewFpsUpdate = now
}

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
  if (diagnosticCandidate.value) return diagnosticCandidate.value.display_name
  if (previewStatus.value?.recognition_state === 'accepted') {
    return previewStatus.value.display_name ?? 'Identitas cocok'
  }
  if (!isFullscreen.value) {
    if (previewStatus.value?.recognition_state === 'waiting_for_calibration') {
      return 'AI belum dikalibrasi'
    }
    return 'Belum teridentifikasi'
  }
  if (previewStatus.value?.recognition_state === 'waiting_for_calibration') {
    return 'AI belum dikalibrasi'
  }
  if (
    recentAttendanceResult.value?.decision === 'pending' ||
    previewStatus.value?.recognition_state === 'accepted'
  )
    return 'Memeriksa presensi'
  if (cameraObservation.value?.state === 'ready') return 'Wajah siap diperiksa'
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
  if (diagnosticCandidate.value) {
    const candidate = diagnosticCandidate.value
    const className = candidate.class_name ? `${candidate.class_name}. ` : ''
    const score = `Kemiripan model ${(candidate.similarity * 100).toFixed(1)}% (bukan akurasi).`
    return previewStatus.value?.session_active
      ? `${className}${score} Identitas masih kandidat; presensi menunggu kebijakan pengenalan dan validasi API.`
      : `${className}${score} Preview saja; presensi belum dimulai.`
  }
  if (!isFullscreen.value) {
    return recognitionMessage.value
  }
  if (!previewStatus.value?.session_active) return recognitionMessage.value
  if (previewStatus.value?.recognition_state === 'waiting_for_calibration') {
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
  if (!previewStatus.value.camera_open)
    return 'Kamera belum terbuka. Periksa agent dan koneksi kamera.'
  if (!previewStatus.value.session_active)
    return 'Kamera aktif untuk preview siswa di kelas yang dijadwalkan. Presensi tidak dicatat sebelum sesi dibuka.'
  switch (previewStatus.value.recognition_state) {
    case 'waiting_for_calibration':
      return 'Pengenalan belum aktif karena admin belum menerapkan threshold Top-1 dan margin hasil benchmark. Presensi belum dibuat. Minta admin memeriksa konfigurasi AI & kamera.'
    case 'preview_only':
      return 'Pencocokan preview berjalan untuk kelas terjadwal di laboratorium ini. Hasilnya belum menjadi presensi.'
    case 'checking':
    case 'collecting':
      return 'Sedang memeriksa beberapa frame. Minta siswa menghadap kamera.'
    case 'accepted':
      return previewStatus.value.display_name
        ? 'Identitas cocok. Mengirim presensi untuk konfirmasi server.'
        : 'Identitas cocok, tetapi nama roster tidak tersedia.'
    case 'retry_frontal':
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
  const preview = document.querySelector<HTMLElement>('.camera-preview-view')
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
  const requestStartedAt = performance.now()
  try {
    const response = await authorizedFetch('/v1/frame.jpg')
    if (!response.ok) {
      if (response.status === 503 && frameUrl.value) {
        URL.revokeObjectURL(frameUrl.value)
        frameUrl.value = null
      }
      throw new Error('Frame kamera belum tersedia.')
    }
    const nextUrl = URL.createObjectURL(await response.blob())
    if (stopped) {
      URL.revokeObjectURL(nextUrl)
      return
    }
    const previousUrl = frameUrl.value
    frameUrl.value = nextUrl
    if (previousUrl) URL.revokeObjectURL(previousUrl)
    errorMessage.value = null
  } catch (error) {
    if (!stopped && !frameUrl.value) {
      errorMessage.value = error instanceof Error ? error.message : 'Preview kamera tidak tersedia.'
    }
  } finally {
    const targetFrameIntervalMs = 1000 / 15
    const waitMs = Math.max(0, targetFrameIntervalMs - (performance.now() - requestStartedAt))
    if (!stopped) frameTimer = setTimeout(() => void pollFrame(), waitMs)
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
  void loadDevicesAndLabs()
  try {
    previewToken.value = await openPreviewSession()
    if (stopped) return
    void pollFrame()
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
  <div class="st-page" aria-label="Preview kamera AI_EDGE">
    <UiPageHeader
      eyebrow="AI_EDGE · pilih perangkat & lab"
      title="Preview Kamera Presensi"
      description="Preview menggunakan stream yang sama dengan agent di PC lab ini; halaman ini tidak membuka webcam kedua."
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
          {{ isFullscreen ? 'Keluar layar penuh' : 'Tampilan depan kamera' }}
        </UiButton>
      </template>
    </UiPageHeader>
    <UiCard
      title="Sumber preview"
      subtitle="Lab → perangkat/kamera → hubungkan. Mengganti sumber melepas sambungan lama."
    >
      <div>
        <p class="st-table__muted">
          Bila ada 2 kamera / 2 lab, pilih perangkat di bawah untuk melihat konteks jadwal &amp;
          statusnya - video tetap dari kamera PC ini.
        </p>
        <div class="st-grid2">
          <label class="st-field"
            ><span>Perangkat</span>
            <UiSelect
              :model-value="selectedDeviceId"
              aria-label="Pilih perangkat kamera"
              data-testid="preview-device-select"
              @change="onDeviceChange"
            >
              <option v-for="d in devices" :key="d.device_id" :value="d.device_id">
                {{ d.name }} · {{ d.laboratory_name }} · {{ deviceHealthLabel(d.health_status) }}
              </option>
            </UiSelect>
          </label>
          <label class="st-field"
            ><span>Laboratorium</span>
            <UiSelect
              :model-value="selectedLabId"
              aria-label="Pilih laboratorium"
              data-testid="preview-lab-select"
              @change="onLabChange"
            >
              <option v-for="lab in laboratories" :key="lab.id" :value="lab.id">
                {{ lab.code }} - {{ lab.name }}
              </option>
            </UiSelect>
          </label>
        </div>
        <p v-if="deviceLoadError" class="st-alert st-alert--error" role="alert">
          {{ deviceLoadError }}
        </p>
        <div style="display: flex; gap: 8px; align-items: center; flex-wrap: wrap">
          <UiButton
            variant="secondary"
            type="button"
            data-testid="open-on-lab-device"
            @click="openOnLabDevice"
          >
            Buka di perangkat lab
          </UiButton>
          <p v-if="openedRemotely" class="st-table__muted" role="status">
            Dibuka dari perangkat lab: pastikan halaman ini dijalankan di PC lab yang memasang agent
            agar feed kamera lokal tersedia.
          </p>
        </div>
      </div>
    </UiCard>
    <p v-if="errorMessage" class="st-alert st-alert--error" role="alert">{{ errorMessage }}</p>

    <section
      v-if="!isFullscreen"
      class="camera-preview-view__telemetry"
      aria-label="Kualitas dan kinerja kamera"
    >
      <div>
        <span>Resolusi aktual</span>
        <strong>{{ cameraResolutionLabel }}</strong>
      </div>
      <div>
        <span>FPS capture aktual</span>
        <strong>{{ cameraFpsLabel }}</strong>
        <small>
          Target {{ cameraMetrics?.requested_fps ?? '-' }} FPS · driver
          {{ cameraMetrics?.driver_fps ?? '-' }} FPS
        </small>
      </div>
      <div>
        <span>FPS preview browser</span>
        <strong>{{ previewFps === null ? 'Mengukur…' : `${previewFps} FPS` }}</strong>
      </div>
      <div>
        <span>Kualitas frame</span>
        <strong>{{ cameraQualityLabel }}</strong>
        <small v-if="cameraMetrics?.quality_source === 'frame_filter'">
          Pemeriksaan cahaya dan ketajaman ringan dari gateway.
        </small>
        <small v-else>Ketajaman, cahaya, dan ukuran wajah terlihat pada kotak kamera.</small>
      </div>
    </section>

    <div class="camera-preview-view__layout">
      <figure class="camera-preview-view__frame">
        <div v-if="frameUrl" class="camera-preview-view__frame-stage">
          <img :src="frameUrl" alt="Preview langsung kamera presensi" @load="recordPreviewFrame" />
          <svg
            v-if="cameraObservation && cameraObservation.frame_width > 0"
            class="camera-preview-view__face-overlay"
            :viewBox="`0 0 ${cameraObservation.frame_width} ${cameraObservation.frame_height}`"
            preserveAspectRatio="xMidYMid meet"
            aria-hidden="true"
          >
            <g
              v-for="(face, index) in cameraObservation.faces"
              :key="`${index}-${cameraObservation.state}`"
              :class="[
                'camera-preview-view__face-mark',
                face.acceptable || identityMatched ? 'is-ready' : 'is-adjust',
              ]"
            >
              <rect
                :x="face.x * cameraObservation.frame_width"
                :y="face.y * cameraObservation.frame_height"
                :width="face.width * cameraObservation.frame_width"
                :height="face.height * cameraObservation.frame_height"
                :class="[
                  'camera-preview-view__face-box',
                  face.acceptable || identityMatched ? 'is-ready' : 'is-adjust',
                ]"
              />
              <template v-if="face.detection_confidence !== undefined">
                <rect
                  v-if="detectionLabel(face)"
                  :x="detectionLabel(face)?.x"
                  :y="detectionLabel(face)?.y"
                  :width="detectionLabel(face)?.width"
                  :height="detectionLabel(face)?.height"
                  rx="5"
                  class="camera-preview-view__confidence-bg"
                />
                <text
                  v-if="detectionLabel(face)"
                  :x="detectionLabel(face)?.textX"
                  :y="detectionLabel(face)?.textY"
                  :font-size="detectionLabel(face)?.fontSize"
                  class="camera-preview-view__confidence-text"
                >
                  {{ detectionLabel(face)?.text }}
                </text>
              </template>
            </g>
          </svg>
          <div
            class="camera-preview-view__guidance"
            :class="`is-${cameraObservation?.state ?? 'pending'}`"
            role="status"
          >
            <strong>{{ cameraObservationLabel }}</strong>
            <span>{{ cameraObservation?.message ?? 'Menunggu status kamera…' }}</span>
            <div v-if="cameraFaceMetrics.length" class="camera-preview-view__metrics">
              <span v-for="metric in cameraFaceMetrics" :key="metric">{{ metric }}</span>
            </div>
          </div>
        </div>
        <div v-else class="camera-preview-view__placeholder" role="status">
          <span aria-hidden="true">◉</span>
          <strong>{{ isStarting ? 'Menghubungkan ke agent…' : 'Preview belum tersedia' }}</strong>
          <p>Pastikan agent AI_EDGE berjalan pada komputer yang sama dengan browser ini.</p>
        </div>
        <figcaption>
          Gambar ditampilkan sementara di browser dan tidak disimpan oleh halaman ini.
        </figcaption>
      </figure>

      <aside
        class="camera-preview-view__identity"
        :class="identityPanelClass"
        aria-label="Status pengenalan siswa"
      >
        <p class="master-data__eyebrow">Hasil pengenalan</p>
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
        <p>{{ identityDisplayMessage }}</p>
        <div
          v-if="diagnosticCandidate"
          class="camera-preview-view__candidate"
          role="status"
          aria-live="polite"
        >
          <span>Kandidat sementara · belum diverifikasi presensi</span>
          <strong>{{ diagnosticCandidate.display_name }}</strong>
          <b>{{ diagnosticCandidate.class_name || 'Kelas tidak tersedia' }}</b>
          <b>{{ diagnosticSimilarityPercent }} kemiripan · bukan tingkat akurasi</b>
          <small>
            Nama adalah kandidat terdekat dari kelas yang terjadwal di laboratorium hari ini. Hasil
            preview tidak membuat presensi. Presensi hanya dicatat oleh Core API saat sesi aktif dan
            kebijakan pengenalan lolos.
          </small>
        </div>
        <div
          v-else-if="previewStatus?.recognition_state === 'preview_only'"
          class="camera-preview-view__candidate-empty"
          role="status"
        >
          <strong>Mencari siswa dari jadwal lab hari ini</strong>
          <small v-if="!previewStatus?.session_active">
            Kamera dapat menampilkan kandidat sebelum sesi dibuka. Presensi belum dicatat.
          </small>
          <small v-else-if="cameraObservation?.state !== 'ready'">
            {{ cameraObservation?.message ?? 'Menunggu satu wajah dengan kualitas yang cukup.' }}
          </small>
          <small v-else>
            Pastikan siswa sudah terdaftar dan memiliki template aktif untuk sesi ini.
          </small>
        </div>
        <RouterLink
          v-if="auth.account?.roles.includes('ADMIN') && !isFullscreen"
          class="button button--secondary camera-preview-view__settings-link"
          to="/app/ai-setup"
        >
          Atur kualitas &amp; pengenalan
        </RouterLink>
        <dl>
          <div>
            <dt>Sesi praktikum</dt>
            <dd>{{ previewStatus?.session_active ? 'Aktif' : 'Belum aktif' }}</dd>
          </div>
          <div>
            <dt>Kondisi kamera</dt>
            <dd>{{ previewStatus?.camera_open ? 'Terhubung' : 'Tidak terhubung' }}</dd>
          </div>
        </dl>
        <p class="camera-preview-view__privacy">
          <template v-if="isFullscreen && !previewStatus?.session_active">
            Kandidat preview belum terverifikasi dan tidak membuat presensi. Buka sesi sesuai jadwal
            untuk mulai mencatat kehadiran.
          </template>
          <template v-else-if="isFullscreen">
            Presensi hanya dinyatakan berhasil setelah Core API mengonfirmasi hasil.
          </template>
          <template v-else>
            Kandidat pada uji kamera hanya untuk petugas. Presensi baru tercatat setelah threshold
            aktif dan Core API mengonfirmasi hasil.
          </template>
        </p>
      </aside>
    </div>
  </div>
</template>
