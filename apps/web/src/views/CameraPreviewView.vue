<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useAuthStore } from '../stores/auth'

type PreviewStatus = {
  camera_open: boolean
  session_active: boolean
  recognition_state: string
  display_name: string | null
  updated_at: number | null
}

const auth = useAuthStore()
const previewToken = ref<string | null>(null)
const frameUrl = ref<string | null>(null)
const previewStatus = ref<PreviewStatus | null>(null)
const errorMessage = ref<string | null>(null)
const isStarting = ref(true)
let frameTimer: ReturnType<typeof setTimeout> | undefined
let statusTimer: ReturnType<typeof setTimeout> | undefined
let stopped = false

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

async function authorizedFetch(path: string): Promise<Response> {
  if (!previewBaseUrl.value || !previewToken.value) throw new Error('Sesi preview belum aktif.')
  const response = await fetch(`${previewBaseUrl.value}${path}`, {
    headers: { 'X-Presensi-Preview-Token': previewToken.value },
    cache: 'no-store',
  })
  if (response.status === 401) {
    previewToken.value = await openPreviewSession()
    return fetch(`${previewBaseUrl.value}${path}`, {
      headers: { 'X-Presensi-Preview-Token': previewToken.value },
      cache: 'no-store',
    })
  }
  return response
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
    const response = await authorizedFetch('/v1/status')
    if (!response.ok) throw new Error('Status kamera belum tersedia.')
    previewStatus.value = (await response.json()) as PreviewStatus
    if (previewStatus.value.camera_open) errorMessage.value = null
  } catch (error) {
    if (!stopped) {
      errorMessage.value = error instanceof Error ? error.message : 'Status kamera tidak tersedia.'
    }
  } finally {
    if (!stopped) statusTimer = setTimeout(() => void pollStatus(), 1500)
  }
}

onMounted(async () => {
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
    </div>

    <p v-if="errorMessage" class="master-data__alert" role="alert">{{ errorMessage }}</p>

    <div class="camera-preview-view__layout">
      <figure class="camera-preview-view__frame">
        <img v-if="frameUrl" :src="frameUrl" alt="Preview langsung kamera presensi" />
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
        <h3>
          {{
            previewStatus?.recognition_state === 'accepted'
              ? previewStatus.display_name
              : 'Belum teridentifikasi'
          }}
        </h3>
        <p>{{ recognitionMessage }}</p>
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
          Nama hanya tampil setelah kecocokan melewati kebijakan yang dikonfigurasi. Keputusan
          kehadiran tetap divalidasi API.
        </p>
      </aside>
    </div>
  </section>
</template>
