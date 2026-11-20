<script setup lang="ts">
import { shouldPausePolling } from '../utils/visibility'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { UiButton, UiInput, UiModal, UiPageHeader, UiSelect } from '../components/ui'
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
import {
  factorySafeThresholds,
  formatThresholdText,
  isFactoryDefaultReference,
  numeric,
  parseThresholdText,
  recognitionDefaults,
  recognitionFrom,
  sanitizeRecognitionForm,
  type UnknownSettings,
} from '../utils/recognitionConfig'
import { centralSyncStatusLabel } from '../utils/configStatus'
import { deviceHealthLabel } from '../utils/attendanceStatus'
import { createRefreshEpoch } from '../utils/refresh'

type SettingsTab = 'enrollment' | 'devices' | 'central'
const readiness = ref<AiReadiness | null>(null)
const devices = ref<Device[]>([])
const selectedDeviceId = ref('')
const deviceConfiguration = ref<DeviceRuntimeConfiguration | null>(null)
const isLoading = ref(false)
const isSaving = ref(false)
const errorMessage = ref<string | null>(null)
const successMessage = ref<string | null>(null)
const activeTab = ref<SettingsTab>('enrollment')
const activeConfigModal = ref<'quality' | 'edge' | null>(null)
const presetMessage = ref<string | null>(null)
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

// Teks mentah input threshold: v-model string agar ketikan tidak hilang saat
// komponen me-render ulang (:value satu arah + parse number menimpa DOM).
// Nilai angka resmi tetap di centralForm/edgeForm dan diisi saat simpan.
const centralTop1Text = ref('')
const centralMarginText = ref('')
const edgeTop1Text = ref('')
const edgeMarginText = ref('')

function syncThresholdTexts(): void {
  centralTop1Text.value = formatThresholdText(centralForm.value.min_top1_similarity)
  centralMarginText.value = formatThresholdText(centralForm.value.min_top1_top2_margin)
  edgeTop1Text.value = formatThresholdText(edgeForm.value.min_top1_similarity)
  edgeMarginText.value = formatThresholdText(edgeForm.value.min_top1_top2_margin)
}

const selectedDevice = computed(
  () => devices.value.find((device) => device.device_id === selectedDeviceId.value) ?? null,
)
const edgeThresholdsConfigured = computed(
  () => edgeTop1Text.value !== '' && edgeMarginText.value !== '',
)
const centralUsesFactoryDefaults = computed(() =>
  isFactoryDefaultReference(centralForm.value.calibration_reference),
)
const edgeUsesFactoryDefaults = computed(() =>
  isFactoryDefaultReference(edgeForm.value.calibration_reference),
)

function applyFactoryDefaults(): void {
  const safe = factorySafeThresholds()
  centralForm.value = { ...centralForm.value, ...safe }
  edgeForm.value = { ...edgeForm.value, ...safe }
  syncThresholdTexts()
  const message =
    'Preset uji lokal terisi. Tinjau nilainya, lalu terapkan ke perangkat untuk pengujian terawasi.'
  if (activeConfigModal.value === 'edge') {
    presetMessage.value = message
    successMessage.value = null
  } else {
    successMessage.value = message
  }
}

function openConfigModal(modal: 'quality' | 'edge'): void {
  activeConfigModal.value = modal
  errorMessage.value = null
  successMessage.value = null
  presetMessage.value = null
}

function closeConfigModal(): void {
  if (isSaving.value) return
  activeConfigModal.value = null
  presetMessage.value = null
}

async function selectDevice(deviceId: string): Promise<void> {
  selectedDeviceId.value = deviceId
  deviceConfiguration.value = null
  await loadDeviceConfiguration(deviceId)
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

const readinessEpoch = createRefreshEpoch()

async function refreshReadiness(forceSettings = false): Promise<void> {
  const epoch = readinessEpoch.next()
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
    if (!readinessEpoch.isCurrent(epoch)) return
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
      syncThresholdTexts()
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
    if (readinessEpoch.isCurrent(epoch)) {
      errorMessage.value =
        error instanceof ApiError ? error.message : 'Status dan konfigurasi AI tidak dapat dimuat.'
    }
  } finally {
    if (readinessEpoch.isCurrent(epoch)) isLoading.value = false
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
      syncThresholdTexts()
    } else {
      gatewayForm.value = gatewayFrom(result.settings as UnknownSettings)
    }
  } catch (error) {
    errorMessage.value =
      error instanceof ApiError ? error.message : 'Konfigurasi perangkat tidak dapat dimuat.'
  }
}

async function saveEnrollment(): Promise<void> {
  // Sinkronkan ketikan threshold edge sebelum ikut tersimpan bersama kualitas enrollment.
  edgeForm.value.min_top1_similarity = parseThresholdText(edgeTop1Text.value)
  edgeForm.value.min_top1_top2_margin = parseThresholdText(edgeMarginText.value)
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
  if (successMessage.value) closeConfigModal()
}

async function saveCentral(): Promise<void> {
  centralForm.value.min_top1_similarity = parseThresholdText(centralTop1Text.value)
  centralForm.value.min_top1_top2_margin = parseThresholdText(centralMarginText.value)
  const invalid = sanitizeRecognitionForm(centralForm.value)
  if (invalid) {
    errorMessage.value = invalid
    return
  }
  await saveSettings(async () => {
    await saveCentralRecognitionConfiguration(centralForm.value)
    await refreshReadiness()
  }, 'Pengaturan AI Central diterbitkan. Service akan mengambilnya otomatis.')
}

async function saveDevice(): Promise<void> {
  if (!selectedDevice.value) return
  if (selectedDevice.value.deployment_profile === 'AI_EDGE') {
    edgeForm.value.min_top1_similarity = parseThresholdText(edgeTop1Text.value)
    edgeForm.value.min_top1_top2_margin = parseThresholdText(edgeMarginText.value)
    const invalid = sanitizeRecognitionForm(edgeForm.value)
    if (invalid) {
      errorMessage.value = invalid
      return
    }
  }
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
  if (successMessage.value) closeConfigModal()
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

function statusLabel(status: boolean | null): string {
  if (status === null) return 'Belum diketahui'
  return status ? 'Siap' : 'Belum siap'
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
  refreshTimer = setInterval(() => {
    if (shouldPausePolling()) return
    void refreshReadiness()
  }, 30_000)
})

onBeforeUnmount(() => {
  if (refreshTimer) clearInterval(refreshTimer)
})
</script>

<template>
  <div class="st-page" aria-label="Kesiapan AI dan pengaturan kamera">
    <UiPageHeader
      eyebrow="Infrastruktur · konfigurasi AI"
      title="Konfigurasi AI"
      description="Atur kualitas kamera dan pengenalan, lalu pantau apakah pengaturan sudah diterapkan."
    >
      <template #actions>
        <UiButton
          variant="secondary"
          type="button"
          :disabled="isLoading"
          @click="refreshReadiness(true)"
        >
          {{ isLoading ? 'Memuat…' : 'Muat ulang' }}
        </UiButton>
      </template>
    </UiPageHeader>

    <p v-if="errorMessage && !activeConfigModal" class="st-alert st-alert--error" role="alert">
      {{ errorMessage }}
    </p>
    <p v-if="successMessage && !activeConfigModal" class="ai-setup-view__success" role="status">
      {{ successMessage }}
    </p>

    <template v-if="readiness">
      <div v-if="readiness.deployment_profile === 'AI_CENTRAL'" class="ai-setup-view__grid">
        <article class="ai-setup-view__card">
          <p class="master-data__eyebrow">AI Central</p>
          <h2>{{ serviceLabel(readiness.central_ai_status) }}</h2>
          <dl class="ai-setup-view__checks">
            <div>
              <dt>Versi model</dt>
              <dd>{{ readiness.central_ai_model_version ?? '-' }}</dd>
            </div>
            <div>
              <dt>Threshold tersedia</dt>
              <dd>{{ statusLabel(readiness.central_ai_thresholds_configured) }}</dd>
            </div>
            <div>
              <dt>Konfigurasi diterapkan</dt>
              <dd>
                {{ readiness.central_ai_config_applied_revision ?? 'Belum diketahui' }} /
                {{ readiness.central_ai_config_desired_revision ?? '-' }}
              </dd>
            </div>
            <div>
              <dt>Status sinkron</dt>
              <dd>
                {{ centralSyncStatusLabel(readiness.central_ai_config_sync_status) }}
                <code v-if="readiness.central_ai_config_sync_error_code">{{
                  readiness.central_ai_config_sync_error_code
                }}</code>
              </dd>
            </div>
          </dl>
        </article>
      </div>

      <template v-if="readiness.deployment_profile === 'AI_EDGE'">
        <div class="ai-setup-view__edge-cards">
          <article class="master-data__panel ai-setup-view__edge-card">
            <div class="master-data__panel-heading">
              <div>
                <p class="master-data__eyebrow">
                  Core API · revisi {{ readiness.enrollment_quality_revision }}
                </p>
                <h2>Kualitas kamera</h2>
              </div>
            </div>
            <p class="ai-setup-view__card-copy">
              Dipakai bersama saat pendaftaran wajah dan presensi AI_EDGE.
            </p>
            <dl class="ai-setup-view__checks">
              <div>
                <dt>Ukuran wajah minimum</dt>
                <dd>{{ enrollmentForm.min_face_pixels }} px</dd>
              </div>
              <div>
                <dt>Ketajaman minimum</dt>
                <dd>{{ enrollmentForm.min_sharpness }}</dd>
              </div>
              <div>
                <dt>Rentang pencahayaan</dt>
                <dd>{{ enrollmentForm.min_brightness }}–{{ enrollmentForm.max_brightness }}</dd>
              </div>
            </dl>
            <div class="ai-setup-view__edge-card-actions">
              <UiButton
                variant="outlined"
                type="button"
                data-testid="edit-capture-quality"
                @click="openConfigModal('quality')"
              >
                Konfigurasi
              </UiButton>
            </div>
          </article>

          <article class="master-data__panel ai-setup-view__edge-card">
            <div class="master-data__panel-heading">
              <div>
                <p class="master-data__eyebrow">Konfigurasi jarak jauh</p>
                <h2>Pengenalan AI_EDGE</h2>
              </div>
            </div>
            <label class="ai-setup-view__device-picker">
              PC kamera
              <UiSelect
                :model-value="selectedDeviceId"
                aria-label="Pilih perangkat AI_EDGE"
                @update:model-value="selectDevice"
              >
                <option value="">Pilih perangkat aktif</option>
                <option v-for="device in devices" :key="device.device_id" :value="device.device_id">
                  {{ device.name }}
                </option>
              </UiSelect>
            </label>

            <template v-if="selectedDevice?.deployment_profile === 'AI_EDGE'">
              <aside class="ai-setup-view__preview" aria-label="Pratinjau konfigurasi AI_EDGE">
                <div class="ai-setup-view__preview-heading">
                  <h3>Ringkasan konfigurasi</h3>
                  <span
                    class="ai-setup-view__state"
                    :class="edgeThresholdsConfigured ? 'is-ready' : 'is-pending'"
                  >
                    {{
                      edgeUsesFactoryDefaults
                        ? 'Mode uji'
                        : edgeThresholdsConfigured
                          ? 'Ambang diatur'
                          : 'Belum diatur'
                    }}
                  </span>
                </div>
                <dl>
                  <div>
                    <dt>Identitas siswa</dt>
                    <dd>
                      {{
                        edgeThresholdsConfigured ? 'Ambang pengenalan diisi' : 'Menunggu pengaturan'
                      }}
                    </dd>
                  </div>
                  <div>
                    <dt>Sampling</dt>
                    <dd>
                      {{ edgeForm.minimum_agreeing_frames }} frame konsisten · periksa tiap
                      {{ edgeForm.sample_every_n_frames }} frame · gunakan
                      {{ edgeForm.best_frame_count }} terbaik
                    </dd>
                  </div>
                </dl>
                <p v-if="edgeUsesFactoryDefaults" role="status">
                  Preset hanya untuk uji terawasi. Pastikan ada sesi aktif dan roster siswa untuk
                  menguji identitas.
                </p>
                <p v-else-if="!edgeThresholdsConfigured" role="status">
                  Identifikasi belum aktif. Isi threshold dan referensi kalibrasi untuk mengujinya.
                </p>
              </aside>
              <div v-if="deviceConfiguration" class="ai-setup-view__apply-state" role="status">
                <strong>{{ configStatusLabel(deviceConfiguration.apply_status) }}</strong>
                <span>
                  Revisi {{ deviceConfiguration.revision }} · diterapkan
                  {{ deviceConfiguration.applied_revision }}
                </span>
              </div>
            </template>
            <p v-else class="master-data__empty">
              {{
                devices.length
                  ? 'Pilih PC kamera untuk melihat ringkasan konfigurasinya.'
                  : 'Belum ada PC AI_EDGE aktif.'
              }}
            </p>

            <div class="ai-setup-view__edge-card-actions">
              <UiButton
                variant="outlined"
                type="button"
                :disabled="!selectedDevice || isLoading"
                data-testid="edit-edge-recognition"
                @click="openConfigModal('edge')"
              >
                Konfigurasi
              </UiButton>
            </div>
          </article>
        </div>

        <UiModal
          v-if="activeConfigModal === 'quality'"
          title="Konfigurasi kualitas kamera"
          wide
          @close="closeConfigModal"
        >
          <p class="ai-setup-view__note">
            Nilai ini berlaku untuk pendaftaran wajah dan PC AI_EDGE terpilih. Sesuaikan berdasarkan
            hasil pengukuran kamera, bukan untuk menggantikan fokus atau pencahayaan yang buruk.
          </p>
          <p v-if="errorMessage" class="st-alert st-alert--error" role="alert">
            {{ errorMessage }}
          </p>
          <p v-if="successMessage" class="ai-setup-view__success" role="status">
            {{ successMessage }}
          </p>
          <form
            id="capture-quality-form"
            class="master-data__form ai-setup-view__form"
            @submit.prevent="saveEnrollment"
          >
            <label>
              Ukuran wajah minimum (piksel)
              <UiInput
                v-model.number="enrollmentForm.min_face_pixels"
                type="number"
                min="16"
                max="2048"
                required
              />
            </label>
            <label>
              Ketajaman minimum
              <UiInput
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
              <UiInput
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
              <UiInput
                v-model.number="enrollmentForm.max_brightness"
                type="number"
                min="1"
                max="255"
                step="any"
                required
              />
            </label>
          </form>
          <template #footer>
            <UiButton variant="secondary" :disabled="isSaving" @click="closeConfigModal">
              Batal
            </UiButton>
            <UiButton
              variant="primary"
              type="submit"
              form="capture-quality-form"
              :disabled="isSaving"
            >
              {{ isSaving ? 'Menyimpan…' : 'Simpan kualitas' }}
            </UiButton>
          </template>
        </UiModal>

        <UiModal
          v-if="activeConfigModal === 'edge' && selectedDevice?.deployment_profile === 'AI_EDGE'"
          title="Konfigurasi pengenalan AI_EDGE"
          wide
          @close="closeConfigModal"
        >
          <p class="ai-setup-view__note">
            {{ selectedDevice.name }} · preset uji bukan hasil kalibrasi. Kamera, resolusi, dan FPS
            tetap diatur di PC kamera.
          </p>
          <p v-if="errorMessage" class="st-alert st-alert--error" role="alert">
            {{ errorMessage }}
          </p>
          <p v-if="presetMessage" class="ai-setup-view__success" role="status">
            {{ presetMessage }}
          </p>
          <form
            id="edge-recognition-form"
            class="master-data__form ai-setup-view__form"
            @submit.prevent="saveDevice"
          >
            <label class="ai-setup-view__field">
              Top-1 similarity
              <UiInput
                id="edge-top1-threshold"
                v-model="edgeTop1Text"
                aria-describedby="edge-top1-hint"
                type="number"
                min="-1"
                max="1"
                step="any"
                :required="edgeMarginText !== ''"
              />
              <small id="edge-top1-hint" class="ai-setup-view__field-hint">
                Skor kandidat terbaik; makin tinggi makin ketat. Nilai awal uji: 0,65.
              </small>
            </label>
            <label class="ai-setup-view__field">
              Margin Top-1 − Top-2
              <UiInput
                id="edge-margin-threshold"
                v-model="edgeMarginText"
                aria-describedby="edge-margin-hint"
                type="number"
                min="0"
                max="2"
                step="any"
                :required="edgeTop1Text !== ''"
              />
              <small id="edge-margin-hint" class="ai-setup-view__field-hint">
                Jarak kandidat pertama dan kedua; nilai awal uji: 0,20.
              </small>
            </label>
            <label class="ai-setup-view__field">
              YuNet score threshold
              <UiInput
                id="edge-yunet-score"
                v-model.number="edgeForm.yunet_score_threshold"
                aria-describedby="edge-yunet-score-hint"
                type="number"
                min="0"
                max="1"
                step="any"
                required
              />
              <small id="edge-yunet-score-hint" class="ai-setup-view__field-hint">
                Ambang deteksi wajah, bukan identitas. Nilai awal: 0,90.
              </small>
            </label>
            <label class="ai-setup-view__field">
              YuNet NMS threshold
              <UiInput
                id="edge-yunet-nms"
                v-model.number="edgeForm.yunet_nms_threshold"
                aria-describedby="edge-yunet-nms-hint"
                type="number"
                min="0"
                max="1"
                step="any"
                required
              />
              <small id="edge-yunet-nms-hint" class="ai-setup-view__field-hint">
                Penekanan kotak deteksi yang bertumpuk; nilai awal: 0,30.
              </small>
            </label>
            <label class="ai-setup-view__field">
              Frame yang harus sepakat
              <UiInput
                id="edge-agreeing-frames"
                v-model.number="edgeForm.minimum_agreeing_frames"
                aria-describedby="edge-agreeing-frames-hint"
                type="number"
                min="1"
                max="10"
                required
              />
              <small id="edge-agreeing-frames-hint" class="ai-setup-view__field-hint">
                Jumlah hasil identitas konsisten; nilai awal: 3.
              </small>
            </label>
            <label class="ai-setup-view__field">
              Sampling setiap N frame
              <UiInput
                id="edge-sample-every"
                v-model.number="edgeForm.sample_every_n_frames"
                aria-describedby="edge-sample-every-hint"
                type="number"
                min="1"
                max="60"
                required
              />
              <small id="edge-sample-every-hint" class="ai-setup-view__field-hint">
                Frekuensi pemeriksaan AI; bukan FPS kamera. Nilai awal: 5.
              </small>
            </label>
            <label class="ai-setup-view__field">
              Frame terbaik
              <UiInput
                id="edge-best-frame-count"
                v-model.number="edgeForm.best_frame_count"
                aria-describedby="edge-best-frame-count-hint"
                type="number"
                min="1"
                max="20"
                required
              />
              <small id="edge-best-frame-count-hint" class="ai-setup-view__field-hint">
                Bukti terbaik yang dipakai; minimal sama dengan frame sepakat. Nilai awal: 5.
              </small>
            </label>
            <label class="ai-setup-view__field">
              Riwayat maksimum
              <UiInput
                id="edge-max-history"
                v-model.number="edgeForm.max_history_frames"
                aria-describedby="edge-max-history-hint"
                type="number"
                min="1"
                max="60"
                required
              />
              <small id="edge-max-history-hint" class="ai-setup-view__field-hint">
                Batas bukti wajah terlacak; minimal sama dengan frame terbaik. Nilai awal: 10.
              </small>
            </label>
            <label class="ai-setup-view__form-wide ai-setup-view__field">
              Referensi laporan kalibrasi
              <UiInput
                id="edge-calibration-reference"
                v-model="edgeForm.calibration_reference"
                aria-describedby="edge-calibration-reference-hint"
                type="text"
                maxlength="200"
                :required="edgeThresholdsConfigured"
                placeholder="ID laporan lokal; preset mengisi label sementara"
              />
              <small id="edge-calibration-reference-hint" class="ai-setup-view__field-hint">
                Ganti label preset dengan ID laporan setelah kalibrasi lokal.
              </small>
            </label>
            <p v-if="edgeUsesFactoryDefaults" class="ai-setup-view__note" role="status">
              Preset sementara aktif. Hasil ambigu tetap perlu verifikasi petugas; kalibrasi lokal
              wajib sebelum penggunaan operasional.
            </p>
          </form>
          <template #footer>
            <UiButton
              variant="outlined"
              type="button"
              :disabled="isSaving"
              data-testid="edge-default-preset"
              @click="applyFactoryDefaults"
            >
              Isi preset uji lokal
            </UiButton>
            <UiButton variant="secondary" :disabled="isSaving" @click="closeConfigModal">
              Batal
            </UiButton>
            <UiButton
              variant="primary"
              type="submit"
              form="edge-recognition-form"
              :disabled="isSaving"
            >
              {{ isSaving ? 'Menyimpan…' : 'Terapkan ke perangkat' }}
            </UiButton>
          </template>
        </UiModal>
      </template>

      <template v-else>
        <nav class="ai-setup-view__tabs" aria-label="Kelompok pengaturan">
          <UiButton
            v-for="tab in settingsTabs"
            :key="tab.id"
            :variant="activeTab === tab.id ? 'primary' : 'outlined'"
            type="button"
            @click="activeTab = tab.id"
          >
            {{ tab.label }}
          </UiButton>
        </nav>

        <section
          v-if="activeTab === 'enrollment'"
          class="master-data__panel ai-setup-view__settings"
        >
          <div class="master-data__panel-heading">
            <div>
              <p class="master-data__eyebrow">
                Core API · revisi {{ readiness.enrollment_quality_revision }}
              </p>
              <h2>Kualitas capture pendaftaran</h2>
            </div>
          </div>
          <p class="ai-setup-view__note">
            Nilai ini memeriksa ukuran wajah, ketajaman, dan pencahayaan pada setiap capture
            pendaftaran. Mulai dari default yang ada; sesuaikan jika capture yang baik sering
            ditolak. Filter ringan STB diatur terpisah pada tab STB gateway.
          </p>
          <form class="master-data__form ai-setup-view__form" @submit.prevent="saveEnrollment">
            <label>
              Ukuran wajah minimum (piksel)
              <UiInput
                v-model.number="enrollmentForm.min_face_pixels"
                type="number"
                min="16"
                max="2048"
                required
              />
            </label>
            <label>
              Ketajaman minimum
              <UiInput
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
              <UiInput
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
              <UiInput
                v-model.number="enrollmentForm.max_brightness"
                type="number"
                min="1"
                max="255"
                step="any"
                required
              />
            </label>
            <div class="master-data__form-actions">
              <UiButton variant="primary" type="submit" :disabled="isSaving">
                {{ isSaving ? 'Menyimpan…' : 'Simpan kualitas capture' }}
              </UiButton>
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
              <h2>Perangkat STB_GATEWAY</h2>
            </div>
          </div>
          <p class="ai-setup-view__note">
            Pilih STB gateway untuk mengatur burst dan filter capture. Kamera, resolusi, dan FPS
            diatur di host gateway.
          </p>
          <label class="ai-setup-view__device-picker">
            Perangkat
            <UiSelect
              v-model="selectedDeviceId"
              @change="loadDeviceConfiguration(selectedDeviceId)"
            >
              <option value="">Pilih perangkat aktif</option>
              <option v-for="device in devices" :key="device.device_id" :value="device.device_id">
                {{ device.name }} · {{ device.deployment_profile }}
              </option>
            </UiSelect>
          </label>

          <template v-if="selectedDevice?.deployment_profile === 'AI_EDGE'">
            <h3>AI_EDGE · kebijakan pengenalan</h3>
            <p class="ai-setup-view__preset-note" data-testid="edge-preset-note">
              <strong>Mulai cepat:</strong> gunakan preset uji lokal di bawah, lalu sesuaikan
              setelah melihat hasil kamera. Preset bukan hasil kalibrasi; jangan jadikan nilai
              produksi tanpa laporan lokal.
            </p>
            <form class="master-data__form ai-setup-view__form" @submit.prevent="saveDevice">
              <label class="ai-setup-view__field">
                Top-1 similarity
                <UiInput
                  id="edge-top1-threshold"
                  v-model="edgeTop1Text"
                  aria-describedby="edge-top1-hint"
                  type="number"
                  min="-1"
                  max="1"
                  step="any"
                  :required="edgeMarginText !== ''"
                />
                <small id="edge-top1-hint" class="ai-setup-view__field-hint">
                  Skor kandidat terbaik (-1 s.d. 1). Makin tinggi, makin ketat. Nilai awal uji:
                  0,65.
                </small>
              </label>
              <label class="ai-setup-view__field">
                Margin Top-1 − Top-2
                <UiInput
                  id="edge-margin-threshold"
                  v-model="edgeMarginText"
                  aria-describedby="edge-margin-hint"
                  type="number"
                  min="0"
                  max="2"
                  step="any"
                  :required="edgeTop1Text !== ''"
                />
                <small id="edge-margin-hint" class="ai-setup-view__field-hint">
                  Jarak skor kandidat pertama dan kedua. Makin tinggi, makin banyak kasus ambigu
                  diminta ulang. Nilai awal uji: 0,20.
                </small>
              </label>
              <label class="ai-setup-view__field">
                YuNet score threshold
                <UiInput
                  id="edge-yunet-score"
                  v-model.number="edgeForm.yunet_score_threshold"
                  aria-describedby="edge-yunet-score-hint"
                  type="number"
                  min="0"
                  max="1"
                  step="any"
                  required
                />
                <small id="edge-yunet-score-hint" class="ai-setup-view__field-hint">
                  Ambang deteksi wajah, bukan identitas. Nilai awal: 0,90; bila wajah sering luput,
                  periksa fokus dan cahaya sebelum menurunkannya.
                </small>
              </label>
              <label class="ai-setup-view__field">
                YuNet NMS threshold
                <UiInput
                  id="edge-yunet-nms"
                  v-model.number="edgeForm.yunet_nms_threshold"
                  aria-describedby="edge-yunet-nms-hint"
                  type="number"
                  min="0"
                  max="1"
                  step="any"
                  required
                />
                <small id="edge-yunet-nms-hint" class="ai-setup-view__field-hint">
                  Mengatur penekanan kotak deteksi yang bertumpuk. Biarkan 0,30 sebagai nilai awal.
                </small>
              </label>
              <label class="ai-setup-view__field">
                Frame yang harus sepakat
                <UiInput
                  id="edge-agreeing-frames"
                  v-model.number="edgeForm.minimum_agreeing_frames"
                  aria-describedby="edge-agreeing-frames-hint"
                  type="number"
                  min="1"
                  max="10"
                  required
                />
                <small id="edge-agreeing-frames-hint" class="ai-setup-view__field-hint">
                  Jumlah hasil identitas yang konsisten sebelum kandidat diterima. Nilai awal: 3.
                </small>
              </label>
              <label class="ai-setup-view__field">
                Sampling setiap N frame
                <UiInput
                  id="edge-sample-every"
                  v-model.number="edgeForm.sample_every_n_frames"
                  aria-describedby="edge-sample-every-hint"
                  type="number"
                  min="1"
                  max="60"
                  required
                />
                <small id="edge-sample-every-hint" class="ai-setup-view__field-hint">
                  Seberapa sering AI memeriksa frame; angka lebih kecil lebih responsif, tetapi
                  memakai lebih banyak CPU. Ini bukan FPS kamera. Nilai awal: 5.
                </small>
              </label>
              <label class="ai-setup-view__field">
                Frame terbaik
                <UiInput
                  id="edge-best-frame-count"
                  v-model.number="edgeForm.best_frame_count"
                  aria-describedby="edge-best-frame-count-hint"
                  type="number"
                  min="1"
                  max="20"
                  required
                />
                <small id="edge-best-frame-count-hint" class="ai-setup-view__field-hint">
                  Jumlah bukti terbaik yang dipakai mengambil keputusan; minimal sama dengan frame
                  sepakat. Nilai awal: 5.
                </small>
              </label>
              <label class="ai-setup-view__field">
                Riwayat maksimum
                <UiInput
                  id="edge-max-history"
                  v-model.number="edgeForm.max_history_frames"
                  aria-describedby="edge-max-history-hint"
                  type="number"
                  min="1"
                  max="60"
                  required
                />
                <small id="edge-max-history-hint" class="ai-setup-view__field-hint">
                  Batas bukti yang disimpan selama wajah terlacak; harus minimal sama dengan frame
                  terbaik. Nilai awal: 10.
                </small>
              </label>
              <label class="ai-setup-view__form-wide ai-setup-view__field">
                Referensi laporan kalibrasi
                <UiInput
                  id="edge-calibration-reference"
                  v-model="edgeForm.calibration_reference"
                  aria-describedby="edge-calibration-reference-hint"
                  type="text"
                  maxlength="200"
                  :required="edgeThresholdsConfigured"
                  placeholder="ID laporan lokal; preset mengisi label sementara"
                />
                <small id="edge-calibration-reference-hint" class="ai-setup-view__field-hint">
                  Wajib untuk audit saat threshold identitas diisi. Ganti label preset dengan ID
                  laporan setelah kalibrasi lokal.
                </small>
              </label>
              <p v-if="edgeUsesFactoryDefaults" class="ai-setup-view__note" role="status">
                Preset sementara aktif. Hasil ambigu tetap perlu verifikasi petugas; kalibrasi lokal
                wajib sebelum penggunaan operasional.
              </p>
              <div class="master-data__form-actions ai-setup-view__form-wide">
                <UiButton
                  variant="text"
                  type="button"
                  :disabled="isSaving"
                  data-testid="edge-default-preset"
                  @click="applyFactoryDefaults"
                >
                  Isi preset uji lokal
                </UiButton>
                <UiButton variant="primary" type="submit" :disabled="isSaving">
                  {{ isSaving ? 'Menyimpan…' : 'Terapkan ke perangkat' }}
                </UiButton>
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
                        : 'Belum aktif - menunggu kalibrasi'
                    }}
                  </dd>
                </div>
              </dl>
              <p v-if="!edgeThresholdsConfigured" role="status">
                Identifikasi masih dijeda. Isi preset uji lokal untuk smoke test terawasi, atau
                masukkan Top-1 dan margin dari laporan kalibrasi untuk penggunaan operasional.
              </p>
              <p v-else-if="edgeUsesFactoryDefaults" role="status">
                Untuk menguji identitas, harus ada sesi aktif dengan siswa terdaftar di roster.
                Tanpa sesi, preview hanya memeriksa kondisi kamera.
              </p>
            </aside>
          </template>

          <template v-else-if="selectedDevice?.deployment_profile === 'STB_GATEWAY'">
            <h3>STB_GATEWAY · capture dan burst</h3>
            <form class="master-data__form ai-setup-view__form" @submit.prevent="saveDevice">
              <label
                >Ambang gerakan<UiInput
                  v-model.number="gatewayForm.motion_threshold"
                  type="number"
                  min="0"
                  max="255"
                  step="any"
                  required
              /></label>
              <label
                >Sampling periodik (detik)<UiInput
                  v-model.number="gatewayForm.periodic_burst_seconds"
                  type="number"
                  min="0.01"
                  max="3600"
                  step="any"
                  required
              /></label>
              <label
                >Jeda minimum burst (detik)<UiInput
                  v-model.number="gatewayForm.minimum_burst_interval_seconds"
                  type="number"
                  min="0.01"
                  max="3600"
                  step="any"
                  required
              /></label>
              <label
                >Jumlah frame per burst<UiInput
                  v-model.number="gatewayForm.burst_frame_count"
                  type="number"
                  min="1"
                  max="5"
                  required
              /></label>
              <label
                >Jeda antar-frame (detik)<UiInput
                  v-model.number="gatewayForm.burst_frame_interval_seconds"
                  type="number"
                  min="0"
                  max="10"
                  step="any"
                  required
              /></label>
              <label
                >Kualitas JPEG<UiInput
                  v-model.number="gatewayForm.jpeg_quality"
                  type="number"
                  min="20"
                  max="100"
                  required
              /></label>
              <label
                >Kecerahan minimum<UiInput
                  v-model.number="gatewayForm.min_brightness"
                  type="number"
                  min="0"
                  max="254"
                  step="any"
                  required
              /></label>
              <label
                >Kecerahan maksimum<UiInput
                  v-model.number="gatewayForm.max_brightness"
                  type="number"
                  min="1"
                  max="255"
                  step="any"
                  required
              /></label>
              <label
                >Ketajaman minimum<UiInput
                  v-model.number="gatewayForm.min_sharpness"
                  type="number"
                  min="0"
                  max="100000"
                  step="any"
                  required
              /></label>
              <div class="master-data__form-actions ai-setup-view__form-wide">
                <UiButton variant="primary" type="submit" :disabled="isSaving">
                  {{ isSaving ? 'Menyimpan…' : 'Terapkan ke gateway' }}
                </UiButton>
              </div>
            </form>
          </template>
          <p v-else class="master-data__empty">Belum ada perangkat aktif STB_GATEWAY.</p>

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
            <div
              v-for="device in devices"
              :key="device.device_id"
              class="ai-setup-view__device-row"
            >
              <span
                ><strong>{{ device.name }}</strong
                ><small>{{ device.deployment_profile }}</small></span
              >
              <span>{{ configStatusLabel(device.config_apply_status) }}</span>
              <code v-if="device.config_error_code">{{ device.config_error_code }}</code>
            </div>
          </div>
          <p v-else class="master-data__empty">
            Belum ada status perangkat aktif untuk profile ini.
          </p>
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
            Threshold harus diambil dari laporan kalibrasi lokal. Jika keduanya kosong, service
            tetap degraded dan tidak menjalankan pengenalan otomatis. Saat disimpan, AI Central
            mengambil konfigurasi terbaru tanpa mengubah file model.
          </p>
          <form class="master-data__form ai-setup-view__form" @submit.prevent="saveCentral">
            <label
              >Ukuran wajah minimum<UiInput
                v-model.number="centralForm.min_face_pixels"
                type="number"
                min="16"
                max="2048"
                required
            /></label>
            <label
              >Ketajaman minimum<UiInput
                v-model.number="centralForm.min_laplacian_variance"
                type="number"
                min="0"
                max="100000"
                step="any"
                required
            /></label>
            <label
              >Kecerahan minimum<UiInput
                v-model.number="centralForm.min_brightness"
                type="number"
                min="0"
                max="254"
                step="any"
                required
            /></label>
            <label
              >Kecerahan maksimum<UiInput
                v-model.number="centralForm.max_brightness"
                type="number"
                min="1"
                max="255"
                step="any"
                required
            /></label>
            <label
              >Top-1 similarity<UiInput
                v-model="centralTop1Text"
                type="number"
                min="-1"
                max="1"
                step="any"
                :required="centralMarginText !== ''"
            /></label>
            <label
              >Margin Top-1 − Top-2<UiInput
                v-model="centralMarginText"
                type="number"
                min="0"
                max="2"
                step="any"
                :required="centralTop1Text !== ''"
            /></label>
            <label
              >YuNet score threshold<UiInput
                v-model.number="centralForm.yunet_score_threshold"
                type="number"
                min="0"
                max="1"
                step="any"
                required
            /></label>
            <label
              >YuNet NMS threshold<UiInput
                v-model.number="centralForm.yunet_nms_threshold"
                type="number"
                min="0"
                max="1"
                step="any"
                required
            /></label>
            <label
              >Frame yang harus sepakat<UiInput
                v-model.number="centralForm.minimum_agreeing_frames"
                type="number"
                min="1"
                max="10"
                required
            /></label>
            <label
              >Sampling setiap N frame<UiInput
                v-model.number="centralForm.sample_every_n_frames"
                type="number"
                min="1"
                max="60"
                required
            /></label>
            <label
              >Frame terbaik<UiInput
                v-model.number="centralForm.best_frame_count"
                type="number"
                min="1"
                max="20"
                required
            /></label>
            <label
              >Riwayat maksimum<UiInput
                v-model.number="centralForm.max_history_frames"
                type="number"
                min="1"
                max="60"
                required
            /></label>
            <label class="ai-setup-view__form-wide"
              >Referensi laporan kalibrasi<UiInput
                v-model="centralForm.calibration_reference"
                type="text"
                maxlength="200"
                placeholder="Wajib diisi bila threshold diatur"
            /></label>
            <p v-if="centralUsesFactoryDefaults" class="ai-setup-view__note" role="status">
              Berjalan dengan default aman sementara - presensi meragukan akan diminta mengulang
              atau dicatat manual. Kalibrasi lokal wajib sebelum produksi.
            </p>
            <div class="master-data__form-actions ai-setup-view__form-wide">
              <UiButton
                variant="text"
                type="button"
                :disabled="isSaving"
                @click="applyFactoryDefaults"
              >
                Pakai default aman
              </UiButton>
              <UiButton variant="primary" type="submit" :disabled="isSaving">
                {{ isSaving ? 'Menyimpan…' : 'Simpan dan terapkan' }}
              </UiButton>
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
            <RouterLink class="st-btnlink" to="/app/devices">Kelola perangkat</RouterLink>
          </div>
          <div class="st-tablewrap">
            <table class="st-table">
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
                  <td data-label="Kamera">{{ deviceHealthLabel(device.camera_status) }}</td>
                  <td data-label="Koneksi">{{ deviceHealthLabel(device.health_status) }}</td>
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
    </template>
  </div>
</template>
