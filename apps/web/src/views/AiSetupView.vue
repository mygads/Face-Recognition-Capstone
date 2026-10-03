<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import PageHeader from '../components/PageHeader.vue'
import {
  ApiError,
  getAiReadiness,
  getCentralRecognitionConfiguration,
  getDeviceRuntimeConfiguration,
  getEnrollmentQualityConfiguration,
  listDevices,
  saveCentralRecognitionConfiguration,
  saveEdgeDeviceConfiguration,
  saveEnrollmentQualityConfiguration,
  saveGatewayDeviceConfiguration,
  type AiReadiness,
  type Device,
  type DeviceRuntimeConfiguration,
  type EnrollmentQualityConfiguration,
  type RecognitionConfiguration,
  type StbGatewayConfiguration,
} from '../api/client'

type SettingsTab = 'enrollment' | 'devices' | 'central'
type UnknownSettings = Record<string, unknown>

const readiness = ref<AiReadiness | null>(null)
const devices = ref<Device[]>([])
const selectedDeviceId = ref('')
const deviceConfiguration = ref<DeviceRuntimeConfiguration | null>(null)
const isLoading = ref(false)
const isSaving = ref(false)
const errorMessage = ref<string | null>(null)
const successMessage = ref<string | null>(null)
const activeTab = ref<SettingsTab>('enrollment')
const settingsTabs = computed<{ id: SettingsTab; label: string }[]>(() => {
  const tabs: { id: SettingsTab; label: string }[] = [
    {
      id: 'enrollment',
      label:
        readiness.value?.deployment_profile === 'AI_EDGE'
          ? 'Kualitas capture'
          : 'Kualitas enrollment',
    },
    {
      id: 'devices',
      label:
        readiness.value?.deployment_profile === 'AI_EDGE' ? 'Pengenalan AI_EDGE' : 'STB gateway',
    },
  ]
  if (readiness.value?.deployment_profile === 'AI_CENTRAL') {
    tabs.push({ id: 'central', label: 'AI Central' })
  }
  return tabs
})
let refreshTimer: ReturnType<typeof setInterval> | undefined
let loadedEnrollmentSettings = false
let loadedCentralSettings = false

const enrollmentForm = ref<EnrollmentQualityConfiguration>({
  min_face_pixels: 80,
  min_sharpness: 45,
  min_brightness: 25,
  max_brightness: 235,
})
const centralForm = ref<RecognitionConfiguration>(recognitionDefaults())
const edgeForm = ref<RecognitionConfiguration>(recognitionDefaults())
const gatewayForm = ref<StbGatewayConfiguration>({
  motion_threshold: 7,
  periodic_burst_seconds: 30,
  minimum_burst_interval_seconds: 5,
  burst_frame_count: 3,
  burst_frame_interval_seconds: 0.2,
  jpeg_quality: 75,
  min_brightness: 20,
  max_brightness: 240,
  min_sharpness: 8,
})

const selectedDevice = computed(
  () => devices.value.find((device) => device.device_id === selectedDeviceId.value) ?? null,
)
const edgeThresholdsConfigured = computed(
  () => edgeForm.value.min_top1_similarity !== null && edgeForm.value.min_top1_top2_margin !== null,
)

function recognitionDefaults(): RecognitionConfiguration {
  return {
    min_face_pixels: 80,
    min_laplacian_variance: 45,
    min_brightness: 25,
    max_brightness: 235,
    min_top1_similarity: null,
    min_top1_top2_margin: null,
    minimum_agreeing_frames: 3,
    sample_every_n_frames: 5,
    best_frame_count: 5,
    max_history_frames: 10,
    calibration_reference: null,
  }
}

function numeric(settings: UnknownSettings, key: string, fallback: number): number {
  const value = settings[key]
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback
}

function optionalNumeric(settings: UnknownSettings, key: string): number | null {
  const value = settings[key]
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function recognitionFrom(settings: UnknownSettings): RecognitionConfiguration {
  const defaults = recognitionDefaults()
  return {
    min_face_pixels: numeric(settings, 'min_face_pixels', defaults.min_face_pixels),
    min_laplacian_variance: numeric(
      settings,
      'min_laplacian_variance',
      defaults.min_laplacian_variance,
    ),
    min_brightness: numeric(settings, 'min_brightness', defaults.min_brightness),
    max_brightness: numeric(settings, 'max_brightness', defaults.max_brightness),
    min_top1_similarity: optionalNumeric(settings, 'min_top1_similarity'),
    min_top1_top2_margin: optionalNumeric(settings, 'min_top1_top2_margin'),
    minimum_agreeing_frames: numeric(
      settings,
      'minimum_agreeing_frames',
      defaults.minimum_agreeing_frames,
    ),
    sample_every_n_frames: numeric(
      settings,
      'sample_every_n_frames',
      defaults.sample_every_n_frames,
    ),
    best_frame_count: numeric(settings, 'best_frame_count', defaults.best_frame_count),
    max_history_frames: numeric(settings, 'max_history_frames', defaults.max_history_frames),
    calibration_reference:
      typeof settings.calibration_reference === 'string' ? settings.calibration_reference : null,
  }
}

function copyEnrollmentQualityToEdge(): void {
  edgeForm.value = {
    ...edgeForm.value,
    min_face_pixels: enrollmentForm.value.min_face_pixels,
    min_laplacian_variance: enrollmentForm.value.min_sharpness,
    min_brightness: enrollmentForm.value.min_brightness,
    max_brightness: enrollmentForm.value.max_brightness,
  }
}

function updateSavedDevice(saved: DeviceRuntimeConfiguration): void {
  deviceConfiguration.value = saved
  const index = devices.value.findIndex((item) => item.device_id === saved.device_id)
  if (index >= 0) {
    devices.value[index] = {
      ...devices.value[index],
      config_applied_revision: saved.applied_revision,
      config_apply_status: saved.apply_status,
      config_error_code: saved.error_code ?? null,
    }
  }
}

function gatewayFrom(settings: UnknownSettings): StbGatewayConfiguration {
  return {
    motion_threshold: numeric(settings, 'motion_threshold', 7),
    periodic_burst_seconds: numeric(settings, 'periodic_burst_seconds', 30),
    minimum_burst_interval_seconds: numeric(settings, 'minimum_burst_interval_seconds', 5),
    burst_frame_count: numeric(settings, 'burst_frame_count', 3),
    burst_frame_interval_seconds: numeric(settings, 'burst_frame_interval_seconds', 0.2),
    jpeg_quality: numeric(settings, 'jpeg_quality', 75),
    min_brightness: numeric(settings, 'min_brightness', 20),
    max_brightness: numeric(settings, 'max_brightness', 240),
    min_sharpness: numeric(settings, 'min_sharpness', 8),
  }
}

async function refreshReadiness(forceSettings = false): Promise<void> {
  isLoading.value = true
  errorMessage.value = null
  try {
    const nextReadiness = await getAiReadiness()
    const expectedDeviceProfile =
      nextReadiness.deployment_profile === 'AI_EDGE' ? 'AI_EDGE' : 'STB_GATEWAY'
    const [nextDevices, enrollment, central] = await Promise.all([
      listDevices({
        limit: 100,
        offset: 0,
        deployment_profile: expectedDeviceProfile,
        is_active: true,
      }),
      !loadedEnrollmentSettings || forceSettings ? getEnrollmentQualityConfiguration() : null,
      nextReadiness.deployment_profile === 'AI_CENTRAL' && (!loadedCentralSettings || forceSettings)
        ? getCentralRecognitionConfiguration()
        : null,
    ])
    readiness.value = nextReadiness
    devices.value = nextDevices.items.filter(
      (device) => device.is_active && device.deployment_profile === expectedDeviceProfile,
    )
    if (nextReadiness.deployment_profile !== 'AI_CENTRAL' && activeTab.value === 'central') {
      activeTab.value = 'devices'
    }
    if (enrollment) {
      const enrollmentSettings = enrollment.settings as UnknownSettings
      enrollmentForm.value = {
        min_face_pixels: numeric(enrollmentSettings, 'min_face_pixels', 80),
        min_sharpness: numeric(enrollmentSettings, 'min_sharpness', 45),
        min_brightness: numeric(enrollmentSettings, 'min_brightness', 25),
        max_brightness: numeric(enrollmentSettings, 'max_brightness', 235),
      }
      loadedEnrollmentSettings = true
    }
    if (central) {
      centralForm.value = recognitionFrom(central.settings as UnknownSettings)
      loadedCentralSettings = true
    }
    if (!devices.value.some((item) => item.device_id === selectedDeviceId.value)) {
      selectedDeviceId.value = devices.value[0]?.device_id ?? ''
      deviceConfiguration.value = null
    }
    if (
      selectedDeviceId.value &&
      (!deviceConfiguration.value || deviceConfiguration.value.device_id !== selectedDeviceId.value)
    ) {
      await loadDeviceConfiguration(selectedDeviceId.value)
    } else if (selectedDevice.value && deviceConfiguration.value) {
      deviceConfiguration.value.applied_revision = selectedDevice.value.config_applied_revision
      deviceConfiguration.value.apply_status = selectedDevice.value.config_apply_status
      deviceConfiguration.value.error_code = selectedDevice.value.config_error_code
    } else if (!selectedDeviceId.value) {
      deviceConfiguration.value = null
    }
  } catch (error) {
    errorMessage.value =
      error instanceof ApiError ? error.message : 'Status dan konfigurasi AI tidak dapat dimuat.'
  } finally {
    isLoading.value = false
  }
}

async function loadDeviceConfiguration(deviceId: string): Promise<void> {
  if (!deviceId) {
    deviceConfiguration.value = null
    return
  }
  try {
    const result = await getDeviceRuntimeConfiguration(deviceId)
    deviceConfiguration.value = result
    if (result.deployment_profile === 'AI_EDGE') {
      edgeForm.value = recognitionFrom(result.settings as UnknownSettings)
      copyEnrollmentQualityToEdge()
    } else {
      gatewayForm.value = gatewayFrom(result.settings as UnknownSettings)
    }
  } catch (error) {
    errorMessage.value =
      error instanceof ApiError ? error.message : 'Konfigurasi perangkat tidak dapat dimuat.'
  }
}

async function saveEnrollment(): Promise<void> {
  await saveSettings(async () => {
    const saved = await saveEnrollmentQualityConfiguration(enrollmentForm.value)
    if (readiness.value) readiness.value.enrollment_quality_revision = saved.revision
    if (
      readiness.value?.deployment_profile === 'AI_EDGE' &&
      selectedDevice.value?.deployment_profile === 'AI_EDGE'
    ) {
      copyEnrollmentQualityToEdge()
      try {
        const deviceSaved = await saveEdgeDeviceConfiguration(
          selectedDeviceId.value,
          edgeForm.value,
        )
        updateSavedDevice(deviceSaved)
      } catch (error) {
        const detail = error instanceof Error ? ` ${error.message}` : ''
        throw new Error(
          `Kualitas enrollment tersimpan, tetapi pengaturan AI_EDGE belum tersinkron.${detail}`,
          { cause: error },
        )
      }
    }
  }, 'Kualitas capture tersimpan. Perangkat AI_EDGE terpilih akan menerapkannya saat tersambung.')
}

async function saveCentral(): Promise<void> {
  await saveSettings(async () => {
    await saveCentralRecognitionConfiguration(centralForm.value)
    await refreshReadiness()
  }, 'Pengaturan AI Central diterbitkan. Service akan mengambilnya otomatis.')
}

async function saveDevice(): Promise<void> {
  if (!selectedDevice.value) return
  await saveSettings(async () => {
    let saved: DeviceRuntimeConfiguration
    if (selectedDevice.value?.deployment_profile === 'AI_EDGE') {
      copyEnrollmentQualityToEdge()
      saved = await saveEdgeDeviceConfiguration(selectedDeviceId.value, edgeForm.value)
    } else {
      saved = await saveGatewayDeviceConfiguration(selectedDeviceId.value, gatewayForm.value)
    }
    updateSavedDevice(saved)
  }, 'Konfigurasi perangkat diterbitkan. Perangkat menerapkannya saat tersambung.')
}

async function saveSettings(action: () => Promise<void>, message: string): Promise<void> {
  isSaving.value = true
  errorMessage.value = null
  successMessage.value = null
  try {
    await action()
    successMessage.value = message
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : 'Pengaturan tidak dapat disimpan.'
  } finally {
    isSaving.value = false
  }
}

function parseOptionalNumber(event: Event): number | null {
  const value = (event.target as HTMLInputElement).value
  return value === '' ? null : Number(value)
}

function setCentralTop1(event: Event): void {
  centralForm.value.min_top1_similarity = parseOptionalNumber(event)
}

function setCentralMargin(event: Event): void {
  centralForm.value.min_top1_top2_margin = parseOptionalNumber(event)
}

function setEdgeTop1(event: Event): void {
  edgeForm.value.min_top1_similarity = parseOptionalNumber(event)
}

function setEdgeMargin(event: Event): void {
  edgeForm.value.min_top1_top2_margin = parseOptionalNumber(event)
}

function statusLabel(status: boolean | null): string {
  if (status === null) return 'Belum diketahui'
  return status ? 'Siap' : 'Belum siap'
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

function configStatusLabel(status: Device['config_apply_status']): string {
  switch (status) {
    case 'not_configured':
      return 'Belum diatur'
    case 'pending':
      return 'Menunggu perangkat tersinkron'
    case 'applied':
      return 'Sudah diterapkan'
    case 'error':
      return 'Gagal diterapkan'
  }
}

onMounted(() => {
  void refreshReadiness(true)
  refreshTimer = setInterval(() => void refreshReadiness(), 30_000)
})

onBeforeUnmount(() => {
  if (refreshTimer) clearInterval(refreshTimer)
})
</script>

<template>
  <section class="ai-setup-view" aria-label="Kesiapan AI dan pengaturan kamera">
    <PageHeader
      eyebrow="Administrasi sistem"
      title="AI & kamera"
      description="Pantau kesiapan dan atur kualitas enrollment serta konfigurasi untuk profile server yang aktif."
    >
      <template #actions>
        <button
          class="button button--secondary"
          type="button"
          :disabled="isLoading"
          @click="refreshReadiness(true)"
        >
          {{ isLoading ? 'Memuat…' : 'Muat ulang' }}
        </button>
      </template>
    </PageHeader>

    <p v-if="errorMessage" class="master-data__alert" role="alert">{{ errorMessage }}</p>
    <p v-if="successMessage" class="ai-setup-view__success" role="status">
      {{ successMessage }}
    </p>

    <template v-if="readiness">
      <section class="ai-setup-view__profile master-data__panel">
        <div>
          <p class="master-data__eyebrow">Profile server</p>
          <h2>{{ profileLabel(readiness.deployment_profile) }}</h2>
          <p>
            Model YuNet/SFace tetap dipasang dan diverifikasi pada host inference. Pengaturan di
            halaman ini tidak mengganti file model atau kamera fisik.
          </p>
        </div>
        <RouterLink class="button button--secondary" to="/app/devices">Lihat perangkat</RouterLink>
      </section>

      <div class="ai-setup-view__grid">
        <article class="ai-setup-view__card">
          <p class="master-data__eyebrow">Model enrollment</p>
          <h2>{{ readiness.enrollment_models_ready ? 'Tersedia' : 'Belum tersedia' }}</h2>
          <p>Model lokal Core API memproses capture sementara; gambar tidak disimpan.</p>
          <span
            class="ai-setup-view__badge"
            :class="readiness.enrollment_models_ready ? 'is-ready' : 'is-pending'"
          >
            {{ statusLabel(readiness.enrollment_models_ready) }}
          </span>
        </article>
        <article v-if="readiness.deployment_profile === 'AI_CENTRAL'" class="ai-setup-view__card">
          <p class="master-data__eyebrow">AI Central</p>
          <h2>{{ serviceLabel(readiness.central_ai_status) }}</h2>
          <dl class="ai-setup-view__checks">
            <div>
              <dt>Versi model</dt>
              <dd>{{ readiness.central_ai_model_version ?? '—' }}</dd>
            </div>
            <div>
              <dt>Threshold tersedia</dt>
              <dd>{{ statusLabel(readiness.central_ai_thresholds_configured) }}</dd>
            </div>
            <div>
              <dt>Konfigurasi diterapkan</dt>
              <dd>
                {{ readiness.central_ai_config_applied_revision ?? 'Belum diketahui' }} /
                {{ readiness.central_ai_config_desired_revision ?? '—' }}
              </dd>
            </div>
          </dl>
        </article>
      </div>

      <nav class="ai-setup-view__tabs" aria-label="Kelompok pengaturan">
        <button
          v-for="tab in settingsTabs"
          :key="tab.id"
          class="button"
          :class="activeTab === tab.id ? 'button--primary' : 'button--secondary'"
          type="button"
          @click="activeTab = tab.id"
        >
          {{ tab.label }}
        </button>
      </nav>

      <section v-if="activeTab === 'enrollment'" class="master-data__panel ai-setup-view__settings">
        <div class="master-data__panel-heading">
          <div>
            <p class="master-data__eyebrow">
              Core API · revisi {{ readiness.enrollment_quality_revision }}
            </p>
            <h2>
              {{
                readiness.deployment_profile === 'AI_EDGE' &&
                selectedDevice?.deployment_profile === 'AI_EDGE'
                  ? 'Kualitas capture bersama'
                  : 'Kualitas capture pendaftaran'
              }}
            </h2>
          </div>
        </div>
        <p class="ai-setup-view__note">
          <template
            v-if="
              readiness.deployment_profile === 'AI_EDGE' &&
              selectedDevice?.deployment_profile === 'AI_EDGE'
            "
          >
            Nilai ini memeriksa ukuran wajah, ketajaman, dan pencahayaan pada pendaftaran serta PC
            AI_EDGE terpilih. Keduanya memakai angka yang sama.
          </template>
          <template v-else-if="readiness.deployment_profile === 'AI_EDGE'">
            Nilai ini dipakai bersama untuk kualitas capture pendaftaran dan presensi AI_EDGE. Atur
            kualitas hanya di sini; tidak ada pengaturan kualitas kedua pada perangkat.
          </template>
          <template v-else>
            Nilai ini memeriksa ukuran wajah, ketajaman, dan pencahayaan pada setiap capture
            pendaftaran. Mulai dari default yang ada; sesuaikan jika capture yang baik sering
            ditolak. Filter ringan STB diatur terpisah pada tab STB gateway.
          </template>
        </p>
        <form class="master-data__form ai-setup-view__form" @submit.prevent="saveEnrollment">
          <label>
            Ukuran wajah minimum (piksel)
            <input
              v-model.number="enrollmentForm.min_face_pixels"
              type="number"
              min="16"
              max="2048"
              required
            />
          </label>
          <label>
            Ketajaman minimum
            <input
              v-model.number="enrollmentForm.min_sharpness"
              type="number"
              min="0"
              max="100000"
              step="any"
              required
            />
          </label>
          <label>
            Kecerahan minimum
            <input
              v-model.number="enrollmentForm.min_brightness"
              type="number"
              min="0"
              max="254"
              step="any"
              required
            />
          </label>
          <label>
            Kecerahan maksimum
            <input
              v-model.number="enrollmentForm.max_brightness"
              type="number"
              min="1"
              max="255"
              step="any"
              required
            />
          </label>
          <div class="master-data__form-actions">
            <button class="button button--primary" type="submit" :disabled="isSaving">
              {{ isSaving ? 'Menyimpan…' : 'Simpan kualitas capture' }}
            </button>
          </div>
        </form>
      </section>

      <section
        v-else-if="activeTab === 'devices'"
        class="master-data__panel ai-setup-view__settings"
      >
        <div class="master-data__panel-heading">
          <div>
            <p class="master-data__eyebrow">Konfigurasi jarak jauh</p>
            <h2>
              {{
                readiness.deployment_profile === 'AI_EDGE'
                  ? 'Perangkat AI_EDGE'
                  : 'Perangkat STB_GATEWAY'
              }}
            </h2>
          </div>
        </div>
        <p class="ai-setup-view__note">
          <template v-if="readiness.deployment_profile === 'AI_EDGE'">
            Pilih PC AI_EDGE untuk mengatur threshold pengenalan dan sampling. Kualitas capture
            bersama diatur satu kali pada tab Kualitas capture. Kamera, resolusi, dan FPS diatur di
            host kamera.
          </template>
          <template v-else>
            Pilih STB gateway untuk mengatur burst dan filter capture. Kamera, resolusi, dan FPS
            diatur di host gateway.
          </template>
        </p>
        <label class="ai-setup-view__device-picker">
          Perangkat
          <select v-model="selectedDeviceId" @change="loadDeviceConfiguration(selectedDeviceId)">
            <option value="">Pilih perangkat aktif</option>
            <option v-for="device in devices" :key="device.device_id" :value="device.device_id">
              {{ device.name }} · {{ device.deployment_profile }}
            </option>
          </select>
        </label>

        <template v-if="selectedDevice?.deployment_profile === 'AI_EDGE'">
          <h3>AI_EDGE · kebijakan pengenalan</h3>
          <form class="master-data__form ai-setup-view__form" @submit.prevent="saveDevice">
            <label
              >Top-1 similarity<input
                :value="edgeForm.min_top1_similarity ?? ''"
                type="number"
                min="-1"
                max="1"
                step="any"
                :required="edgeForm.min_top1_top2_margin !== null"
                @input="setEdgeTop1"
            /></label>
            <label
              >Margin Top-1 − Top-2<input
                :value="edgeForm.min_top1_top2_margin ?? ''"
                type="number"
                min="0"
                max="2"
                step="any"
                :required="edgeForm.min_top1_similarity !== null"
                @input="setEdgeMargin"
            /></label>
            <label
              >Frame yang harus sepakat<input
                v-model.number="edgeForm.minimum_agreeing_frames"
                type="number"
                min="1"
                max="10"
                required
            /></label>
            <label
              >Sampling setiap N frame<input
                v-model.number="edgeForm.sample_every_n_frames"
                type="number"
                min="1"
                max="60"
                required
            /></label>
            <label
              >Frame terbaik<input
                v-model.number="edgeForm.best_frame_count"
                type="number"
                min="1"
                max="20"
                required
            /></label>
            <label
              >Riwayat maksimum<input
                v-model.number="edgeForm.max_history_frames"
                type="number"
                min="1"
                max="60"
                required
            /></label>
            <label class="ai-setup-view__form-wide"
              >Referensi laporan kalibrasi<input
                v-model="edgeForm.calibration_reference"
                type="text"
                maxlength="200"
                :required="edgeThresholdsConfigured"
                placeholder="ID/nama laporan kalibrasi yang disetujui"
            /></label>
            <div class="master-data__form-actions ai-setup-view__form-wide">
              <button class="button button--primary" type="submit" :disabled="isSaving">
                {{ isSaving ? 'Menyimpan…' : 'Terapkan ke perangkat' }}
              </button>
            </div>
          </form>
          <aside class="ai-setup-view__preview" aria-label="Pratinjau konfigurasi AI_EDGE">
            <h3>Pratinjau konfigurasi</h3>
            <dl>
              <div>
                <dt>Proses pengenalan</dt>
                <dd>PC kamera AI_EDGE</dd>
              </div>
              <div>
                <dt>Sampling</dt>
                <dd>
                  {{ edgeForm.minimum_agreeing_frames }} frame sepakat · setiap
                  {{ edgeForm.sample_every_n_frames }} frame · pilih
                  {{ edgeForm.best_frame_count }} terbaik
                </dd>
              </div>
              <div>
                <dt>Identifikasi</dt>
                <dd>
                  {{
                    edgeThresholdsConfigured
                      ? 'Threshold terisi'
                      : 'Belum aktif — menunggu kalibrasi'
                  }}
                </dd>
              </div>
            </dl>
            <p v-if="!edgeThresholdsConfigured" role="status">
              Nilai quality dan sampling bisa diterapkan sekarang. Agent baru mengidentifikasi siswa
              setelah Top-1 dan margin diisi dari laporan kalibrasi.
            </p>
          </aside>
        </template>

        <template v-else-if="selectedDevice?.deployment_profile === 'STB_GATEWAY'">
          <h3>STB_GATEWAY · capture dan burst</h3>
          <form class="master-data__form ai-setup-view__form" @submit.prevent="saveDevice">
            <label
              >Ambang gerakan<input
                v-model.number="gatewayForm.motion_threshold"
                type="number"
                min="0"
                max="255"
                step="any"
                required
            /></label>
            <label
              >Sampling periodik (detik)<input
                v-model.number="gatewayForm.periodic_burst_seconds"
                type="number"
                min="0.01"
                max="3600"
                step="any"
                required
            /></label>
            <label
              >Jeda minimum burst (detik)<input
                v-model.number="gatewayForm.minimum_burst_interval_seconds"
                type="number"
                min="0.01"
                max="3600"
                step="any"
                required
            /></label>
            <label
              >Jumlah frame per burst<input
                v-model.number="gatewayForm.burst_frame_count"
                type="number"
                min="1"
                max="5"
                required
            /></label>
            <label
              >Jeda antar-frame (detik)<input
                v-model.number="gatewayForm.burst_frame_interval_seconds"
                type="number"
                min="0"
                max="10"
                step="any"
                required
            /></label>
            <label
              >Kualitas JPEG<input
                v-model.number="gatewayForm.jpeg_quality"
                type="number"
                min="20"
                max="100"
                required
            /></label>
            <label
              >Kecerahan minimum<input
                v-model.number="gatewayForm.min_brightness"
                type="number"
                min="0"
                max="254"
                step="any"
                required
            /></label>
            <label
              >Kecerahan maksimum<input
                v-model.number="gatewayForm.max_brightness"
                type="number"
                min="1"
                max="255"
                step="any"
                required
            /></label>
            <label
              >Ketajaman minimum<input
                v-model.number="gatewayForm.min_sharpness"
                type="number"
                min="0"
                max="100000"
                step="any"
                required
            /></label>
            <div class="master-data__form-actions ai-setup-view__form-wide">
              <button class="button button--primary" type="submit" :disabled="isSaving">
                {{ isSaving ? 'Menyimpan…' : 'Terapkan ke gateway' }}
              </button>
            </div>
          </form>
        </template>
        <p v-else class="master-data__empty">
          Belum ada perangkat aktif
          {{ readiness.deployment_profile === 'AI_EDGE' ? 'AI_EDGE' : 'STB_GATEWAY' }}.
        </p>

        <div v-if="deviceConfiguration" class="ai-setup-view__apply-state" role="status">
          <strong>{{ configStatusLabel(deviceConfiguration.apply_status) }}</strong>
          <span
            >Diminta: revisi {{ deviceConfiguration.revision }} · diterapkan: revisi
            {{ deviceConfiguration.applied_revision }}</span
          >
          <code v-if="deviceConfiguration.error_code">{{ deviceConfiguration.error_code }}</code>
        </div>

        <div v-if="devices.length" class="ai-setup-view__device-status">
          <h3>Status sinkronisasi</h3>
          <div v-for="device in devices" :key="device.device_id" class="ai-setup-view__device-row">
            <span
              ><strong>{{ device.name }}</strong
              ><small>{{ device.deployment_profile }}</small></span
            >
            <span>{{ configStatusLabel(device.config_apply_status) }}</span>
            <code v-if="device.config_error_code">{{ device.config_error_code }}</code>
          </div>
        </div>
        <p v-else class="master-data__empty">Belum ada status perangkat aktif untuk profile ini.</p>
      </section>

      <section
        v-else-if="activeTab === 'central' && readiness.deployment_profile === 'AI_CENTRAL'"
        class="master-data__panel ai-setup-view__settings"
      >
        <div class="master-data__panel-heading">
          <div>
            <p class="master-data__eyebrow">
              AI Central · revisi {{ readiness.central_ai_config_desired_revision ?? 0 }}
            </p>
            <h2>Kualitas frame dan threshold identitas</h2>
          </div>
        </div>
        <p class="ai-setup-view__note">
          Threshold harus diambil dari laporan kalibrasi lokal. Jika keduanya kosong, service tetap
          degraded dan tidak menjalankan pengenalan otomatis. Saat disimpan, AI Central mengambil
          konfigurasi terbaru tanpa mengubah file model.
        </p>
        <form class="master-data__form ai-setup-view__form" @submit.prevent="saveCentral">
          <label
            >Ukuran wajah minimum<input
              v-model.number="centralForm.min_face_pixels"
              type="number"
              min="16"
              max="2048"
              required
          /></label>
          <label
            >Ketajaman minimum<input
              v-model.number="centralForm.min_laplacian_variance"
              type="number"
              min="0"
              max="100000"
              step="any"
              required
          /></label>
          <label
            >Kecerahan minimum<input
              v-model.number="centralForm.min_brightness"
              type="number"
              min="0"
              max="254"
              step="any"
              required
          /></label>
          <label
            >Kecerahan maksimum<input
              v-model.number="centralForm.max_brightness"
              type="number"
              min="1"
              max="255"
              step="any"
              required
          /></label>
          <label
            >Top-1 similarity<input
              :value="centralForm.min_top1_similarity ?? ''"
              type="number"
              min="-1"
              max="1"
              step="any"
              @input="setCentralTop1"
          /></label>
          <label
            >Margin Top-1 − Top-2<input
              :value="centralForm.min_top1_top2_margin ?? ''"
              type="number"
              min="0"
              max="2"
              step="any"
              @input="setCentralMargin"
          /></label>
          <label
            >Frame yang harus sepakat<input
              v-model.number="centralForm.minimum_agreeing_frames"
              type="number"
              min="1"
              max="10"
              required
          /></label>
          <label
            >Sampling setiap N frame<input
              v-model.number="centralForm.sample_every_n_frames"
              type="number"
              min="1"
              max="60"
              required
          /></label>
          <label
            >Frame terbaik<input
              v-model.number="centralForm.best_frame_count"
              type="number"
              min="1"
              max="20"
              required
          /></label>
          <label
            >Riwayat maksimum<input
              v-model.number="centralForm.max_history_frames"
              type="number"
              min="1"
              max="60"
              required
          /></label>
          <label class="ai-setup-view__form-wide"
            >Referensi laporan kalibrasi<input
              v-model="centralForm.calibration_reference"
              type="text"
              maxlength="200"
              placeholder="Wajib diisi bila threshold diatur"
          /></label>
          <div class="master-data__form-actions ai-setup-view__form-wide">
            <button class="button button--primary" type="submit" :disabled="isSaving">
              {{ isSaving ? 'Menyimpan…' : 'Simpan dan terapkan' }}
            </button>
          </div>
        </form>
        <p class="ai-setup-view__note">
          Versi model dan path file tetap dikelola saat provisioning server; threshold similarity
          tidak dapat mengubah atau mengunduh model.
        </p>
      </section>

      <section class="master-data__panel ai-setup-view__devices">
        <div class="master-data__panel-heading">
          <div>
            <p class="master-data__eyebrow">Kamera presensi</p>
            <h2>Status perangkat terdaftar</h2>
          </div>
          <RouterLink class="button button--text" to="/app/devices">Kelola perangkat</RouterLink>
        </div>
        <div class="master-data__table-wrap">
          <table class="master-data__table">
            <thead>
              <tr>
                <th>Perangkat / lab</th>
                <th>Profile</th>
                <th>Model dilaporkan</th>
                <th>Kamera</th>
                <th>Koneksi</th>
                <th>Konfigurasi</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="devices.length === 0">
                <td colspan="6" class="master-data__empty">Belum ada perangkat.</td>
              </tr>
              <tr v-for="device in devices" :key="device.device_id">
                <td data-label="Perangkat / lab">
                  <strong>{{ device.name }}</strong
                  ><small>{{ device.laboratory_code }} · {{ device.laboratory_name }}</small>
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
                <td data-label="Konfigurasi">
                  {{ configStatusLabel(device.config_apply_status) }} ·
                  {{ device.config_applied_revision }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </template>
  </section>
</template>
