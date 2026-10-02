<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import PageHeader from '../components/PageHeader.vue'
import { ApiError, getAiReadiness, listDevices, type AiReadiness, type Device } from '../api/client'

const readiness = ref<AiReadiness | null>(null)
const devices = ref<Device[]>([])
const isLoading = ref(false)
const errorMessage = ref<string | null>(null)
let refreshTimer: ReturnType<typeof setInterval> | undefined

async function refreshReadiness(): Promise<void> {
  isLoading.value = true
  errorMessage.value = null
  try {
    const [nextReadiness, nextDevices] = await Promise.all([
      getAiReadiness(),
      listDevices({ limit: 100, offset: 0 }),
    ])
    readiness.value = nextReadiness
    devices.value = nextDevices.items
  } catch (error) {
    errorMessage.value =
      error instanceof ApiError ? error.message : 'Status AI tidak dapat dimuat saat ini.'
  } finally {
    isLoading.value = false
  }
}

function statusLabel(value: boolean | null): string {
  if (value === null) return 'Belum diketahui'
  return value ? 'Siap' : 'Belum siap'
}

function profileLabel(profile: AiReadiness['deployment_profile']): string {
  return profile === 'AI_CENTRAL' ? 'AI Central · server' : 'AI Edge · PC kamera'
}

function serviceLabel(status: AiReadiness['central_ai_status']): string {
  switch (status) {
    case 'disabled':
      return 'Tidak digunakan pada profile ini'
    case 'ready':
      return 'Siap'
    case 'degraded':
      return 'Berjalan, konfigurasi belum lengkap'
    case 'unreachable':
      return 'Tidak terjangkau'
  }
}

onMounted(() => {
  void refreshReadiness()
  refreshTimer = setInterval(() => void refreshReadiness(), 30_000)
})

onBeforeUnmount(() => {
  if (refreshTimer) clearInterval(refreshTimer)
})
</script>

<template>
  <section class="ai-setup-view" aria-label="Kesiapan AI dan kamera">
    <PageHeader
      eyebrow="Administrasi sistem"
      title="AI & kamera"
      description="Periksa profile yang berjalan, ketersediaan model, dan kesiapan inference."
    >
      <template #actions>
        <button
          class="button button--secondary"
          type="button"
          :disabled="isLoading"
          @click="refreshReadiness"
        >
          {{ isLoading ? 'Memeriksa…' : 'Periksa lagi' }}
        </button>
      </template>
    </PageHeader>

    <p v-if="errorMessage" class="master-data__alert" role="alert">{{ errorMessage }}</p>

    <template v-if="readiness">
      <section class="ai-setup-view__profile master-data__panel">
        <div>
          <p class="master-data__eyebrow">Profile aktif</p>
          <h2>{{ profileLabel(readiness.deployment_profile) }}</h2>
          <p>
            Model diunduh otomatis saat setup lokal atau instalasi kamera AI_EDGE. Unduhan memakai
            versi yang dipatok dan checksum diverifikasi.
          </p>
        </div>
        <RouterLink class="button button--secondary" to="/app/devices">Lihat perangkat</RouterLink>
      </section>

      <div class="ai-setup-view__grid">
        <article class="ai-setup-view__card">
          <span class="ai-setup-view__icon" aria-hidden="true">01</span>
          <p class="master-data__eyebrow">Model untuk pendaftaran</p>
          <h2>{{ readiness.enrollment_models_ready ? 'Tersedia' : 'Belum tersedia' }}</h2>
          <p>
            Dipakai API untuk memeriksa capture enrollment; file model tidak disimpan ke database.
          </p>
          <span
            class="ai-setup-view__badge"
            :class="readiness.enrollment_models_ready ? 'is-ready' : 'is-pending'"
          >
            {{ statusLabel(readiness.enrollment_models_ready) }}
          </span>
        </article>

        <article class="ai-setup-view__card">
          <span class="ai-setup-view__icon" aria-hidden="true">02</span>
          <p class="master-data__eyebrow">AI Central</p>
          <h2>{{ serviceLabel(readiness.central_ai_status) }}</h2>
          <template v-if="readiness.central_ai_status !== 'disabled'">
            <dl class="ai-setup-view__checks">
              <div>
                <dt>YuNet + SFace</dt>
                <dd>{{ statusLabel(readiness.central_ai_models_ready) }}</dd>
              </div>
              <div>
                <dt>Versi model</dt>
                <dd>{{ readiness.central_ai_model_version ?? 'Belum dilaporkan' }}</dd>
              </div>
              <div>
                <dt>Threshold kalibrasi</dt>
                <dd>{{ statusLabel(readiness.central_ai_thresholds_configured) }}</dd>
              </div>
            </dl>
          </template>
          <p v-else>
            Profile AI_EDGE memakai model pada PC kamera; status perangkat terlihat di menu
            Perangkat.
          </p>
        </article>

        <article class="ai-setup-view__card ai-setup-view__card--wide">
          <span class="ai-setup-view__icon" aria-hidden="true">03</span>
          <p class="master-data__eyebrow">Threshold pengenalan</p>
          <h2>Harus berasal dari kalibrasi</h2>
          <p>
            Sistem tidak mengisi angka otomatis. Untuk AI Central, nilai Top-1 dan margin disetel
            pada <code>.env</code> lalu service AI dimulai ulang. Untuk AI_EDGE, nilainya ada pada
            <code>recognition.min_top1_similarity</code> dan
            <code>recognition.min_top1_top2_margin</code> di konfigurasi agent.
          </p>
          <p class="ai-setup-view__note">
            Threshold belum dapat diubah dari dashboard. SFace yang diunduh masih untuk evaluasi
            sampai sekolah menyetujui izin penggunaannya.
          </p>
        </article>

        <article class="ai-setup-view__card ai-setup-view__card--wide">
          <span class="ai-setup-view__icon" aria-hidden="true">04</span>
          <p class="master-data__eyebrow">Kamera</p>
          <h2>Kamera dicek pada perangkatnya</h2>
          <p>
            Preview enrollment memakai kamera browser operator. Kamera presensi milik PC AI_EDGE
            atau gateway STB; dashboard menampilkan status heartbeat/kamera yang dilaporkan
            perangkat, tetapi tidak bisa membuka webcam komputer operator dari server.
          </p>
          <p>
            Untuk memilih camera index dan mengukur pencahayaan, jalankan camera calibration utility
            di host kamera.
          </p>
        </article>
      </div>

      <section class="master-data__panel ai-setup-view__devices">
        <div class="master-data__panel-heading">
          <div>
            <p class="master-data__eyebrow">Kamera presensi</p>
            <h2>Kesiapan perangkat terdaftar</h2>
          </div>
          <RouterLink class="button button--text" to="/app/devices">Kelola perangkat</RouterLink>
        </div>
        <div class="master-data__table-wrap">
          <table class="master-data__table">
            <thead>
              <tr>
                <th scope="col">Perangkat / lab</th>
                <th scope="col">Profile</th>
                <th scope="col">Model dilaporkan</th>
                <th scope="col">Kamera</th>
                <th scope="col">Koneksi</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="devices.length === 0">
                <td colspan="5" class="master-data__empty">Belum ada perangkat.</td>
              </tr>
              <tr v-for="device in devices" :key="device.device_id">
                <td data-label="Perangkat / lab">
                  <strong>{{ device.name }}</strong>
                  <small>{{ device.laboratory_code }} · {{ device.laboratory_name }}</small>
                </td>
                <td data-label="Profile">{{ device.deployment_profile }}</td>
                <td data-label="Model dilaporkan">
                  {{
                    device.deployment_profile === 'AI_EDGE'
                      ? (device.model_version ?? 'Belum dilaporkan')
                      : 'Dijalankan di server'
                  }}
                </td>
                <td data-label="Kamera">{{ device.camera_status }}</td>
                <td data-label="Koneksi">{{ device.health_status }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </template>
  </section>
</template>
