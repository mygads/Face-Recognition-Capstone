<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  ApiError,
  listClasses,
  listClassEnrollmentStatus,
  listFaceTemplates,
  revokeFaceTemplate,
  submitEnrollmentCaptures,
  type EnrollmentCaptureResult,
  type EnrollmentStudentStatus,
  type FaceTemplate,
  type SchoolClass,
} from '../api/client'
import {
  UiAvatar,
  UiBadge,
  UiButton,
  UiCard,
  UiEmptyState,
  UiModal,
  UiPageHeader,
  UiSearchInput,
  UiSelect,
  UiStat,
  UiTextarea,
} from '../components/ui'

type CapturePhase = 'ready' | 'countdown' | 'capturing' | 'processing' | 'confirming' | 'complete'

const classes = ref<SchoolClass[]>([])
const students = ref<EnrollmentStudentStatus[]>([])
const selectedClassId = ref('')
const selectedStudentId = ref('')
const rosterSearch = ref('')
const filteredStudents = computed(() => {
  const q = rosterSearch.value.trim().toLowerCase()
  if (!q) return students.value
  return students.value.filter(
    (student) =>
      student.full_name.toLowerCase().includes(q) ||
      student.student_number.toLowerCase().includes(q),
  )
})
const enrolledCount = computed(
  () => students.value.filter((s) => s.template_status === 'enrolled').length,
)
const pendingCount = computed(
  () => students.value.filter((s) => s.template_status !== 'enrolled').length,
)
const videoElement = ref<HTMLVideoElement | null>(null)
const capturePhase = ref<CapturePhase>('ready')
const countdownValue = ref(3)
const captureIndex = ref(0)
const captureResult = ref<EnrollmentCaptureResult | null>(null)
const duplicateWarnings = computed(() => captureResult.value?.duplicate_warnings ?? [])
const confirmationRequired = computed(() => captureResult.value?.confirmation_required ?? true)
const activeTemplates = ref<FaceTemplate[]>([])
const isLoadingTemplates = ref(false)
const isRevoking = ref(false)
const showRevokeConfirm = ref(false)
const revokeReason = ref('')
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
  activeTemplates.value = []
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
    // Frames are secured as Blobs: release the camera while the operator
    // reviews the result, instead of streaming through the confirm step.
    stopCamera()
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
  cancelCapture()
  pageMessage.value = null
  pageError.value = null
  selectedStudentId.value = student.id
  activeTemplates.value = []
  if (student.template_status === 'enrolled') void loadActiveTemplates(student.id)
}

async function loadActiveTemplates(studentId: string): Promise<void> {
  isLoadingTemplates.value = true
  try {
    const templates = await listFaceTemplates(studentId)
    if (selectedStudentId.value === studentId) activeTemplates.value = templates
  } catch (error) {
    pageError.value = formatError(error)
  } finally {
    isLoadingTemplates.value = false
  }
}

async function revokeSelectedTemplates(): Promise<void> {
  const templates = activeTemplates.value
  const student = selectedStudent.value
  if (templates.length === 0 || !student || isRevoking.value) return
  isRevoking.value = true
  pageError.value = null
  try {
    for (const template of templates) {
      await revokeFaceTemplate(template.id)
    }
    const updatedRoster = await listClassEnrollmentStatus(selectedClassId.value)
    students.value = updatedRoster
    const updatedStudent = updatedRoster.find((item) => item.id === student.id)
    selectedStudentId.value = updatedStudent?.id ?? ''
    activeTemplates.value = []
    pageMessage.value =
      `${student.full_name}: ${templates.length} template dicabut. ` +
      'Siswa dapat didaftarkan ulang.'
  } catch (error) {
    pageError.value = formatError(error)
  } finally {
    isRevoking.value = false
  }
}

const selectedClassLabel = computed(
  () => classes.value.find((item) => item.id === selectedClassId.value)?.code ?? '',
)
const revokeReasonLength = computed(() => revokeReason.value.trim().length)
const revokeReasonValid = computed(
  () => revokeReasonLength.value >= 10 && revokeReasonLength.value <= 120,
)

function openRevokeConfirm(): void {
  revokeReason.value = ''
  showRevokeConfirm.value = true
}

async function confirmRevoke(): Promise<void> {
  if (!revokeReasonValid.value || isRevoking.value) return
  await revokeSelectedTemplates()
  if (!pageError.value) {
    showRevokeConfirm.value = false
    revokeReason.value = ''
  }
}

function confirmIdentityAndContinue(): void {
  if (
    !captureResult.value ||
    !selectedStudent.value ||
    (confirmationRequired.value && !identityConfirmed.value)
  )
    return
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
  <div class="st-page" aria-label="Pendaftaran wajah siswa">
    <UiPageHeader
      eyebrow="Modul biometrik siswa"
      title="Pendaftaran Wajah Biometrik"
      description="Manajemen acuan biometrik siswa yang bersumber dari Data Master. Daftarkan siswa satu per satu; pastikan nama di layar sesuai dengan siswa di depan kamera."
    >
      <template #actions>
        <UiButton variant="secondary" type="button" @click="loadClasses">Sinkron Master</UiButton>
      </template>
    </UiPageHeader>
    <p v-if="pageError" class="st-alert st-alert--error" role="alert">{{ pageError }}</p>
    <p v-if="pageMessage" class="st-alert st-alert--success" role="status">{{ pageMessage }}</p>

    <div class="st-kpi">
      <UiStat
        label="Siap & terverifikasi"
        :value="`${enrolledCount} siswa`"
        caption="Koleksi valid"
        tone="success"
      />
      <UiStat
        label="Belum terdaftar"
        :value="`${pendingCount} siswa`"
        caption="Perlu sesi pemotretan"
        tone="warning"
      />
    </div>

    <UiCard
      title="Pilih kelas dan siswa"
      subtitle="1. Data master siswa = identitas & keanggotaan kelas. 2. Pendaftaran wajah = data acuan wajah untuk presensi."
    >
      <template #header>
        <label class="st-field" style="min-width: 240px"
          ><span>Kelas</span>
          <UiSelect v-model="selectedClassId" aria-label="Pilih kelas" :disabled="isLoading">
            <option value="" disabled>Pilih kelas aktif</option>
            <option v-for="schoolClass in classes" :key="schoolClass.id" :value="schoolClass.id">
              {{ schoolClass.name }} · {{ schoolClass.academic_year }}
            </option>
          </UiSelect>
        </label>
      </template>
      <UiSearchInput
        v-model="rosterSearch"
        placeholder="Cari NIS atau Nama Siswa…"
        aria-label="Cari siswa"
      />
      <div class="st-tablewrap" style="margin-top: 10px">
        <table class="st-table">
          <thead>
            <tr>
              <th>Nomor siswa</th>
              <th>Nama lengkap</th>
              <th>Status acuan</th>
              <th><span class="st-table__actions">Tindakan</span></th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="isLoading">
              <td colspan="4"><UiEmptyState title="Memuat kelas dan siswa…" /></td>
            </tr>
            <tr v-else-if="!selectedClassId">
              <td colspan="4"><UiEmptyState title="Belum ada kelas aktif untuk dipilih." /></td>
            </tr>
            <tr v-else-if="filteredStudents.length === 0">
              <td colspan="4"><UiEmptyState title="Tidak ada siswa yang cocok." /></td>
            </tr>
            <tr
              v-for="student in filteredStudents"
              v-else
              :key="student.id"
              :data-testid="`enrollment-student-${student.id}`"
              :class="{ 'st-list__item--active': student.id === selectedStudentId }"
            >
              <td class="st-table__mono">{{ student.student_number }}</td>
              <td>
                <span class="st-table__who"
                  ><UiAvatar :name="student.full_name" />{{ student.full_name }}</span
                >
              </td>
              <td>
                <UiBadge
                  :tone="
                    student.template_status === 'enrolled'
                      ? 'present'
                      : student.template_status === 'needs_reenrollment'
                        ? 'late'
                        : 'neutral'
                  "
                >
                  {{ statusLabel(student.template_status) }}
                </UiBadge>
              </td>
              <td class="st-table__actions">
                <button
                  class="st-rowbtn"
                  type="button"
                  :disabled="isStarting"
                  @click="selectStudent(student)"
                >
                  {{
                    student.id === selectedStudentId
                      ? 'Dipilih ✓'
                      : student.template_status === 'enrolled'
                        ? 'Ambil Ulang'
                        : 'Mulai Pendaftaran'
                  }}
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </UiCard>

    <UiCard
      v-if="selectedStudent || capturePhase === 'complete'"
      title="Capture kamera"
      :subtitle="
        selectedStudent
          ? `${selectedStudent.full_name} · ${selectedStudent.student_number}`
          : 'Pendaftaran kelas selesai'
      "
    >
      <template #header>
        <UiButton
          v-if="
            capturePhase === 'countdown' ||
            capturePhase === 'capturing' ||
            capturePhase === 'processing'
          "
          variant="secondary"
          type="button"
          @click="cancelCapture"
          >Batalkan</UiButton
        >
      </template>
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
            >{{ countdownValue }}</span
          >
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
            <label v-if="confirmationRequired" class="enrollment-view__confirm">
              <input v-model="identityConfirmed" type="checkbox" />
              <span
                >Saya memastikan siswa di kamera adalah {{ selectedStudent.full_name }} ({{
                  selectedStudent.student_number
                }}).</span
              >
            </label>
            <p v-if="duplicateWarnings.length" class="st-alert st-alert--error" role="status">
              Ada kemungkinan wajah mirip dengan
              {{ duplicateWarnings.map((w) => `${w.full_name} (${w.student_number})`).join(', ') }}.
              Periksa kembali identitas dan lanjutkan hanya setelah operator memastikan siswa yang
              benar.
            </p>
            <UiButton
              variant="primary"
              type="button"
              data-testid="confirm-enrollment-identity"
              :disabled="confirmationRequired && !identityConfirmed"
              @click="confirmIdentityAndContinue"
            >
              Konfirmasi identitas & lanjut
            </UiButton>
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
          <p v-if="capturePhase === 'capturing'" class="st-table__muted">
            {{ captureIndex }} / 4 capture
          </p>
          <p
            v-if="capturePhase === 'confirming' && captureResult"
            class="enrollment-view__result-status"
            role="status"
          >
            Status: {{ statusLabel(captureResult.template_status) }}
          </p>
          <div
            v-if="selectedStudent.template_status === 'enrolled' && capturePhase === 'ready'"
            class="enrollment-view__revoke"
          >
            <p class="st-table__muted">
              Template aktif: {{ isLoadingTemplates ? 'memuat…' : activeTemplates.length }}
            </p>
            <UiButton
              variant="secondary"
              type="button"
              data-testid="revoke-enrollment-template"
              :disabled="isLoadingTemplates || isRevoking || activeTemplates.length === 0"
              @click="openRevokeConfirm"
            >
              {{ isRevoking ? 'Mencabut…' : 'Cabut semua template untuk daftar ulang' }}
            </UiButton>
            <UiModal
              v-if="showRevokeConfirm"
              title="Cabut Acuan Wajah Siswa?"
              @close="showRevokeConfirm = false"
            >
              <p class="st-modal__eyebrow">Konfirmasi kritis</p>
              <p v-if="selectedStudent" class="st-identityline" data-testid="revoke-identity">
                <UiAvatar :name="selectedStudent.full_name" />
                <span>
                  <strong>{{ selectedStudent.full_name }}</strong
                  ><br />
                  <span class="st-table__muted"
                    >NIS: {{ selectedStudent.student_number
                    }}<span v-if="selectedClassLabel"> · {{ selectedClassLabel }}</span></span
                  >
                </span>
              </p>
              <p class="st-alert st-alert--error" role="note">
                <strong>Peringatan dampak:</strong>
                Pencabutan menghapus acuan wajah aktif siswa ini. Siswa tidak dapat melakukan
                presensi mandiri sampai acuan wajah didaftarkan kembali.
              </p>
              <div class="st-fieldhead">
                <label for="revoke-reason">Alasan pencabutan *</label>
                <span class="st-charcount" aria-live="polite"
                  >{{ revokeReasonLength }}/120 karakter</span
                >
              </div>
              <UiTextarea
                id="revoke-reason"
                v-model="revokeReason"
                data-testid="revoke-reason-input"
                maxlength="120"
                rows="3"
                placeholder="Contoh: Perubahan bentuk fisik signifikan / kualitas tangkapan lama menyebabkan galat pengenalan berulang…"
                :invalid="revokeReasonLength > 0 && !revokeReasonValid"
              />
              <p class="st-table__muted">Alasan wajib diisi (minimal 10 karakter).</p>
              <template #footer>
                <UiButton variant="secondary" type="button" @click="showRevokeConfirm = false"
                  >Batal</UiButton
                >
                <UiButton
                  variant="danger"
                  type="button"
                  data-testid="confirm-revoke-template"
                  :disabled="!revokeReasonValid || isRevoking"
                  @click="confirmRevoke"
                >
                  <span class="st-material-icon" aria-hidden="true">person_remove</span>
                  {{ isRevoking ? 'Mencabut…' : 'Ya, cabut acuan' }}
                </UiButton>
              </template>
            </UiModal>
          </div>
          <UiButton
            v-if="
              capturePhase === 'ready' &&
              selectedStudent &&
              selectedStudent.template_status !== 'enrolled'
            "
            variant="primary"
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
          </UiButton>
        </div>
      </div>
    </UiCard>
  </div>
</template>
