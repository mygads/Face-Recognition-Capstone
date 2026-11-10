<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { todayLocalISO } from '../utils/dateFormat'
import {
  createSchedule,
  listClasses,
  listLaboratories,
  listScheduleTeachers,
  listSchedules,
  updateSchedule,
  type Laboratory,
  type Schedule,
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

async function loadRows(): Promise<void> {
  isLoading.value = true
  errorMessage.value = null
  try {
    const result = await listSchedules({
      limit: pageSize,
      offset: page.value * pageSize,
      search: search.value || undefined,
      weekday: weekdayFilter.value === '' ? undefined : Number(weekdayFilter.value),
      is_active: statusFilter.value === 'all' ? undefined : statusFilter.value === 'active',
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
      <UiSelect v-model="weekdayFilter" aria-label="Filter hari" @change="submitFilters">
        <option value="">Semua Hari</option>
        <option v-for="(day, index) in weekdays" :key="day" :value="index">{{ day }}</option>
      </UiSelect>
      <UiSelect v-model="statusFilter" aria-label="Filter status" @change="submitFilters">
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
        <UiButton v-if="canManageSchedule" variant="primary" @click="selected && openEdit(selected)"
          >Ubah Jadwal</UiButton
        >
      </template>
    </UiDrawer>

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
