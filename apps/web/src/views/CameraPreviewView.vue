<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useAuthStore } from '../stores/auth'

type PreviewStatus = {
  camera_open: boolean
  session_active: boolean
  recognition_state: string
  display_name: string | null
  diagnostic_candidate?: DiagnosticCandidate | null
  updated_at: number | null
  camera_observation?: CameraObservation
  attendance_result?: AttendanceResult | null
}

type CameraFaceObservation = {
  x: number
  y: number
  width: number
  height: number
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
  decision: 'pending' | 'recorded' | 'not_recorded'
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
const previewToken = ref<string | null>(null)
const frameUrl = ref<string | null>(null)
const previewStatus = ref<PreviewStatus | null>(null)
const cameraObservation = computed(() => previewStatus.value?.camera_observation ?? null)
const cameraFaceMetrics = computed(() => {
  const face = cameraObservation.value?.faces[0]
  if (!face) return []
  const metrics: string[] = []
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
        : ` · target ${Math.round(face.min_brightness)}–${Math.round(face.max_brightness)}`
    metrics.push(`Cahaya ${face.brightness.toFixed(1)}${range}`)
  }
  return metrics
})
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
  if (!result || Date.now() / 1000 - result.updated_at > 15) return null
  return result
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

const identityTitle = computed(() => {
  if (recentAttendanceResult.value?.decision === 'recorded') {
    return recentAttendanceResult.value.display_name ?? 'Presensi tercatat'
  }
  if (recentAttendanceResult.value?.decision === 'not_recorded') return 'Presensi belum tercatat'
  if (diagnosticCandidate.value) return diagnosticCandidate.value.display_name
  if (!isFullscreen.value) {
    if (previewStatus.value?.recognition_state === 'waiting_for_calibration') {
      return 'AI belum dikalibrasi'
    }
    return previewStatus.value?.recognition_state === 'accepted'
      ? (previewStatus.value.display_name ?? 'Identitas cocok')
      : 'Belum teridentifikasi'
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
  if (recentAttendanceResult.value?.decision === 'not_recorded') {
    return 'Presensi belum tercatat. Silakan minta bantuan petugas.'
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
        ? `Teridentifikasi: ${previewStatus.value.display_name}. Presensi menunggu validasi Core API.`
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
  const response = await fetch(`${previewBaseUrl.value}/v1/session`, {
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
  const response = await fetch(`${previewBaseUrl.value}${path}`, {
    ...init,
    headers,
    cache: 'no-store',
  })
  if (response.status === 401) {
    previewToken.value = await openPreviewSession()
    headers.set('X-Presensi-Preview-Token', previewToken.value)
    return fetch(`${previewBaseUrl.value}${path}`, {
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
    if (!stopped) frameTimer = setTimeout(() => void pollFrame(), 100)
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
  <section class="camera-preview-view" aria-label="Preview kamera AI_EDGE">
    <div class="camera-preview-view__intro">
      <div>
        <p class="master-data__eyebrow">AI_EDGE · satu kamera</p>
        <h2>Preview kamera presensi</h2>
        <p>
          Preview menggunakan stream yang sama dengan agent; halaman ini tidak membuka webcam kedua.
        </p>
      </div>
      <span
        class="camera-preview-view__badge"
        :class="previewStatus?.camera_open ? 'is-online' : 'is-offline'"
        role="status"
      >
        {{
          previewStatus?.camera_open
            ? 'Kamera aktif'
            : isStarting
              ? 'Menghubungkan…'
              : 'Menunggu kamera'
        }}
      </span>
      <button class="button button--secondary" type="button" @click="toggleFullscreen">
        {{ isFullscreen ? 'Keluar layar penuh' : 'Tampilan depan kamera' }}
      </button>
    </div>

    <p v-if="errorMessage" class="master-data__alert" role="alert">{{ errorMessage }}</p>

    <div class="camera-preview-view__layout">
      <figure class="camera-preview-view__frame">
        <div v-if="frameUrl" class="camera-preview-view__frame-stage">
          <img :src="frameUrl" alt="Preview langsung kamera presensi" />
          <svg
            v-if="cameraObservation && cameraObservation.frame_width > 0"
            class="camera-preview-view__face-overlay"
            :viewBox="`0 0 ${cameraObservation.frame_width} ${cameraObservation.frame_height}`"
            preserveAspectRatio="xMidYMid meet"
            aria-hidden="true"
          >
            <rect
              v-for="(face, index) in cameraObservation.faces"
              :key="`${index}-${cameraObservation.state}`"
              :x="face.x * cameraObservation.frame_width"
              :y="face.y * cameraObservation.frame_height"
              :width="face.width * cameraObservation.frame_width"
              :height="face.height * cameraObservation.frame_height"
              :class="['camera-preview-view__face-box', face.acceptable ? 'is-ready' : 'is-adjust']"
            />
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

      <aside class="camera-preview-view__identity" aria-label="Status pengenalan siswa">
        <p class="master-data__eyebrow">Hasil pengenalan</p>
        <h3>{{ identityTitle }}</h3>
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
          v-if="
            !isFullscreen &&
            previewStatus?.recognition_state === 'waiting_for_calibration' &&
            auth.account?.roles.includes('ADMIN')
          "
          class="button button--secondary camera-preview-view__settings-link"
          to="/app/ai-setup"
        >
          Buka AI & kamera
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
  </section>
</template>
