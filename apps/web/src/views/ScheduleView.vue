<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  ApiError,
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
  const localDate = new Date(now.getTime() - now.getTimezoneOffset() * 60_000)
    .toISOString()
    .slice(0, 10)
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
  if (error instanceof ApiError) {
    const details = error.details?.map((item) => `${item.field}: ${item.message}`)
    return details?.length ? details.join(' · ') : error.message
  }
  return 'Permintaan tidak dapat diproses. Coba lagi.'
}

function weekdayName(day: number): string {
  return weekdays[day] ?? '—'
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

function goToPage(nextPage: number): void {
  if (nextPage < 0 || nextPage >= totalPages.value || nextPage === page.value) return
  page.value = nextPage
  void loadRows()
}
</script>

<template>
  <section class="master-data schedule-view" aria-label="Jadwal praktikum">
    <p class="schedule-view__hint">
      Jadwal berulang setiap minggu sesuai zona waktu dan rentang tanggal yang dipilih.
    </p>

    <div class="master-data__toolbar">
      <form class="master-data__search" role="search" @submit.prevent="submitFilters">
        <label class="visually-hidden" for="schedule-search">Cari jadwal praktikum</label>
        <input
          id="schedule-search"
          v-model="searchText"
          type="search"
          placeholder="Cari mata pelajaran, kelas, atau lab"
        />
        <button class="button button--secondary" type="submit">Cari</button>
      </form>
      <label class="schedule-view__filter">
        <span class="visually-hidden">Filter hari</span>
        <select v-model="weekdayFilter" aria-label="Filter hari" @change="submitFilters">
          <option value="">Semua hari</option>
          <option v-for="(day, index) in weekdays" :key="day" :value="index">{{ day }}</option>
        </select>
      </label>
      <label class="schedule-view__filter">
        <span class="visually-hidden">Filter status</span>
        <select v-model="statusFilter" aria-label="Filter status" @change="submitFilters">
          <option value="active">Aktif</option>
          <option value="inactive">Nonaktif</option>
          <option value="all">Semua status</option>
        </select>
      </label>
      <button class="button button--primary" data-testid="create-schedule" @click="openCreate">
        Tambah jadwal
      </button>
    </div>

    <p v-if="errorMessage" class="master-data__alert" role="alert">{{ errorMessage }}</p>

    <section v-if="isFormOpen" class="master-data__panel" aria-labelledby="schedule-form-title">
      <div class="master-data__panel-heading">
        <div>
          <p class="master-data__eyebrow">{{ editingId ? 'Perbarui' : 'Jadwal baru' }}</p>
          <h2 id="schedule-form-title">{{ editingId ? 'Ubah jadwal' : 'Tambah jadwal' }}</h2>
        </div>
        <button class="button button--text" type="button" @click="isFormOpen = false">Tutup</button>
      </div>
      <form class="master-data__form schedule-view__form" @submit.prevent="submitForm">
        <label
          >Mata pelajaran<input v-model="form.subject" required maxlength="120" autocomplete="off"
        /></label>
        <label
          >Kelas<select v-model="form.class_id" required>
            <option value="" disabled>Pilih kelas aktif</option>
            <option v-for="schoolClass in classes" :key="schoolClass.id" :value="schoolClass.id">
              {{ schoolClass.name }} · {{ schoolClass.academic_year }}
            </option>
          </select></label
        >
        <label
          >Laboratorium<select v-model="form.laboratory_id" required>
            <option value="" disabled>Pilih laboratorium aktif</option>
            <option v-for="lab in laboratories" :key="lab.id" :value="lab.id">
              {{ lab.name }} · {{ lab.code }}
            </option>
          </select></label
        >
        <label
          >Guru<select v-model="form.teacher_user_id" required :disabled="!canAssignTeacher">
            <option value="" disabled>Pilih guru</option>
            <option v-for="teacher in teachers" :key="teacher.id" :value="teacher.id">
              {{ teacher.full_name }}
            </option>
          </select></label
        >
        <label
          >Hari<select v-model.number="form.weekday" required>
            <option v-for="(day, index) in weekdays" :key="day" :value="index">{{ day }}</option>
          </select></label
        >
        <label>Jam mulai<input v-model="form.start_time" required type="time" /></label>
        <label>Jam selesai<input v-model="form.end_time" required type="time" /></label>
        <label
          >Zona waktu<input
            v-model="form.timezone_name"
            required
            maxlength="64"
            placeholder="Asia/Jakarta"
        /></label>
        <label
          >Tanggal mulai berlaku<input v-model="form.effective_from" required type="date"
        /></label>
        <label
          >Tanggal akhir berlaku<input
            v-model="form.effective_through"
            type="date"
            :min="form.effective_from"
          /><small>Kosongkan jika tidak memiliki tanggal akhir.</small></label
        >
        <label v-if="editingId" class="master-data__checkbox">
          <input v-model="form.is_active" type="checkbox" /> Jadwal aktif
        </label>
        <p v-if="formError" class="master-data__alert schedule-view__form-error" role="alert">
          {{ formError }}
        </p>
        <div class="master-data__form-actions">
          <button class="button button--secondary" type="button" @click="isFormOpen = false">
            Batal
          </button>
          <button class="button button--primary" type="submit" :disabled="isSaving">
            {{ isSaving ? 'Menyimpan…' : 'Simpan jadwal' }}
          </button>
        </div>
      </form>
    </section>

    <div class="master-data__table-wrap">
      <table class="master-data__table schedule-view__table">
        <thead>
          <tr>
            <th scope="col">Hari & waktu</th>
            <th scope="col">Praktikum</th>
            <th scope="col">Kelas</th>
            <th scope="col">Laboratorium</th>
            <th scope="col">Guru</th>
            <th scope="col">Status</th>
            <th scope="col">Aksi</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="isLoading">
            <td colspan="7" class="master-data__empty">Memuat jadwal…</td>
          </tr>
          <tr v-else-if="rows.length === 0">
            <td colspan="7" class="master-data__empty">Belum ada jadwal yang cocok.</td>
          </tr>
          <tr v-for="schedule in rows" v-else :key="schedule.id">
            <td data-label="Hari & waktu">
              <strong>{{ weekdayName(schedule.weekday) }}</strong>
              <small
                >{{ displayTime(schedule.start_time) }}–{{ displayTime(schedule.end_time) }}</small
              >
            </td>
            <td data-label="Praktikum">{{ schedule.subject }}</td>
            <td data-label="Kelas">{{ schedule.class_name }}</td>
            <td data-label="Laboratorium">{{ schedule.laboratory_name }}</td>
            <td data-label="Guru">{{ schedule.teacher_name }}</td>
            <td data-label="Status">
              <span
                class="status-badge"
                :class="schedule.is_active ? 'status-badge--active' : 'status-badge--inactive'"
                >{{ schedule.is_active ? 'Aktif' : 'Nonaktif' }}</span
              >
            </td>
            <td class="master-data__actions" data-label="Aksi">
              <button class="button button--text" type="button" @click="selected = schedule">
                Detail
              </button>
              <button class="button button--text" type="button" @click="openEdit(schedule)">
                Ubah
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="master-data__pagination" aria-label="Navigasi halaman jadwal">
      <span>{{
        total === 0
          ? '0 jadwal'
          : `${page * pageSize + 1}–${Math.min((page + 1) * pageSize, total)} dari ${total}`
      }}</span>
      <div>
        <button
          class="button button--secondary"
          type="button"
          :disabled="page === 0"
          @click="goToPage(page - 1)"
        >
          Sebelumnya
        </button>
        <span>Halaman {{ page + 1 }} dari {{ totalPages }}</span>
        <button
          class="button button--secondary"
          type="button"
          :disabled="page + 1 >= totalPages"
          @click="goToPage(page + 1)"
        >
          Berikutnya
        </button>
      </div>
    </div>

    <section v-if="selected" class="master-data__panel" aria-labelledby="schedule-detail-title">
      <div class="master-data__panel-heading">
        <div>
          <p class="master-data__eyebrow">Detail jadwal</p>
          <h2 id="schedule-detail-title">{{ selected.subject }}</h2>
        </div>
        <button class="button button--text" type="button" @click="selected = null">
          Tutup detail
        </button>
      </div>
      <dl class="master-data__details schedule-view__details">
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
            {{ weekdayName(selected.weekday) }}, {{ displayTime(selected.start_time) }}–{{
              displayTime(selected.end_time)
            }}
            · {{ selected.timezone_name }}
          </dd>
        </div>
        <div>
          <dt>Berlaku</dt>
          <dd>{{ selected.effective_from }}–{{ selected.effective_through ?? 'seterusnya' }}</dd>
        </div>
        <div>
          <dt>Status</dt>
          <dd>{{ selected.is_active ? 'Aktif' : 'Nonaktif' }}</dd>
        </div>
      </dl>
    </section>
  </section>
</template>
