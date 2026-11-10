<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import {
  ApiError,
  getAttendanceReportSummary,
  getMyClass,
  listClassLaboratories,
  listLaboratories,
  listMyClasses,
  listSchedules,
  listTeacherAssignments,
  type ClassDetails,
  type SchoolClass,
} from '../api/client'
import UiAvatar from '../components/ui/UiAvatar.vue'
import UiBadge from '../components/ui/UiBadge.vue'
import UiButton from '../components/ui/UiButton.vue'
import UiCard from '../components/ui/UiCard.vue'
import UiEmptyState from '../components/ui/UiEmptyState.vue'
import UiPageHeader from '../components/ui/UiPageHeader.vue'
import UiSearchInput from '../components/ui/UiSearchInput.vue'
import UiSelect from '../components/ui/UiSelect.vue'

interface ClassAssignment {
  starts_on: string | null
  ends_on: string | null
  is_substitute: boolean
}

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const classes = ref<SchoolClass[]>([])
const counts = ref<Record<string, number | null>>({})
const assignments = ref<Record<string, ClassAssignment>>({})
const classLabs = ref<Record<string, string[]>>({})
const attendanceAvg = ref<Record<string, number | null>>({})
const attendanceDetail = ref<Record<string, string>>({})
const canReadReports = computed(
  () =>
    auth.account?.roles.includes('ADMIN') ||
    (auth.account?.permissions ?? []).includes('reports_read'),
)

function semesterRangeFor(academicYear: string): { starts_on: string; ends_on: string } {
  const startYear = Number(academicYear.split('-')[0]) || new Date().getFullYear()
  const today = new Date()
  const pad = (n: number): string => String(n).padStart(2, '0')
  const ends_on = `${today.getFullYear()}-${pad(today.getMonth() + 1)}-${pad(today.getDate())}`
  return { starts_on: `${startYear}-07-01`, ends_on }
}

function ringOffset(pct: number | null): number {
  if (pct === null) return 0
  const c = 2 * Math.PI * 15.5
  return c * (1 - Math.min(100, Math.max(0, pct)) / 100)
}

async function loadAttendanceAverages(items: SchoolClass[]): Promise<void> {
  if (!canReadReports.value) return
  await Promise.all(
    items.map(async (cls) => {
      try {
        const range = semesterRangeFor(cls.academic_year)
        const summary = await getAttendanceReportSummary({
          starts_on: range.starts_on,
          ends_on: range.ends_on,
          class_id: cls.id,
          limit: 1,
          offset: 0,
        })
        const total = summary.total_rows ?? 0
        if (!total) {
          attendanceAvg.value[cls.id] = null
          attendanceDetail.value[cls.id] = 'Belum ada sesi pada periode ini.'
          return
        }
        const present = (summary.present_count ?? 0) + (summary.late_count ?? 0)
        const pct = (present / total) * 100
        attendanceAvg.value[cls.id] = Math.round(pct * 10) / 10
        attendanceDetail.value[cls.id] =
          `${summary.present_count ?? 0} hadir, ${summary.late_count ?? 0} terlambat dari ${total} catatan`
      } catch {
        attendanceAvg.value[cls.id] = null
        attendanceDetail.value[cls.id] = 'Ringkasan belum dapat dimuat.'
      }
    }),
  )
}

function skLabel(classId: string): string {
  const a = assignmentOf(classId)
  if (!a) return 'SK penugasan: belum tercatat di sistem'
  if (a.ends_on) return `Penugasan aktif sampai ${a.ends_on} - SK belum tercatat di sistem`
  return 'Penugasan aktif - SK belum tercatat di sistem'
}
const nextSchedules = ref<
  Record<
    string,
    { subject: string; weekday: number; start: string; end: string; lab: string } | null
  >
>({})
const weekdays = ['Senin', 'Selasa', 'Rabu', 'Kamis', 'Jumat', 'Sabtu', 'Minggu']

function nextScheduleFor(list: { weekday: number }[]): number {
  const today = (new Date().getDay() + 6) % 7
  let best = -1
  let bestDelta = 8
  list.forEach((item, index) => {
    const delta = (item.weekday - today + 7) % 7
    if (delta < bestDelta) {
      bestDelta = delta
      best = index
    }
  })
  return best
}
const detail = ref<ClassDetails | null>(null)
const isLoading = ref(false)
const detailLoading = ref(false)
const error = ref<string | null>(null)
const detailError = ref<string | null>(null)
const searchText = ref('')
const statusFilter = ref('')

const activeClassId = computed(() => {
  const id = route.params.classId
  return typeof id === 'string' ? id : ''
})
const activeCount = computed(() => classes.value.filter((c) => c.is_active).length)
const periodLabel = computed(() => {
  const years = [...new Set(classes.value.map((c) => c.academic_year))]
  return years.length ? years.join(', ') : '-'
})
const todayLabel = computed(() =>
  new Date().toLocaleDateString('id-ID', {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  }),
)
const filteredStudents = computed(() => {
  const q = searchText.value.trim().toLowerCase()
  const members = detail.value?.students ?? []
  return members.filter((s) => {
    if (statusFilter.value === 'active' && !s.is_active) return false
    if (statusFilter.value === 'inactive' && s.is_active) return false
    if (!q) return true
    return s.full_name.toLowerCase().includes(q) || s.student_number.toLowerCase().includes(q)
  })
})

function formatError(err: unknown): string {
  if (err instanceof ApiError) return err.message
  return 'Data kelas belum dapat dimuat.'
}

function assignmentOf(classId: string): ClassAssignment | null {
  return assignments.value[classId] ?? null
}

function assignmentLabel(classId: string): string {
  const a = assignmentOf(classId)
  if (!a) return 'Periode penugasan berlaku'
  if (a.ends_on) return `Aktif sampai ${a.ends_on}`
  return 'Penugasan aktif'
}

async function loadClasses(): Promise<void> {
  isLoading.value = true
  error.value = null
  try {
    const page = await listMyClasses({ limit: 50, offset: 0 })
    classes.value = page.items
    const accountId = auth.account?.id
    if (accountId) {
      try {
        const result = await listTeacherAssignments(accountId)
        const map: Record<string, ClassAssignment> = {}
        for (const item of result.items) {
          map[item.class_id] = {
            starts_on: item.starts_on,
            ends_on: item.ends_on,
            is_substitute: item.is_substitute,
          }
        }
        assignments.value = map
      } catch {
        assignments.value = {}
      }
    }
    try {
      const [pairs, labs, schedules] = await Promise.all([
        listClassLaboratories().catch(() => ({ items: [] })),
        listLaboratories({ limit: 50, offset: 0 }).catch(() => ({ items: [] })),
        listSchedules({ limit: 100, offset: 0, is_active: true }).catch(() => ({ items: [] })),
      ])
      const labNames = new Map((labs.items ?? []).map((lab) => [lab.id, lab.name]))
      const labMap: Record<string, string[]> = {}
      const pushLab = (classId: string, name: string) => {
        const list = (labMap[classId] ??= [])
        if (name && !list.includes(name)) list.push(name)
      }
      for (const item of schedules.items ?? []) pushLab(item.class_id, item.laboratory_name)
      for (const pair of pairs.items ?? []) {
        const name = labNames.get(pair.laboratory_id)
        if (name) pushLab(pair.class_id, name)
      }
      classLabs.value = labMap
      const schedMap: Record<
        string,
        { subject: string; weekday: number; start: string; end: string; lab: string } | null
      > = {}
      for (const cls of page.items) {
        const mine = (schedules.items ?? []).filter((item) => item.class_id === cls.id)
        const pick = nextScheduleFor(mine)
        schedMap[cls.id] =
          pick >= 0
            ? {
                subject: mine[pick].subject,
                weekday: mine[pick].weekday,
                start: mine[pick].start_time.slice(0, 5),
                end: mine[pick].end_time.slice(0, 5),
                lab: mine[pick].laboratory_name,
              }
            : null
      }
      nextSchedules.value = schedMap
    } catch {
      classLabs.value = {}
      nextSchedules.value = {}
    }
    void loadAttendanceAverages(page.items)
    const settled = await Promise.allSettled(
      page.items.map(async (cls) => ({ id: cls.id, detail: await getMyClass(cls.id) })),
    )
    const next: Record<string, number | null> = {}
    for (const entry of settled) {
      if (entry.status === 'fulfilled') next[entry.value.id] = entry.value.detail.students.length
      else next[''] = null
    }
    counts.value = next
    if (activeClassId.value) await loadDetail(activeClassId.value)
  } catch (err) {
    error.value = formatError(err)
  } finally {
    isLoading.value = false
  }
}

async function loadDetail(classId: string): Promise<void> {
  detailLoading.value = true
  detailError.value = null
  try {
    detail.value = await getMyClass(classId)
  } catch (err) {
    detailError.value = formatError(err)
    detail.value = null
  } finally {
    detailLoading.value = false
  }
}

function openRoster(classId: string): void {
  void router.push(`/app/my-classes/${classId}`)
}

function backToList(): void {
  detail.value = null
  void router.push('/app/my-classes')
}

watch(
  () => route.params.classId,
  (next) => {
    if (typeof next === 'string' && next) void loadDetail(next)
    else detail.value = null
  },
)

onMounted(() => void loadClasses())
</script>

<template>
  <div class="st-page">
    <p v-if="error" class="st-alert st-alert--error" role="alert">{{ error }}</p>

    <!-- ============ DAFTAR KELAS PENUGASAN (B02-07) ============ -->
    <section v-if="!activeClassId">
      <UiPageHeader
        title="Kelas Saya"
        description="Daftar kelas penugasan mengajar praktikum yang menjadi tanggung jawab Anda."
      >
        <template #actions>
          <div class="st-statline">
            <span class="st-table__muted">Total Penugasan Aktif:</span>
            <strong>{{ activeCount }} Kelas Aktif</strong>
          </div>
        </template>
      </UiPageHeader>

      <div class="st-toolbar">
        <span class="st-chip">Periode: {{ periodLabel }}</span>
        <span class="st-chip">Status: Aktif ({{ activeCount }})</span>
        <span class="st-toolbar__spacer" />
        <span class="st-chip st-chip--muted">{{ todayLabel }}</span>
      </div>

      <p v-if="isLoading" class="st-table__muted">Memuat kelas penugasan…</p>
      <UiEmptyState
        v-else-if="!classes.length && !error"
        title="Belum ada kelas yang ditugaskan"
        description="Minta admin menetapkan penugasan kelas pada menu Akun staf."
      />
      <div v-else class="st-grid2">
        <UiCard v-for="cls in classes" :key="cls.id">
          <template #header>
            <span class="st-chip">Kelas Penugasan Aktif</span>
            <span v-if="assignmentOf(cls.id)?.is_substitute" class="st-chip st-chip--muted"
              >Pengampu Pengganti</span
            >
            <span class="st-table__muted">{{ cls.academic_year }}</span>
          </template>
          <h2 class="st-card__title">{{ cls.code }}</h2>
          <p class="st-table__muted">{{ cls.name }}</p>
          <div class="st-classring">
            <svg
              class="st-ring"
              viewBox="0 0 40 40"
              role="img"
              :aria-label="`Rata-rata kehadiran ${attendanceAvg[cls.id] === null || attendanceAvg[cls.id] === undefined ? 'belum ada data' : attendanceAvg[cls.id] + ' persen'}`"
            >
              <circle class="st-ring__track" cx="20" cy="20" r="15.5" />
              <circle
                class="st-ring__value"
                cx="20"
                cy="20"
                r="15.5"
                :stroke-dashoffset="ringOffset(attendanceAvg[cls.id] ?? null)"
              />
              <text x="20" y="20" class="st-ring__text">
                {{
                  attendanceAvg[cls.id] === null || attendanceAvg[cls.id] === undefined
                    ? '-'
                    : `${attendanceAvg[cls.id]}%`
                }}
              </text>
            </svg>
            <div>
              <p class="st-classring__label">Rata-rata kehadiran nyata</p>
              <p class="st-table__muted">{{ attendanceDetail[cls.id] ?? 'Menghitung…' }}</p>
            </div>
          </div>
          <p class="st-table__muted st-skline">{{ skLabel(cls.id) }}</p>
          <p v-if="(classLabs[cls.id] ?? []).length" class="st-classlab">
            <span class="st-material-icon" aria-hidden="true">science</span>
            <span
              >Laboratorium praktikum:
              <strong>{{ (classLabs[cls.id] ?? []).join(', ') }}</strong></span
            >
          </p>
          <div class="st-grid2">
            <div>
              <p class="st-kpi">{{ counts[cls.id] ?? '…' }} <small>Siswa Terdaftar</small></p>
              <p class="st-table__muted">{{ assignmentLabel(cls.id) }}</p>
            </div>
            <div v-if="nextSchedules[cls.id]">
              <p class="st-classnext">
                <strong>Sesi: {{ nextSchedules[cls.id]?.subject }}</strong>
              </p>
              <p class="st-table__muted">
                {{ weekdays[nextSchedules[cls.id]?.weekday ?? 0] }},
                {{ nextSchedules[cls.id]?.start }} - {{ nextSchedules[cls.id]?.end }} ·
                {{ nextSchedules[cls.id]?.lab }}
              </p>
            </div>
            <div v-else>
              <p class="st-table__muted">Belum ada jadwal aktif untuk kelas ini.</p>
            </div>
          </div>
          <p>
            <UiButton variant="primary" @click="openRoster(cls.id)">Buka Roster Siswa →</UiButton>
          </p>
        </UiCard>
      </div>
    </section>

    <!-- ============ ROSTER KELAS (B02-08) ============ -->
    <section v-else>
      <UiButton variant="text" size="sm" @click="backToList">← Kembali ke Kelas Saya</UiButton>
      <UiPageHeader
        :title="`Roster Siswa · ${detail?.code ?? ''}`"
        description="Daftar siswa terdaftar dalam penugasan (Mode Baca)."
      >
        <template #actions>
          <RouterLink class="st-btnlink" to="/app/sessions">Lihat Sesi Terkait</RouterLink>
          <RouterLink class="st-btnlink" to="/app/reports">Rekap Kehadiran Kelas</RouterLink>
        </template>
      </UiPageHeader>

      <p v-if="detailLoading" class="st-table__muted">Memuat roster…</p>
      <p v-if="detailError" class="st-alert st-alert--error" role="alert">{{ detailError }}</p>

      <div v-if="detail" class="st-grid3">
        <UiCard title="Status Hak Akses Penugasan" :subtitle="assignmentLabel(detail.id)">
          <p class="st-table__muted">Pengampu: {{ auth.account?.full_name ?? '-' }}</p>
          <p class="st-table__muted">Total: {{ detail.students.length }} Siswa Terdaftar</p>
        </UiCard>
        <UiCard
          title="Anggota Aktif"
          :subtitle="`${detail.students.filter((s) => s.is_active).length} dari ${detail.students.length} siswa`"
        >
          <p class="st-kpi">
            {{ detail.students.filter((s) => s.is_active).length
            }}<small> / {{ detail.students.length }}</small>
          </p>
        </UiCard>
        <UiCard title="Mode Akses" subtitle="Baca roster dan rekap kelas penugasan">
          <p><UiBadge tone="info">Mode Baca</UiBadge></p>
        </UiCard>
      </div>

      <div v-if="detail" class="st-card">
        <form class="st-toolbar" @submit.prevent>
          <UiSearchInput
            v-model="searchText"
            placeholder="Cari nomor siswa atau nama siswa…"
            aria-label="Cari siswa"
          />
          <UiSelect v-model="statusFilter" aria-label="Filter status">
            <option value="">Semua Anggota Aktif</option>
            <option value="active">Aktif</option>
            <option value="inactive">Nonaktif</option>
          </UiSelect>
        </form>
        <div class="st-tablewrap">
          <table class="st-table">
            <thead>
              <tr>
                <th scope="col">No</th>
                <th scope="col">Nomor Siswa</th>
                <th scope="col">Nama Siswa</th>
                <th scope="col">Kelas</th>
                <th scope="col">Status Keanggotaan</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(s, idx) in filteredStudents" :key="s.id">
                <td>{{ idx + 1 }}</td>
                <td class="st-table__mono">{{ s.student_number }}</td>
                <td>
                  <span class="st-identity">
                    <UiAvatar :name="s.full_name" />
                    <span>{{ s.full_name }}</span>
                  </span>
                </td>
                <td>{{ detail.code }}</td>
                <td>
                  <UiBadge :tone="s.is_active ? 'present' : 'neutral'">{{
                    s.is_active ? 'Terdaftar Aktif' : 'Nonaktif'
                  }}</UiBadge>
                </td>
              </tr>
              <tr v-if="!filteredStudents.length">
                <td colspan="5">
                  <UiEmptyState
                    title="Tidak ada siswa cocok"
                    description="Ubah kata kunci atau filter status."
                  />
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </section>
  </div>
</template>
