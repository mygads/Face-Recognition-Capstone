<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  ApiError,
  listClasses,
  listClassEnrollmentStatus,
  submitEnrollmentCaptures,
  type EnrollmentCaptureResult,
  type EnrollmentStudentStatus,
  type SchoolClass,
} from '../api/client'

type CapturePhase = 'ready' | 'countdown' | 'capturing' | 'processing' | 'confirming' | 'complete'

const classes = ref<SchoolClass[]>([])
const students = ref<EnrollmentStudentStatus[]>([])
const selectedClassId = ref('')
const selectedStudentId = ref('')
const videoElement = ref<HTMLVideoElement | null>(null)
const capturePhase = ref<CapturePhase>('ready')
const countdownValue = ref(3)
const captureIndex = ref(0)
const captureResult = ref<EnrollmentCaptureResult | null>(null)
const identityConfirmed = ref(false)
const pageError = ref<string | null>(null)
const pageMessage = ref<string | null>(null)
const isLoading = ref(false)
const isStarting = ref(false)
const stream = ref<MediaStream | null>(null)
let flowVersion = 0

const selectedStudent = computed(
  () => students.value.find((student) => student.id === selectedStudentId.value) ?? null,
)
const eligibleStudents = computed(() =>
  students.value.filter((student) => student.template_status !== 'enrolled'),
)
const progressPercent = computed(() => {
  if (capturePhase.value === 'countdown') return 5
  if (capturePhase.value === 'capturing') return Math.round((captureIndex.value / 4) * 70) + 10
  if (capturePhase.value === 'processing') return 90
  if (capturePhase.value === 'confirming') return 100
  return 0
})

function formatError(error: unknown): string {
  if (error instanceof ApiError) {
    const details = error.details?.map((item) => `${item.field}: ${item.message}`)
    return details?.length ? details.join(' · ') : error.message
  }
  if (error instanceof DOMException && error.name === 'NotAllowedError') {
    return 'Akses kamera belum diizinkan. Izinkan kamera pada browser lalu coba lagi.'
  }
  return 'Permintaan tidak dapat diproses. Periksa kamera dan koneksi, lalu coba lagi.'
}

function delay(milliseconds: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds))
}

function stopCamera(): void {
  stream.value?.getTracks().forEach((track) => track.stop())
  stream.value = null
  if (videoElement.value) videoElement.value.srcObject = null
}

async function loadClasses(): Promise<void> {
  isLoading.value = true
  pageError.value = null
  try {
    const result = await listClasses({ limit: 100, offset: 0, is_active: true })
    classes.value = result.items
    selectedClassId.value = result.items[0]?.id ?? ''
  } catch (error) {
    pageError.value = formatError(error)
  } finally {
    isLoading.value = false
  }
}

async function loadRoster(classId: string): Promise<void> {
  flowVersion += 1
  stopCamera()
  isStarting.value = false
  students.value = []
  selectedStudentId.value = ''
  capturePhase.value = 'ready'
  captureResult.value = null
  identityConfirmed.value = false
  pageMessage.value = null
  pageError.value = null
  if (!classId) return

  isLoading.value = true
  try {
    students.value = await listClassEnrollmentStatus(classId)
    selectedStudentId.value = eligibleStudents.value[0]?.id ?? ''
  } catch (error) {
    pageError.value = formatError(error)
  } finally {
    isLoading.value = false
  }
}

onMounted(() => void loadClasses())

watch(selectedClassId, (classId, previousClassId) => {
  if (classId && classId !== previousClassId) void loadRoster(classId)
})

onBeforeUnmount(() => {
  flowVersion += 1
  stopCamera()
})

function captureVideoFrame(): Promise<Blob> {
  const video = videoElement.value
  if (!video || video.videoWidth < 1 || video.videoHeight < 1) {
    return Promise.reject(new Error('Kamera belum siap.'))
  }
  const canvas = document.createElement('canvas')
  canvas.width = video.videoWidth
  canvas.height = video.videoHeight
  const context = canvas.getContext('2d')
  if (!context) return Promise.reject(new Error('Kamera belum siap.'))
  context.drawImage(video, 0, 0, canvas.width, canvas.height)
  return new Promise((resolve, reject) => {
    canvas.toBlob(
      (image) => (image ? resolve(image) : reject(new Error('Capture kamera gagal.'))),
      'image/jpeg',
      0.88,
    )
  })
}

async function startEnrollment(): Promise<void> {
  if (!selectedStudent.value || isStarting.value) return
  pageError.value = null
  pageMessage.value = null
  captureResult.value = null
  identityConfirmed.value = false
  captureIndex.value = 0
  isStarting.value = true
  const currentFlow = ++flowVersion

  try {
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error('Browser ini tidak dapat membuka kamera.')
    }
    const cameraStream = await navigator.mediaDevices.getUserMedia({
      audio: false,
      video: { facingMode: 'user', width: { ideal: 1280 }, height: { ideal: 720 } },
    })
    if (currentFlow !== flowVersion) {
      cameraStream.getTracks().forEach((track) => track.stop())
      return
    }
    stream.value = cameraStream
    if (!videoElement.value) throw new Error('Preview kamera tidak tersedia.')
    videoElement.value.srcObject = stream.value
    await videoElement.value.play()
    capturePhase.value = 'countdown'
    for (let remaining = 3; remaining > 0; remaining -= 1) {
      countdownValue.value = remaining
      await delay(1000)
      if (currentFlow !== flowVersion) return
    }

    capturePhase.value = 'capturing'
    const captures: Blob[] = []
    for (let index = 0; index < 4; index += 1) {
      captureIndex.value = index + 1
      captures.push(await captureVideoFrame())
      if (currentFlow !== flowVersion) return
      if (index < 3) await delay(1000)
    }

    capturePhase.value = 'processing'
    const submittedStudentId = selectedStudent.value.id
    captureResult.value = await submitEnrollmentCaptures(submittedStudentId, captures)
    if (currentFlow !== flowVersion) return
    if (captureResult.value.student_id !== submittedStudentId) {
      throw new Error('Hasil pendaftaran tidak sesuai dengan siswa yang dipilih.')
    }
    capturePhase.value = 'confirming'
  } catch (error) {
    if (currentFlow === flowVersion) {
      pageError.value = formatError(error)
      capturePhase.value = 'ready'
      stopCamera()
    }
  } finally {
    if (currentFlow === flowVersion) isStarting.value = false
  }
}

function cancelCapture(): void {
  flowVersion += 1
  isStarting.value = false
  capturePhase.value = 'ready'
  captureResult.value = null
  identityConfirmed.value = false
  captureIndex.value = 0
  stopCamera()
}

function selectStudent(student: EnrollmentStudentStatus): void {
  if (student.template_status === 'enrolled') return
  cancelCapture()
  pageMessage.value = null
  pageError.value = null
  selectedStudentId.value = student.id
}

function confirmIdentityAndContinue(): void {
  if (!identityConfirmed.value || !captureResult.value || !selectedStudent.value) return
  const currentIndex = students.value.findIndex((student) => student.id === selectedStudentId.value)
  students.value = students.value.map((student) =>
    student.id === selectedStudentId.value
      ? {
          ...student,
          template_status: captureResult.value?.template_status ?? student.template_status,
        }
      : student,
  )
  capturePhase.value = 'ready'
  captureResult.value = null
  identityConfirmed.value = false
  stopCamera()

  const nextStudent =
    students.value
      .slice(currentIndex + 1)
      .find((student) => student.template_status !== 'enrolled') ?? null
  if (nextStudent) {
    selectedStudentId.value = nextStudent.id
    pageMessage.value = `${nextStudent.full_name} dipilih. Pastikan siswa yang benar sebelum memulai.`
    return
  }
  selectedStudentId.value = ''
  capturePhase.value = 'complete'
  pageMessage.value = 'Semua siswa yang dipilih untuk kelas ini sudah diproses.'
}

function statusLabel(status: EnrollmentStudentStatus['template_status']): string {
  if (status === 'enrolled') return 'Terdaftar'
  if (status === 'needs_reenrollment') return 'Perlu daftar ulang'
  return 'Belum terdaftar'
}
</script>

<template>
  <section class="master-data enrollment-view" aria-label="Pendaftaran wajah siswa">
    <p class="enrollment-view__hint">
      Daftarkan siswa satu per satu. Pastikan nama di layar sesuai dengan siswa di depan kamera.
      Capture hanya digunakan selama proses ini.
    </p>

    <p v-if="pageError" class="master-data__alert" role="alert">{{ pageError }}</p>
    <p v-if="pageMessage" class="master-data__success" role="status">{{ pageMessage }}</p>

    <section class="master-data__panel" aria-labelledby="enrollment-roster-title">
      <div class="master-data__panel-heading">
        <div>
          <p class="master-data__eyebrow">Pendaftaran siswa</p>
          <h2 id="enrollment-roster-title">Pilih kelas dan siswa</h2>
        </div>
        <label class="enrollment-view__class-picker">
          Kelas
          <select v-model="selectedClassId" aria-label="Pilih kelas" :disabled="isLoading">
            <option value="" disabled>Pilih kelas aktif</option>
            <option v-for="schoolClass in classes" :key="schoolClass.id" :value="schoolClass.id">
              {{ schoolClass.name }} · {{ schoolClass.academic_year }}
            </option>
          </select>
        </label>
      </div>

      <div class="enrollment-view__roster" aria-label="Daftar siswa">
        <button
          v-for="student in students"
          :key="student.id"
          class="enrollment-view__student"
          :class="{
            'enrollment-view__student--selected': student.id === selectedStudentId,
            'enrollment-view__student--enrolled': student.template_status === 'enrolled',
          }"
          type="button"
          :disabled="student.template_status === 'enrolled' || isStarting"
          :aria-pressed="student.id === selectedStudentId"
          :data-testid="`enrollment-student-${student.id}`"
          @click="selectStudent(student)"
        >
          <span class="enrollment-view__student-copy">
            <strong>{{ student.full_name }}</strong>
            <small>{{ student.student_number }}</small>
          </span>
          <span
            class="status-badge"
            :class="
              student.template_status === 'enrolled'
                ? 'status-badge--active'
                : student.template_status === 'needs_reenrollment'
                  ? 'status-badge--warning'
                  : 'status-badge--inactive'
            "
          >
            {{ statusLabel(student.template_status) }}
          </span>
        </button>
        <p v-if="isLoading" class="master-data__empty">Memuat kelas dan siswa…</p>
        <p v-else-if="!selectedClassId" class="master-data__empty">
          Belum ada kelas aktif untuk dipilih.
        </p>
        <p v-else-if="students.length === 0" class="master-data__empty">
          Tidak ada siswa aktif di kelas ini.
        </p>
        <p v-else-if="eligibleStudents.length === 0" class="master-data__empty">
          Semua siswa di kelas ini sudah terdaftar.
        </p>
      </div>
    </section>

    <section
      v-if="selectedStudent || capturePhase === 'complete'"
      class="master-data__panel enrollment-view__capture-panel"
      aria-labelledby="capture-panel-title"
    >
      <div class="master-data__panel-heading">
        <div>
          <p class="master-data__eyebrow">
            {{ capturePhase === 'confirming' ? 'Konfirmasi identitas' : 'Capture kamera' }}
          </p>
          <h2 id="capture-panel-title">
            {{ selectedStudent ? selectedStudent.full_name : 'Pendaftaran kelas selesai' }}
          </h2>
          <p v-if="selectedStudent" class="master-data__muted">
            {{ selectedStudent.student_number }} ·
            {{ statusLabel(selectedStudent.template_status) }}
          </p>
        </div>
        <button
          v-if="
            capturePhase === 'countdown' ||
            capturePhase === 'capturing' ||
            capturePhase === 'processing'
          "
          class="button button--secondary"
          type="button"
          @click="cancelCapture"
        >
          Batalkan
        </button>
      </div>

      <div v-if="selectedStudent" class="enrollment-view__capture-layout">
        <div class="enrollment-view__camera-frame">
          <video
            ref="videoElement"
            class="enrollment-view__camera"
            autoplay
            muted
            playsinline
            aria-label="Preview kamera siswa"
            data-testid="enrollment-camera"
          />
          <div v-if="!stream" class="enrollment-view__camera-placeholder">
            <svg viewBox="0 0 48 48" fill="none" aria-hidden="true">
              <rect x="5" y="11" width="28" height="26" rx="4" />
              <path d="m33 19 10-6v22l-10-6" />
              <circle cx="19" cy="24" r="6" />
            </svg>
            <span>Preview kamera akan tampil di sini</span>
          </div>
          <span
            v-if="capturePhase === 'countdown'"
            class="enrollment-view__countdown"
            aria-live="polite"
          >
            {{ countdownValue }}
          </span>
        </div>

        <div class="enrollment-view__capture-info">
          <p v-if="capturePhase === 'ready'" class="enrollment-view__instruction">
            Arahkan kamera ke siswa. Wajah dan nama di layar harus sesuai sebelum melanjutkan.
          </p>
          <p
            v-else-if="capturePhase === 'countdown'"
            class="enrollment-view__instruction"
            aria-live="polite"
          >
            Siap-siap… capture dimulai dalam {{ countdownValue }} detik.
          </p>
          <p
            v-else-if="capturePhase === 'capturing'"
            class="enrollment-view__instruction"
            aria-live="polite"
          >
            Pengambilan {{ captureIndex }} dari 4. Minta siswa tetap menghadap kamera.
          </p>
          <p
            v-else-if="capturePhase === 'processing'"
            class="enrollment-view__instruction"
            aria-live="polite"
          >
            Sedang memeriksa hasil capture. Tunggu sebentar.
          </p>
          <template v-else-if="capturePhase === 'confirming' && captureResult">
            <p class="enrollment-view__instruction" role="status">
              {{ captureResult.accepted_frames }} dari 4 capture siap. Pastikan siswa pada preview
              cocok dengan identitas berikut.
            </p>
            <label class="enrollment-view__confirm">
              <input v-model="identityConfirmed" type="checkbox" />
              <span>
                Saya memastikan siswa di kamera adalah {{ selectedStudent.full_name }} ({{
                  selectedStudent.student_number
                }}).
              </span>
            </label>
            <button
              class="button button--primary"
              type="button"
              data-testid="confirm-enrollment-identity"
              :disabled="!identityConfirmed"
              @click="confirmIdentityAndContinue"
            >
              Konfirmasi identitas & lanjut
            </button>
          </template>
          <div v-else-if="capturePhase === 'complete'" class="enrollment-view__instruction">
            Semua siswa yang dapat diproses sudah selesai.
          </div>
          <div
            v-if="
              capturePhase === 'countdown' ||
              capturePhase === 'capturing' ||
              capturePhase === 'processing' ||
              capturePhase === 'confirming'
            "
            class="enrollment-view__progress"
            role="progressbar"
            aria-label="Kemajuan pendaftaran"
            :aria-valuenow="progressPercent"
            aria-valuemin="0"
            aria-valuemax="100"
          >
            <span :style="{ width: `${progressPercent}%` }" />
          </div>
          <p v-if="capturePhase === 'capturing'" class="master-data__muted">
            {{ captureIndex }} / 4 capture
          </p>
          <p
            v-if="capturePhase === 'confirming' && captureResult"
            class="enrollment-view__result-status"
            role="status"
          >
            Status: {{ statusLabel(captureResult.template_status) }}
          </p>
          <button
            v-if="capturePhase === 'ready' && selectedStudent"
            class="button button--primary"
            type="button"
            data-testid="start-enrollment-capture"
            :disabled="isStarting"
            @click="startEnrollment"
          >
            {{
              selectedStudent.template_status === 'needs_reenrollment'
                ? 'Daftar ulang siswa'
                : 'Mulai pendaftaran'
            }}
          </button>
        </div>
      </div>
    </section>
  </section>
</template>
