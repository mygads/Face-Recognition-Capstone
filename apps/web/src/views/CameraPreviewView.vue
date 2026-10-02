<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useAuthStore } from '../stores/auth'

type PreviewStatus = {
  camera_open: boolean
  session_active: boolean
  recognition_state: string
  display_name: string | null
  updated_at: number | null
  camera_observation?: CameraObservation
  attendance_result?: AttendanceResult | null
  calibration?: CalibrationStatus
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
  updated_at: number
}

type CalibrationSummary = {
  sample_count: number
  top1_min?: number
  top1_mean?: number
  top1_max?: number
  margin_min?: number
  margin_mean?: number
  margin_max?: number
  identity_match_count?: number
}

type CalibrationStatus = {
  students: { student_id: string; full_name: string }[]
  sample_pending: boolean
  gallery_identity_count: number
  margin_interpretable: boolean
  last_result: { phase: string; result: string; message: string } | null
  genuine: CalibrationSummary
  impostor: CalibrationSummary
}

const auth = useAuthStore()
const previewToken = ref<string | null>(null)
const frameUrl = ref<string | null>(null)
const previewStatus = ref<PreviewStatus | null>(null)
const calibration = computed(() => previewStatus.value?.calibration ?? null)
const cameraObservation = computed(() => previewStatus.value?.camera_observation ?? null)
const errorMessage = ref<string | null>(null)
const isStarting = ref(true)
const isFullscreen = ref(false)
const selectedStudentId = ref('')
const isRequestingCalibrationSample = ref(false)
const identityConfirmed = ref(false)
const volunteerConsented = ref(false)
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
  if (!isFullscreen.value) {
    return previewStatus.value?.recognition_state === 'accepted'
      ? (previewStatus.value.display_name ?? 'Identitas cocok')
      : 'Belum teridentifikasi'
  }
  if (recentAttendanceResult.value?.decision === 'recorded') return 'Presensi tercatat'
  if (recentAttendanceResult.value?.decision === 'not_recorded') return 'Presensi belum tercatat'
  if (
    recentAttendanceResult.value?.decision === 'pending' ||
    previewStatus.value?.recognition_state === 'accepted'
  )
    return 'Memeriksa presensi'
  if (cameraObservation.value?.state === 'ready') return 'Wajah siap diperiksa'
  return 'Posisikan wajah di kamera'
})

const identityDisplayMessage = computed(() => {
  if (!isFullscreen.value) {
    if (recentAttendanceResult.value?.decision === 'recorded') {
      return recentAttendanceResult.value.attendance_status === 'late'
        ? 'Presensi sudah tercatat sebagai terlambat.'
        : 'Presensi sudah tercatat sebagai hadir.'
    }
    if (recentAttendanceResult.value?.decision === 'not_recorded') {
      return 'Kandidat belum menghasilkan presensi. Periksa alasan pada status sesi atau minta bantuan petugas.'
    }
    return recognitionMessage.value
  }
  if (!previewStatus.value?.session_active) return 'Sesi praktikum belum dibuka.'
  if (recentAttendanceResult.value?.decision === 'recorded') {
    return recentAttendanceResult.value.attendance_status === 'late'
      ? 'Terima kasih. Presensi tercatat sebagai terlambat.'
      : 'Terima kasih. Presensi tercatat sebagai hadir.'
  }
  if (recentAttendanceResult.value?.decision === 'not_recorded') {
    return 'Presensi belum tercatat. Silakan minta bantuan petugas.'
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
    return 'Kamera aktif. Buka sesi praktikum agar pengenalan dimulai.'
  switch (previewStatus.value.recognition_state) {
    case 'waiting_for_calibration':
      return 'Preview aktif. Pengenalan identitas menunggu threshold hasil kalibrasi.'
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
  const enrolledStudents = previewStatus.value.calibration?.students ?? []
  if (!enrolledStudents.some((student) => student.student_id === selectedStudentId.value)) {
    selectedStudentId.value = enrolledStudents[0]?.student_id ?? ''
  }
  if (previewStatus.value.camera_open) errorMessage.value = null
}

async function requestCalibrationSample(phase: 'genuine' | 'impostor'): Promise<void> {
  if (isRequestingCalibrationSample.value) return
  isRequestingCalibrationSample.value = true
  errorMessage.value = null
  try {
    const response = await authorizedFetch('/v1/calibration-sample', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        phase,
        ...(phase === 'genuine' ? { student_id: selectedStudentId.value } : {}),
      }),
    })
    if (!response.ok) {
      const result = (await response.json().catch(() => ({}))) as { error?: string }
      const messages: Record<string, string> = {
        session_unavailable: 'Kamera dan sesi aktif diperlukan untuk mengambil sampel.',
        student_not_in_session: 'Siswa tersebut tidak memiliki template pada sesi aktif.',
        sample_in_progress: 'Satu sampel masih diproses. Tunggu hasilnya terlebih dahulu.',
        sample_limit: 'Batas 100 sampel per kategori tercapai. Reset agent untuk mulai ulang.',
      }
      throw new Error(messages[result.error ?? ''] ?? 'Agent menolak permintaan sampel.')
    }
    await refreshStatus()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : 'Sampel belum dapat dimulai.'
  } finally {
    isRequestingCalibrationSample.value = false
  }
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

function formatScore(value: number | undefined): string {
  return value === undefined ? '—' : value.toFixed(3)
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
    if (!stopped) frameTimer = setTimeout(() => void pollFrame(), 250)
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
    if (!stopped) statusTimer = setTimeout(() => void pollStatus(), 1500)
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
            <ellipse
              v-for="(face, index) in cameraObservation.faces"
              :key="`${index}-${cameraObservation.state}`"
              :cx="(face.x + face.width / 2) * cameraObservation.frame_width"
              :cy="(face.y + face.height / 2) * cameraObservation.frame_height"
              :rx="face.width * cameraObservation.frame_width * 0.58"
              :ry="face.height * cameraObservation.frame_height * 0.62"
              :class="[
                'camera-preview-view__face-ring',
                face.acceptable ? 'is-ready' : 'is-adjust',
              ]"
            />
          </svg>
          <div
            class="camera-preview-view__guidance"
            :class="`is-${cameraObservation?.state ?? 'pending'}`"
            role="status"
          >
            <strong>{{ cameraObservationLabel }}</strong>
            <span>{{ cameraObservation?.message ?? 'Menunggu status kamera…' }}</span>
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
          <template v-if="isFullscreen">
            Layar siswa tidak menampilkan nama atau kandidat. Status berhasil hanya tampil setelah
            Core API mengonfirmasi presensi.
          </template>
          <template v-else>
            Nama kandidat hanya tampil pada halaman operator setelah kebijakan pengenalan cocok.
            Keputusan kehadiran tetap divalidasi API.
          </template>
        </p>
      </aside>
    </div>

    <section class="camera-preview-view__diagnostics" aria-labelledby="diagnostics-title">
      <div class="camera-preview-view__diagnostics-heading">
        <div>
          <p class="master-data__eyebrow">Pemeriksaan lokal</p>
          <h3 id="diagnostics-title">Uji kecocokan kamera</h3>
          <p>
            Mengambil satu rangkaian frame berkualitas per permintaan untuk membandingkan skor siswa
            terdaftar dan relawan dewasa yang tidak terdaftar.
          </p>
        </div>
        <span class="camera-preview-view__diagnostic-badge">Diagnostik saja</span>
      </div>

      <div class="camera-preview-view__diagnostic-warning" role="note">
        Tidak membuat presensi dari sampel uji dan tidak mengubah threshold. Foto hanya diproses
        sementara oleh agent yang sudah berjalan; foto dan embedding tidak disimpan. Ringkasan skor
        berada di memori agent dan terhapus saat sesi berganti atau agent dimulai ulang.
      </div>

      <template v-if="calibration">
        <div class="camera-preview-view__diagnostic-controls">
          <label>
            Siswa terdaftar
            <select v-model="selectedStudentId" :disabled="calibration.sample_pending">
              <option value="" disabled>Pilih siswa dengan template aktif</option>
              <option
                v-for="student in calibration.students"
                :key="student.student_id"
                :value="student.student_id"
              >
                {{ student.full_name }}
              </option>
            </select>
          </label>
          <label class="camera-preview-view__consent">
            <input v-model="identityConfirmed" type="checkbox" />
            Saya memastikan orang di kamera adalah siswa yang dipilih.
          </label>
          <button
            class="button button--primary"
            type="button"
            :disabled="
              !previewStatus?.camera_open ||
              !previewStatus?.session_active ||
              !selectedStudentId ||
              !identityConfirmed ||
              calibration.sample_pending ||
              isRequestingCalibrationSample
            "
            @click="requestCalibrationSample('genuine')"
          >
            Ambil sampel siswa terdaftar
          </button>
        </div>

        <div class="camera-preview-view__diagnostic-controls">
          <label class="camera-preview-view__consent">
            <input v-model="volunteerConsented" type="checkbox" />
            Relawan dewasa setuju ikut uji lokal dan bukan siswa yang terdaftar.
          </label>
          <button
            class="button button--secondary"
            type="button"
            :disabled="
              !previewStatus?.camera_open ||
              !previewStatus?.session_active ||
              !volunteerConsented ||
              calibration.sample_pending ||
              isRequestingCalibrationSample
            "
            @click="requestCalibrationSample('impostor')"
          >
            Ambil sampel relawan non-terdaftar
          </button>
        </div>

        <p
          v-if="calibration.sample_pending"
          class="camera-preview-view__sample-status"
          role="status"
        >
          Memeriksa frame. Tahan posisi sampai hasil tampil…
        </p>
        <p
          v-else-if="calibration.last_result"
          class="camera-preview-view__sample-status"
          :class="calibration.last_result.result === 'retry' ? 'is-retry' : 'is-complete'"
          role="status"
        >
          {{ calibration.last_result.message }}
        </p>

        <div
          v-if="calibration.gallery_identity_count < 2"
          class="camera-preview-view__diagnostic-warning"
          role="note"
        >
          Gallery saat ini hanya memiliki {{ calibration.gallery_identity_count }} identitas dengan
          template. Margin Top‑1/Top‑2 disembunyikan karena belum ada identitas kedua untuk
          dibandingkan. Enrollment beberapa siswa diperlukan sebelum menilai margin.
        </div>

        <div class="camera-preview-view__diagnostic-table-wrap">
          <table class="camera-preview-view__diagnostic-table">
            <thead>
              <tr>
                <th scope="col">Kelompok</th>
                <th scope="col">Sampel</th>
                <th scope="col">Top‑1 min / rata-rata / max</th>
                <th v-if="calibration.margin_interpretable" scope="col">
                  Margin min / rata-rata / max
                </th>
                <th v-if="calibration.genuine.identity_match_count !== undefined" scope="col">
                  Identitas cocok
                </th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <th scope="row">Siswa terdaftar</th>
                <td>{{ calibration.genuine.sample_count }}</td>
                <td>
                  {{ formatScore(calibration.genuine.top1_min) }} /
                  {{ formatScore(calibration.genuine.top1_mean) }} /
                  {{ formatScore(calibration.genuine.top1_max) }}
                </td>
                <td v-if="calibration.margin_interpretable">
                  {{ formatScore(calibration.genuine.margin_min) }} /
                  {{ formatScore(calibration.genuine.margin_mean) }} /
                  {{ formatScore(calibration.genuine.margin_max) }}
                </td>
                <td v-if="calibration.genuine.identity_match_count !== undefined">
                  {{ calibration.genuine.identity_match_count }} /
                  {{ calibration.genuine.sample_count }}
                </td>
              </tr>
              <tr>
                <th scope="row">Relawan non-terdaftar</th>
                <td>{{ calibration.impostor.sample_count }}</td>
                <td>
                  {{ formatScore(calibration.impostor.top1_min) }} /
                  {{ formatScore(calibration.impostor.top1_mean) }} /
                  {{ formatScore(calibration.impostor.top1_max) }}
                </td>
                <td v-if="calibration.margin_interpretable">
                  {{ formatScore(calibration.impostor.margin_min) }} /
                  {{ formatScore(calibration.impostor.margin_mean) }} /
                  {{ formatScore(calibration.impostor.margin_max) }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <p class="camera-preview-view__diagnostic-limit">
          Hasil ini hanya eksplorasi pada kamera, ruangan, model, dan relawan ini. Sampel sedikit
          tidak cukup untuk memperkirakan false-accept rate operasional atau menetapkan threshold
          produksi. Catat threshold dari benchmark yang disetujui secara terpisah.
        </p>
      </template>
      <p v-else class="camera-preview-view__sample-status" role="status">
        Menunggu status sesi dan roster template dari agent.
      </p>
    </section>
  </section>
</template>
