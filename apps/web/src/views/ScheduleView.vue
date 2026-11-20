<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { todayLocalISO } from '../utils/dateFormat'
import {
  createSchedule,
  deleteSchedule,
  duplicateSchedule,
  listClasses,
  listLaboratories,
  listScheduleTeachers,
  listSchedules,
  updateSchedule,
  type Laboratory,
  type Schedule,
  type ScheduleDuplicateRequest,
  type ScheduleTeacher,
  type SchoolClass,
} from '../api/client'
import { formatApiError } from '../utils/apiError'
import UiBadge from '../components/ui/UiBadge.vue'
import UiButton from '../components/ui/UiButton.vue'
import UiDrawer from '../components/ui/UiDrawer.vue'
import UiEmptyState from '../components/ui/UiEmptyState.vue'
import UiField from '../components/ui/UiField.vue'
import UiInput from '../components/ui/UiInput.vue'
import UiModal from '../components/ui/UiModal.vue'
import UiPageHeader from '../components/ui/UiPageHeader.vue'
import UiPagination from '../components/ui/UiPagination.vue'
import UiSearchInput from '../components/ui/UiSearchInput.vue'
import UiSelect from '../components/ui/UiSelect.vue'
import { useAuthStore } from '../stores/auth'

type ScheduleForm = {
  class_id: string
  laboratory_id: string
  teacher_user_id: string
  subject: string
  weekday: number
  start_time: string
  end_time: string
  timezone_name: string
  effective_from: string
  effective_through: string
  is_active: boolean
}

const weekdays = ['Senin', 'Selasa', 'Rabu', 'Kamis', 'Jumat', 'Sabtu', 'Minggu']
const auth = useAuthStore()
const canAssignTeacher = computed(() => auth.account?.roles.includes('ADMIN') ?? false)
const rows = ref<Schedule[]>([])
const classes = ref<SchoolClass[]>([])
const laboratories = ref<Laboratory[]>([])
const teachers = ref<ScheduleTeacher[]>([])
const total = ref(0)
const page = ref(0)
const pageSize = 10
const searchText = ref('')
const search = ref('')
const weekdayFilter = ref('')
const statusFilter = ref('active')
const isLoading = ref(false)
const isSaving = ref(false)
const errorMessage = ref<string | null>(null)
const formError = ref<string | null>(null)
const isFormOpen = ref(false)
const editingId = ref<string | null>(null)
const selected = ref<Schedule | null>(null)
const form = ref<ScheduleForm>(emptyForm())
const duplicateTarget = ref<Schedule | null>(null)
const isDuplicateOpen = ref(false)
const isDuplicating = ref(false)
const duplicateMode = ref<'weeks' | 'through'>('weeks')
const duplicateWeeks = ref(4)
const duplicateStartDate = ref('')
const duplicateThroughDate = ref('')
const duplicateError = ref<string | null>(null)
const successMessage = ref<string | null>(null)
const pendingDelete = ref<Schedule | null>(null)
const isDeleting = ref(false)
const deleteError = ref<string | null>(null)

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))

function emptyForm(): ScheduleForm {
  const now = new Date()
  const localDate = todayLocalISO()
  return {
    class_id: '',
    laboratory_id: '',
    teacher_user_id: '',
    subject: '',
    weekday: (now.getDay() + 6) % 7,
    start_time: '09:00',
    end_time: '10:00',
    timezone_name: 'Asia/Jakarta',
    effective_from: localDate,
    effective_through: '',
    is_active: true,
  }
}

function formatError(error: unknown): string {
  return formatApiError(error, 'Permintaan tidak dapat diproses. Coba lagi.')
}

function weekdayName(day: number): string {
  return weekdays[day] ?? '-'
}

function displayTime(value: string): string {
  return value.slice(0, 5)
}

function dateValue(value: string): Date {
  return new Date(`${value}T00:00:00.000Z`)
}

function isoDate(value: Date): string {
  return `${value.getUTCFullYear()}-${String(value.getUTCMonth() + 1).padStart(2, '0')}-${String(value.getUTCDate()).padStart(2, '0')}`
}

function addDays(value: string, days: number): string {
  const result = dateValue(value)
  result.setUTCDate(result.getUTCDate() + days)
  return isoDate(result)
}

function todayInTimezone(timezone: string): string {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: timezone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(new Date())
  const part = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find((item) => item.type === type)?.value
  return `${part('year')}-${part('month')}-${part('day')}`
}

function nextWeekdayOnOrAfter(startDate: string, weekday: number): string {
  const start = dateValue(startDate)
  const mondayFirstWeekday = (start.getUTCDay() + 6) % 7
  const daysUntil = (weekday - mondayFirstWeekday + 7) % 7
  return addDays(startDate, daysUntil)
}

function firstDuplicateDate(schedule: Schedule): string {
  const today = todayInTimezone(schedule.timezone_name)
  const anchor = nextWeekdayOnOrAfter(
    schedule.effective_from > today ? schedule.effective_from : today,
    schedule.weekday,
  )
  const sourceStillHasAnchor =
    schedule.effective_through === null || schedule.effective_through >= anchor
  return sourceStillHasAnchor ? addDays(anchor, 7) : anchor
}

function formatDate(value: string): string {
  return dateValue(value).toLocaleDateString('id-ID', {
    timeZone: 'UTC',
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  })
}

const duplicatePreviewDates = computed(() => {
  if (!duplicateTarget.value || !duplicateStartDate.value) return []
  let count = duplicateWeeks.value
  if (duplicateMode.value === 'through') {
    if (!duplicateThroughDate.value || duplicateThroughDate.value < duplicateStartDate.value) {
      return []
    }
    count =
      Math.floor(
        (dateValue(duplicateThroughDate.value).getTime() -
          dateValue(duplicateStartDate.value).getTime()) /
          (7 * 24 * 60 * 60 * 1000),
      ) + 1
  }
  if (!Number.isInteger(count) || count < 1 || count > 52) return []
  return Array.from({ length: count }, (_, index) => addDays(duplicateStartDate.value, index * 7))
})

const duplicateDateError = computed(() => {
  if (!duplicateTarget.value || !duplicateStartDate.value)
    return 'Pilih tanggal pertemuan berikutnya.'
  const selectedDate = dateValue(duplicateStartDate.value)
  const weekday = (selectedDate.getUTCDay() + 6) % 7
  if (weekday !== duplicateTarget.value.weekday) {
    return `Tanggal harus jatuh pada hari ${weekdayName(duplicateTarget.value.weekday)}.`
  }
  if (duplicateStartDate.value < firstDuplicateDate(duplicateTarget.value)) {
    return `Tanggal paling awal untuk salinan adalah ${formatDate(firstDuplicateDate(duplicateTarget.value))}.`
  }
  if (
    duplicateMode.value === 'weeks' &&
    (!Number.isInteger(duplicateWeeks.value) ||
      duplicateWeeks.value < 1 ||
      duplicateWeeks.value > 52)
  ) {
    return 'Masukkan jumlah 1 sampai 52 minggu.'
  }
  if (duplicateMode.value === 'through') {
    if (!duplicateThroughDate.value) return 'Pilih tanggal akhir.'
    if (duplicateThroughDate.value < duplicateStartDate.value) {
      return 'Tanggal akhir harus sama dengan atau setelah tanggal salinan pertama.'
    }
    if (duplicatePreviewDates.value.length === 0) {
      return 'Rentang maksimal adalah 52 pertemuan mingguan.'
    }
  }
  return null
})

const duplicateSourceWillEnd = computed(() => {
  if (!duplicateTarget.value || !duplicateStartDate.value) return false
  return (
    duplicateTarget.value.effective_through === null ||
    duplicateTarget.value.effective_through >= duplicateStartDate.value
  )
})

async function loadRows(): Promise<void> {
  isLoading.value = true
  errorMessage.value = null
  try {
    const today = todayLocalISO()
    const todayDate = dateValue(today)
    const weekdayFromMonday = (todayDate.getUTCDay() + 6) % 7
    const weekStartDate = addDays(today, -weekdayFromMonday)
    const weekEndDate = addDays(weekStartDate, 6)
    const dateRange =
      dayScope.value === 'today'
        ? { starts_on: today, ends_on: today }
        : dayScope.value === 'week'
          ? { starts_on: weekStartDate, ends_on: weekEndDate }
          : {}
    const result = await listSchedules({
      limit: pageSize,
      offset: page.value * pageSize,
      search: search.value || undefined,
      weekday: weekdayFilter.value === '' ? undefined : Number(weekdayFilter.value),
      is_active: statusFilter.value === 'all' ? undefined : statusFilter.value === 'active',
      ...dateRange,
    })
    rows.value = result.items
    total.value = result.pagination.total
  } catch (error) {
    errorMessage.value = formatError(error)
  } finally {
    isLoading.value = false
  }
}

async function loadOptions(): Promise<void> {
  try {
    const [classPage, labPage, teacherOptions] = await Promise.all([
      listClasses({ limit: 100, offset: 0, is_active: true }),
      listLaboratories({ limit: 100, offset: 0, is_active: true }),
      listScheduleTeachers(),
    ])
    classes.value = classPage.items
    laboratories.value = labPage.items
    teachers.value = teacherOptions
  } catch (error) {
    errorMessage.value = formatError(error)
  }
}

onMounted(async () => {
  await Promise.all([loadRows(), loadOptions()])
})

function submitFilters(): void {
  page.value = 0
  search.value = searchText.value.trim()
  void loadRows()
}

function openCreate(): void {
  editingId.value = null
  selected.value = null
  form.value = emptyForm()
  const ownTeacher = teachers.value.find((teacher) => teacher.id === auth.account?.id)
  form.value.teacher_user_id = ownTeacher?.id ?? teachers.value[0]?.id ?? ''
  formError.value = null
  isFormOpen.value = true
}

function openEdit(schedule: Schedule): void {
  selected.value = schedule
  editingId.value = schedule.id
  form.value = {
    class_id: schedule.class_id,
    laboratory_id: schedule.laboratory_id,
    teacher_user_id: schedule.teacher_user_id,
    subject: schedule.subject,
    weekday: schedule.weekday,
    start_time: displayTime(schedule.start_time),
    end_time: displayTime(schedule.end_time),
    timezone_name: schedule.timezone_name,
    effective_from: schedule.effective_from,
    effective_through: schedule.effective_through ?? '',
    is_active: schedule.is_active,
  }
  formError.value = null
  isFormOpen.value = true
}

function openDuplicate(schedule: Schedule): void {
  duplicateTarget.value = schedule
  duplicateMode.value = 'weeks'
  duplicateWeeks.value = 4
  duplicateStartDate.value = firstDuplicateDate(schedule)
  duplicateThroughDate.value = ''
  duplicateError.value = null
  selected.value = null
  isDuplicateOpen.value = true
}

function closeDuplicate(): void {
  if (isDuplicating.value) return
  isDuplicateOpen.value = false
  duplicateTarget.value = null
}

async function submitDuplicate(): Promise<void> {
  if (!duplicateTarget.value || duplicateDateError.value || isDuplicating.value) return
  duplicateError.value = null
  successMessage.value = null
  isDuplicating.value = true
  const body: ScheduleDuplicateRequest = {
    start_date: duplicateStartDate.value,
    ...(duplicateMode.value === 'weeks'
      ? { additional_weeks: duplicateWeeks.value }
      : { through_date: duplicateThroughDate.value }),
  }
  try {
    const result = await duplicateSchedule(duplicateTarget.value.id, body)
    const firstSubject = result.duplicates[0]?.subject
    const lastSubject = result.duplicates[result.duplicates.length - 1]?.subject
    successMessage.value = `${result.duplicates.length} jadwal berhasil dibuat: ${firstSubject} sampai ${lastSubject}.`
    isDuplicateOpen.value = false
    duplicateTarget.value = null
    await loadRows()
  } catch (error) {
    duplicateError.value = formatError(error)
  } finally {
    isDuplicating.value = false
  }
}

async function submitForm(): Promise<void> {
  formError.value = null
  const missing: string[] = []
  if (!form.value.class_id) missing.push('Kelas')
  if (!form.value.laboratory_id) missing.push('Laboratorium')
  if (!form.value.teacher_user_id) missing.push('Guru')
  if (!form.value.subject.trim()) missing.push('Nama pertemuan')
  if (missing.length) {
    formError.value = 'Lengkapi dulu: ' + missing.join(', ') + '.'
    return
  }
  isSaving.value = true
  const body = {
    class_id: form.value.class_id,
    laboratory_id: form.value.laboratory_id,
    teacher_user_id: form.value.teacher_user_id,
    subject: form.value.subject.trim(),
    weekday: Number(form.value.weekday),
    start_time: form.value.start_time,
    end_time: form.value.end_time,
    timezone_name: form.value.timezone_name.trim(),
    effective_from: form.value.effective_from,
    effective_through: form.value.effective_through || null,
  }
  try {
    if (editingId.value) {
      await updateSchedule(editingId.value, { ...body, is_active: form.value.is_active })
    } else {
      await createSchedule(body)
    }
    isFormOpen.value = false
    selected.value = null
    await loadRows()
  } catch (error) {
    formError.value = formatError(error)
  } finally {
    isSaving.value = false
  }
}

const isTeacher = computed(
  () =>
    (auth.account?.roles.includes('TEACHER') ?? false) &&
    !(auth.account?.roles.includes('ADMIN') ?? false),
)
const canManageSchedule = computed(() => {
  const roles = auth.account?.roles ?? []
  if (roles.includes('ADMIN') || roles.includes('TEACHER')) return true
  const perms = (auth.account?.permissions ?? []) as string[]
  return perms.includes('schedule_manage')
})
const dayScope = ref<'today' | 'week' | 'all'>('week')
const conflictAlternatives = computed(() =>
  laboratories.value.filter((lab) => lab.id !== form.value.laboratory_id).slice(0, 2),
)
const isConflictError = computed(() => /tabrakan|conflict/i.test(formError.value ?? ''))

function setScope(scope: 'today' | 'week' | 'all'): void {
  dayScope.value = scope
  if (scope === 'today') weekdayFilter.value = String((new Date().getDay() + 6) % 7)
  else weekdayFilter.value = ''
  page.value = 0
  void loadRows()
}

function changeWeekday(value: string): void {
  weekdayFilter.value = value
  const today = dateValue(todayLocalISO())
  const currentWeekday = String((today.getUTCDay() + 6) % 7)
  if (dayScope.value === 'today' && value !== currentWeekday) {
    dayScope.value = 'week'
  }
  page.value = 0
  void loadRows()
}

function changeStatus(value: string): void {
  statusFilter.value = value
  page.value = 0
  void loadRows()
}

function requestDelete(schedule: Schedule): void {
  pendingDelete.value = schedule
  deleteError.value = null
}

async function confirmDelete(): Promise<void> {
  if (!pendingDelete.value || isDeleting.value) return
  isDeleting.value = true
  deleteError.value = null
  try {
    const result = await deleteSchedule(pendingDelete.value.id)
    successMessage.value = result.message
    pendingDelete.value = null
    selected.value = null
    await loadRows()
  } catch (error) {
    deleteError.value = formatError(error)
  } finally {
    isDeleting.value = false
  }
}

function applyAltLab(laboratoryId: string): void {
  form.value.laboratory_id = laboratoryId
  formError.value = null
}

function goToPage(nextPage: number): void {
  if (nextPage < 0 || nextPage >= totalPages.value || nextPage === page.value) return
  page.value = nextPage
  void loadRows()
}
</script>

<template>
  <div class="st-page">
    <UiPageHeader
      :title="isTeacher ? 'Jadwal Saya' : 'Jadwal Praktikum'"
      :description="
        isTeacher
          ? 'Jadwal praktikum untuk kelas penugasan Anda.'
          : 'Agenda praktikum semua kelas, lab, dan guru.'
      "
    >
      <template #actions>
        <UiButton v-if="canManageSchedule" variant="primary" @click="openCreate"
          >+ Tambah Jadwal</UiButton
        >
        <span v-else class="st-table__muted">Mode baca saja - membutuhkan izin Kelola Jadwal.</span>
      </template>
    </UiPageHeader>

    <p v-if="errorMessage" class="st-alert st-alert--error" role="alert">{{ errorMessage }}</p>
    <p v-if="successMessage" class="st-alert st-alert--success" role="status">
      {{ successMessage }}
    </p>

    <div class="st-toolbar">
      <div class="st-scope" role="group" aria-label="Rentang jadwal">
        <button
          type="button"
          :class="{ 'st-scope--active': dayScope === 'today' }"
          @click="setScope('today')"
        >
          Hari Ini
        </button>
        <button
          type="button"
          :class="{ 'st-scope--active': dayScope === 'week' }"
          @click="setScope('week')"
        >
          Minggu Ini
        </button>
        <button
          type="button"
          :class="{ 'st-scope--active': dayScope === 'all' }"
          @click="setScope('all')"
        >
          Semua Jadwal
        </button>
      </div>
      <UiSelect
        :model-value="weekdayFilter"
        aria-label="Filter hari"
        @update:model-value="changeWeekday"
      >
        <option value="">Semua Hari</option>
        <option v-for="(day, index) in weekdays" :key="day" :value="index">{{ day }}</option>
      </UiSelect>
      <UiSelect
        :model-value="statusFilter"
        aria-label="Filter status"
        @update:model-value="changeStatus"
      >
        <option value="active">Terjadwal</option>
        <option value="inactive">Nonaktif</option>
        <option value="all">Semua status</option>
      </UiSelect>
    </div>

    <form class="st-toolbar" @submit.prevent="submitFilters">
      <UiSearchInput
        v-model="searchText"
        placeholder="Cari mata pelajaran, kelas, atau lab…"
        aria-label="Cari jadwal"
      />
      <span class="st-toolbar__spacer" />
      <UiButton variant="secondary" type="submit">Cari</UiButton>
    </form>

    <p v-if="isLoading" class="st-table__muted">Memuat jadwal…</p>
    <UiEmptyState
      v-else-if="!rows.length && !errorMessage"
      title="Belum ada jadwal yang cocok"
      description="Ubah filter atau tambah jadwal baru."
    />
    <div v-else class="st-grid2">
      <article v-for="schedule in rows" :key="schedule.id" class="st-card st-schedule">
        <div class="st-schedule__time">
          <strong>{{ displayTime(schedule.start_time) }}</strong>
          <small>sampai</small>
          <strong>{{ displayTime(schedule.end_time) }} WIB</strong>
        </div>
        <div class="st-schedule__main">
          <div class="st-schedule__tags">
            <UiBadge tone="info">{{ weekdayName(schedule.weekday) }}</UiBadge>
            <UiBadge :tone="schedule.is_active ? 'present' : 'neutral'">{{
              schedule.is_active ? 'Terjadwal' : 'Nonaktif'
            }}</UiBadge>
          </div>
          <h2 class="st-card__title">{{ schedule.subject }}</h2>
          <p class="st-table__muted">
            {{ schedule.laboratory_name }} · {{ schedule.class_name }} · {{ schedule.teacher_name }}
          </p>
          <div class="st-schedule__actions">
            <button type="button" class="st-link" @click="selected = schedule">Detail</button>
            <button
              v-if="canManageSchedule"
              type="button"
              class="st-link"
              @click="openEdit(schedule)"
            >
              Ubah
            </button>
            <button
              v-if="canManageSchedule && schedule.is_active"
              type="button"
              class="st-link"
              :data-testid="`duplicate-schedule-${schedule.id}`"
              @click="openDuplicate(schedule)"
            >
              Duplikasi mingguan
            </button>
            <button
              v-if="canManageSchedule"
              type="button"
              class="st-link st-link--danger"
              :data-testid="`delete-schedule-${schedule.id}`"
              @click="requestDelete(schedule)"
            >
              Hapus
            </button>
          </div>
        </div>
      </article>
    </div>

    <UiPagination
      :page="page + 1"
      :total-pages="totalPages"
      :total="total"
      label="jadwal"
      @update:page="goToPage($event - 1)"
    />

    <!-- Detail jadwal -->
    <UiDrawer
      v-if="selected"
      :title="selected.subject"
      subtitle="Detail jadwal praktikum"
      @close="selected = null"
    >
      <dl class="st-def">
        <div>
          <dt>Kelas</dt>
          <dd>{{ selected.class_name }}</dd>
        </div>
        <div>
          <dt>Laboratorium</dt>
          <dd>{{ selected.laboratory_name }}</dd>
        </div>
        <div>
          <dt>Guru</dt>
          <dd>{{ selected.teacher_name }}</dd>
        </div>
        <div>
          <dt>Waktu</dt>
          <dd>
            {{ weekdayName(selected.weekday) }}, {{ displayTime(selected.start_time) }}-{{
              displayTime(selected.end_time)
            }}
            · {{ selected.timezone_name }}
          </dd>
        </div>
        <div>
          <dt>Berlaku</dt>
          <dd>{{ selected.effective_from }}-{{ selected.effective_through ?? 'seterusnya' }}</dd>
        </div>
        <div>
          <dt>Status</dt>
          <dd>{{ selected.is_active ? 'Aktif' : 'Nonaktif' }}</dd>
        </div>
      </dl>
      <template #footer>
        <UiButton variant="secondary" @click="selected = null">Tutup</UiButton>
        <UiButton
          v-if="canManageSchedule && selected.is_active"
          variant="secondary"
          @click="openDuplicate(selected)"
        >
          Duplikasi mingguan
        </UiButton>
        <UiButton v-if="canManageSchedule" variant="primary" @click="selected && openEdit(selected)"
          >Ubah Jadwal</UiButton
        >
        <UiButton v-if="canManageSchedule" variant="danger-soft" @click="requestDelete(selected)">
          Hapus Jadwal
        </UiButton>
      </template>
    </UiDrawer>

    <UiModal v-if="pendingDelete" title="Hapus jadwal?" @close="pendingDelete = null">
      <p>
        Jadwal <strong>{{ pendingDelete.subject }}</strong> akan diperiksa keterkaitannya. Jika
        sudah memiliki riwayat sesi, jadwal diarsipkan agar presensi tetap tersimpan. Jika belum
        pernah dipakai, jadwal dihapus permanen.
      </p>
      <p class="st-table__muted">Tutup sesi yang masih berlangsung sebelum menghapus jadwal.</p>
      <p v-if="deleteError" class="st-alert st-alert--error" role="alert">{{ deleteError }}</p>
      <template #footer>
        <UiButton variant="secondary" :disabled="isDeleting" @click="pendingDelete = null">
          Batal
        </UiButton>
        <UiButton
          variant="danger"
          :disabled="isDeleting"
          data-testid="confirm-delete-schedule"
          @click="confirmDelete"
        >
          {{ isDeleting ? 'Memproses…' : 'Lanjutkan' }}
        </UiButton>
      </template>
    </UiModal>

    <UiModal
      v-if="isDuplicateOpen && duplicateTarget"
      title="Duplikasi jadwal mingguan"
      @close="closeDuplicate"
    >
      <p class="st-table__muted">
        Buat pertemuan baru pada hari, jam, kelas, laboratorium, dan guru yang sama. Nama pertemuan
        dibuat berurutan, misalnya “Pertemuan 2 - {{ duplicateTarget.subject }}”.
      </p>
      <p class="st-alert st-alert--warning" role="note">
        {{
          duplicateSourceWillEnd
            ? `Jadwal sumber akan berakhir pada ${formatDate(addDays(duplicateStartDate, -1))}. Pertemuan baru dibuat sebagai jadwal satu kali supaya tidak ada sesi ganda; setelah salinan terakhir, jadwal ini tidak berulang lagi.`
            : 'Jadwal sumber sudah berakhir sebelum tanggal salinan pertama. Jadwal sumber tetap seperti sekarang; salinan baru dibuat sebagai jadwal satu kali.'
        }}
      </p>
      <p v-if="duplicateError" class="st-alert st-alert--error" role="alert">
        {{ duplicateError }}
      </p>
      <form id="duplicate-schedule-form" class="st-form" @submit.prevent="submitDuplicate">
        <UiField
          label="Tanggal salinan pertama"
          :hint="`Jadwal sumber: ${weekdayName(duplicateTarget.weekday)}, ${displayTime(duplicateTarget.start_time)}–${displayTime(duplicateTarget.end_time)} · tanggal harus pada hari yang sama.`"
          :error="duplicateDateError"
        >
          <UiInput
            v-model="duplicateStartDate"
            type="date"
            required
            :min="firstDuplicateDate(duplicateTarget)"
            data-testid="duplicate-start-date"
          />
        </UiField>
        <fieldset class="st-duplicate-mode">
          <legend>Jumlah pertemuan</legend>
          <label
            class="st-radio-card"
            :class="{ 'st-radio-card--active': duplicateMode === 'weeks' }"
          >
            <input v-model="duplicateMode" type="radio" value="weeks" />
            <span><strong>Jumlah minggu</strong><small>Atur banyak salinan</small></span>
          </label>
          <label
            class="st-radio-card"
            :class="{ 'st-radio-card--active': duplicateMode === 'through' }"
          >
            <input v-model="duplicateMode" type="radio" value="through" />
            <span
              ><strong>Sampai tanggal</strong
              ><small>Termasuk pertemuan pada hari jadwal</small></span
            >
          </label>
        </fieldset>
        <UiField
          v-if="duplicateMode === 'weeks'"
          label="Minggu tambahan"
          hint="1 sampai 52 pertemuan"
        >
          <UiInput
            v-model.number="duplicateWeeks"
            type="number"
            min="1"
            max="52"
            required
            data-testid="duplicate-weeks"
          />
        </UiField>
        <UiField
          v-else
          label="Tanggal akhir"
          hint="Pertemuan dibuat setiap 7 hari sampai tanggal ini."
        >
          <UiInput
            v-model="duplicateThroughDate"
            type="date"
            required
            :min="duplicateStartDate"
            data-testid="duplicate-through-date"
          />
        </UiField>
      </form>
      <div v-if="duplicatePreviewDates.length" class="st-duplicate-preview" aria-live="polite">
        <strong>{{ duplicatePreviewDates.length }} pertemuan akan dibuat</strong>
        <ul>
          <li v-for="date in duplicatePreviewDates.slice(0, 4)" :key="date">
            {{ weekdayName(duplicateTarget.weekday) }}, {{ formatDate(date) }}
          </li>
          <li v-if="duplicatePreviewDates.length > 4">
            dan {{ duplicatePreviewDates.length - 4 }} pertemuan berikutnya
          </li>
        </ul>
        <small>Nomor pertemuan berlanjut otomatis dari jadwal dan pertemuan yang sudah ada.</small>
      </div>
      <template #footer>
        <UiButton variant="secondary" :disabled="isDuplicating" @click="closeDuplicate">
          Batal
        </UiButton>
        <UiButton
          variant="primary"
          type="submit"
          :disabled="isDuplicating || Boolean(duplicateDateError)"
          form="duplicate-schedule-form"
          data-testid="submit-schedule-duplicate"
          @click="submitDuplicate"
        >
          {{ isDuplicating ? 'Membuat…' : `Buat ${duplicatePreviewDates.length} pertemuan` }}
        </UiButton>
      </template>
    </UiModal>

    <!-- Form tambah/ubah (B02-10) -->
    <UiDrawer
      v-if="isFormOpen"
      :title="editingId ? 'Ubah Jadwal Praktikum' : 'Tambah Jadwal Praktikum'"
      subtitle="Atur pertemuan praktikum rutin mingguan untuk kelas penugasan."
      @close="isFormOpen = false"
    >
      <p v-if="formError && !isConflictError" class="st-alert st-alert--error" role="alert">
        {{ formError }}
      </p>
      <div v-if="isConflictError" class="st-alert st-alert--error" role="alert">
        <strong>Konflik Jadwal Laboratorium Terdeteksi</strong><br />
        {{ formError }}<br />
        <span v-if="conflictAlternatives.length">
          Silakan pilih waktu lain atau
          <button
            v-for="alt in conflictAlternatives"
            :key="alt.id"
            type="button"
            class="st-link"
            @click="applyAltLab(alt.id)"
          >
            Pindah ke {{ alt.name }}
          </button>
        </span>
      </div>
      <form @submit.prevent="submitForm">
        <UiField label="Pilih Kelas Praktikum" required>
          <UiSelect v-model="form.class_id" required>
            <option value="" disabled>Pilih kelas aktif</option>
            <option v-for="schoolClass in classes" :key="schoolClass.id" :value="schoolClass.id">
              {{ schoolClass.code }} - {{ schoolClass.name }}
            </option>
          </UiSelect>
        </UiField>
        <UiField label="Nama Pertemuan / Praktikum" required>
          <UiInput v-model="form.subject" required name="subject" />
        </UiField>
        <UiField label="Hari" required>
          <UiSelect
            :model-value="form.weekday"
            required
            @update:model-value="form.weekday = Number($event)"
          >
            <option v-for="(day, index) in weekdays" :key="day" :value="index">{{ day }}</option>
          </UiSelect>
        </UiField>
        <div class="st-grid2">
          <UiField label="Jam Mulai" required>
            <UiInput v-model="form.start_time" required type="time" name="start_time" />
          </UiField>
          <UiField label="Jam Selesai" required>
            <UiInput v-model="form.end_time" required type="time" name="end_time" />
          </UiField>
        </div>
        <UiField label="Pilihan Laboratorium" required>
          <UiSelect v-model="form.laboratory_id" required>
            <option value="" disabled>Pilih laboratorium aktif</option>
            <option v-for="lab in laboratories" :key="lab.id" :value="lab.id">
              {{ lab.name }}
            </option>
          </UiSelect>
        </UiField>
        <UiField label="Guru" required>
          <UiSelect v-model="form.teacher_user_id" required :disabled="!canAssignTeacher">
            <option value="" disabled>Pilih guru</option>
            <option v-for="teacher in teachers" :key="teacher.id" :value="teacher.id">
              {{ teacher.full_name }} -
              {{
                teacher.opening_mode === 'automatic'
                  ? 'otomatis sesuai jadwal'
                  : 'membuka sesi sendiri'
              }}
            </option>
          </UiSelect>
        </UiField>
        <div class="st-grid2">
          <UiField label="Tanggal Mulai Berlaku" required>
            <UiInput v-model="form.effective_from" required type="date" name="effective_from" />
          </UiField>
          <UiField
            label="Tanggal Akhir Berlaku"
            hint="Kosongkan jika tidak memiliki tanggal akhir."
          >
            <UiInput
              v-model="form.effective_through"
              type="date"
              name="effective_through"
              :min="form.effective_from"
            />
          </UiField>
        </div>
        <UiField v-if="editingId" label="Status">
          <label class="st-radio-card" :class="{ 'st-radio-card--active': form.is_active }">
            <input v-model="form.is_active" type="checkbox" /> Jadwal aktif
          </label>
        </UiField>
      </form>
      <template #footer>
        <UiButton variant="secondary" @click="isFormOpen = false">Batal</UiButton>
        <UiButton variant="primary" :disabled="isSaving" @click="submitForm">{{
          isSaving ? 'Menyimpan…' : 'Simpan jadwal'
        }}</UiButton>
      </template>
    </UiDrawer>
  </div>
</template>
