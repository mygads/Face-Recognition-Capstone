<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  ApiError,
  listAtRiskStudents,
  listAttendanceSessions,
  listDevices,
  getAttendanceReportSummary,
  listLaborantAssignments,
  listLaboratories,
  listMyClasses,
  type AtRiskStudentRow,
  type AttendanceSession,
  type AttendanceReportSummary,
  type Device,
  type Laboratory,
  type SchoolClass,
} from '../api/client'
import { useAuthStore } from '../stores/auth'
import { formatDateTime } from '../utils/dateFormat'
import UiBadge from '../components/ui/UiBadge.vue'
import UiButton from '../components/ui/UiButton.vue'
import UiCard from '../components/ui/UiCard.vue'
import UiEmptyState from '../components/ui/UiEmptyState.vue'
import UiPageHeader from '../components/ui/UiPageHeader.vue'
import UiSelect from '../components/ui/UiSelect.vue'

const auth = useAuthStore()
const router = useRouter()

const roles = computed(() => auth.account?.roles ?? [])
const perms = computed(() => (auth.account?.permissions ?? []) as string[])
const isAdmin = computed(() => roles.value.includes('ADMIN'))
const isTeacher = computed(() => !isAdmin.value && roles.value.includes('TEACHER'))
const canViewSessions = computed(
  () =>
    isAdmin.value ||
    perms.value.includes('session_view') ||
    perms.value.includes('session_operate'),
)
const canViewReports = computed(() => isAdmin.value || perms.value.includes('reports_read'))
const firstName = computed(() => (auth.account?.full_name ?? 'Staf').split(' ').at(0) ?? 'Staf')

const isLoading = ref(true)
const pageError = ref<string | null>(null)
const labFilter = ref('')
const dateFilter = ref(jakartaDateInputValue())
const dateInputRef = ref<HTMLInputElement | null>(null)
const attendanceSummary = ref<AttendanceReportSummary | null>(null)
const attendanceSummaryLoading = ref(false)
const attendanceSummaryError = ref<string | null>(null)
let attendanceSummaryRequest = 0

const labs = ref<Laboratory[]>([])
const devices = ref<Device[]>([])
const activeSessions = ref<AttendanceSession[]>([])
const atRisk = ref<AtRiskStudentRow[]>([])
const myClasses = ref<SchoolClass[]>([])
const myLabs = ref<{ laboratory_id: string; code: string | null; name: string | null }[]>([])

const todayLabel = computed(() => {
  try {
    return new Intl.DateTimeFormat('id-ID', {
      weekday: 'long',
      day: 'numeric',
      month: 'long',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      timeZone: 'Asia/Jakarta',
    }).format(new Date())
  } catch {
    return ''
  }
})

function errMsg(error: unknown): string {
  if (error instanceof ApiError) return error.message
  return 'Ringkasan belum dapat dimuat. Periksa koneksi lalu coba lagi.'
}

const visibleLabs = computed(() =>
  labFilter.value ? labs.value.filter((l) => l.id === labFilter.value) : labs.value,
)
const onlineDevices = computed(
  () => devices.value.filter((d) => (d.health_status ?? 'unknown') === 'online').length,
)

function sessionsForLab(labName: string): AttendanceSession[] {
  return activeSessions.value.filter((s) => s.laboratory_name === labName)
}

function labOnline(labName: string): number {
  return devices.value.filter(
    (d) => d.laboratory_name === labName && (d.health_status ?? '') === 'online',
  ).length
}

function labDeviceCount(labName: string): number {
  return devices.value.filter((d) => d.laboratory_name === labName).length
}

function atRiskReason(row: AtRiskStudentRow): string {
  if (row.reasons.includes('sering_terlambat'))
    return `Terlambat ${row.late_count}x dari ${row.total_sessions} sesi`
  return `Absen ${row.absent_count}x dari ${row.total_sessions} sesi`
}

function jakartaDateInputValue(): string {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Jakarta',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(new Date())
  const value = Object.fromEntries(parts.map((part) => [part.type, part.value]))
  return `${value.year}-${value.month}-${value.day}`
}

async function loadAttendanceSummary(): Promise<void> {
  if (!isAdmin.value || !dateFilter.value) return
  const requestId = ++attendanceSummaryRequest
  attendanceSummary.value = null
  attendanceSummaryError.value = null
  attendanceSummaryLoading.value = true
  try {
    const result = await getAttendanceReportSummary({
      starts_on: dateFilter.value,
      ends_on: dateFilter.value,
      timezone_name: 'Asia/Jakarta',
      laboratory_id: labFilter.value || undefined,
    })
    if (requestId === attendanceSummaryRequest) attendanceSummary.value = result
  } catch (error) {
    if (requestId === attendanceSummaryRequest) attendanceSummaryError.value = errMsg(error)
  } finally {
    if (requestId === attendanceSummaryRequest) attendanceSummaryLoading.value = false
  }
}

function openDatePicker(): void {
  const input = dateInputRef.value
  if (!input) return
  if (typeof input.showPicker === 'function') input.showPicker()
  else {
    input.focus()
    input.click()
  }
}

async function load(): Promise<void> {
  isLoading.value = true
  pageError.value = null
  try {
    if (isAdmin.value) {
      const [labPage, devPage, sessPage, riskPage] = await Promise.all([
        listLaboratories({ limit: 100, offset: 0 }).catch(() => ({ items: [] as Laboratory[] })),
        listDevices({ limit: 100, offset: 0 }).catch(() => ({ items: [] as Device[] })),
        listAttendanceSessions({ status: 'active', limit: 100, offset: 0 }).catch(() => ({
          items: [] as AttendanceSession[],
        })),
        listAtRiskStudents({ limit: 25, offset: 0 }).catch(() => ({
          items: [] as AtRiskStudentRow[],
        })),
      ])
      labs.value = labPage.items ?? []
      devices.value = devPage.items ?? []
      activeSessions.value = sessPage.items ?? []
      atRisk.value = (riskPage.items ?? []) as AtRiskStudentRow[]
      await loadAttendanceSummary()
    } else if (isTeacher.value) {
      const [clsPage, sessPage, riskPage] = await Promise.all([
        listMyClasses({ limit: 50 }).catch(() => ({ items: [] as SchoolClass[] })),
        listAttendanceSessions({ status: 'active', limit: 100, offset: 0 }).catch(() => ({
          items: [] as AttendanceSession[],
        })),
        listAtRiskStudents({ limit: 25, offset: 0 }).catch(() => ({
          items: [] as AtRiskStudentRow[],
        })),
      ])
      myClasses.value = clsPage.items ?? []
      const classNames = new Set(myClasses.value.map((c) => c.name))
      activeSessions.value = (sessPage.items ?? []).filter((s) => classNames.has(s.class_name))
      atRisk.value = (riskPage.items ?? []) as AtRiskStudentRow[]
    } else {
      const accountId = auth.account?.id
      const assign = accountId
        ? await listLaborantAssignments(accountId).catch(() => ({
            items: [] as typeof myLabs.value,
          }))
        : { items: [] as typeof myLabs.value }
      myLabs.value = assign.items ?? []
      const labNames = new Set(myLabs.value.map((a) => a.name ?? '').filter(Boolean))
      const [labPage, devPage, sessPage] = await Promise.all([
        listLaboratories({ limit: 100, offset: 0 }).catch(() => ({ items: [] as Laboratory[] })),
        listDevices({ limit: 100, offset: 0 }).catch(() => ({ items: [] as Device[] })),
        canViewSessions.value
          ? listAttendanceSessions({ status: 'active', limit: 100, offset: 0 }).catch(() => ({
              items: [] as AttendanceSession[],
            }))
          : Promise.resolve({ items: [] as AttendanceSession[] }),
      ])
      labs.value = (labPage.items ?? []).filter((l) => labNames.has(l.name))
      devices.value = (devPage.items ?? []).filter((d) => labNames.has(d.laboratory_name))
      activeSessions.value = (sessPage.items ?? []).filter((s) => labNames.has(s.laboratory_name))
    }
  } catch (error) {
    pageError.value = errMsg(error)
  } finally {
    isLoading.value = false
  }
}

watch([dateFilter, labFilter], () => {
  if (isAdmin.value) void loadAttendanceSummary()
})

function go(path: string): void {
  void router.push(path)
}

onMounted(load)
</script>

<template>
  <div class="st-page" data-testid="dashboard-page">
    <div v-if="isLoading">Memuat ringkasan…</div>
    <div v-else-if="pageError" class="master-data__alert" role="alert">{{ pageError }}</div>
    <template v-else>
      <!-- ADMIN -->
      <template v-if="isAdmin">
        <UiPageHeader
          title="Dashboard Admin"
          description="Pantau presensi, kondisi kamera, dan siswa yang perlu perhatian."
        >
          <template #actions>
            <UiSelect v-model="labFilter" aria-label="Filter laboratorium">
              <option value="">Semua Laboratorium</option>
              <option v-for="lab in labs" :key="lab.id" :value="lab.id">{{ lab.name }}</option>
            </UiSelect>
            <div class="dashboard__date-filter">
              <input
                ref="dateInputRef"
                v-model="dateFilter"
                class="st-input"
                type="date"
                aria-label="Filter tanggal"
              />
              <button
                class="dashboard__calendar-button"
                type="button"
                aria-label="Buka kalender"
                title="Buka kalender"
                @click="openDatePicker"
              >
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <path d="M7 2v3m10-3v3M4 9h16M5 4h14a1 1 0 0 1 1 1v15H4V5a1 1 0 0 1 1-1Z" />
                  <path d="M8 13h2m4 0h2m-8 4h2m4 0h2" />
                </svg>
              </button>
            </div>
          </template>
        </UiPageHeader>

        <div class="st-kpi">
          <UiCard>
            <p class="st-kpi__label">Sesi Praktikum Aktif</p>
            <p class="st-kpi__value">
              {{ activeSessions.length }} Sesi
              <UiBadge
                :tone="activeSessions.length ? 'present' : 'neutral'"
                data-testid="dashboard-active-session-status"
              >
                {{ activeSessions.length ? 'Berjalan' : 'Tidak aktif' }}
              </UiBadge>
            </p>
          </UiCard>
          <UiCard>
            <p class="st-kpi__label">Kesiapan Perangkat Kamera</p>
            <p class="st-kpi__value">
              {{ onlineDevices }} / {{ devices.length }}
              <UiBadge tone="present"
                >Online
                {{
                  devices.length ? Math.round((onlineDevices / devices.length) * 100) : 0
                }}%</UiBadge
              >
            </p>
          </UiCard>
          <UiCard>
            <p class="st-kpi__label">Siswa Terpantau EWS</p>
            <p class="st-kpi__value">
              {{ atRisk.length }} Siswa <UiBadge tone="neutral">Watchlist</UiBadge>
            </p>
          </UiCard>
        </div>

        <UiCard
          title="Ringkasan presensi"
          :subtitle="`Rekap kehadiran untuk ${dateFilter || 'tanggal yang dipilih'}`"
          data-testid="dashboard-attendance-summary"
        >
          <p v-if="attendanceSummaryLoading" role="status">Memuat rekap presensi…</p>
          <p v-else-if="attendanceSummaryError" class="master-data__alert" role="alert">
            {{ attendanceSummaryError }}
          </p>
          <div v-else-if="attendanceSummary" class="st-kpi dashboard__attendance-summary">
            <div>
              <p class="st-kpi__label">Total roster</p>
              <p class="st-kpi__value" data-testid="report-total">
                {{ attendanceSummary.total_rows }}
              </p>
            </div>
            <div>
              <p class="st-kpi__label">Hadir</p>
              <p class="st-kpi__value" data-testid="report-present">
                {{ attendanceSummary.present_count }}
              </p>
            </div>
            <div>
              <p class="st-kpi__label">Terlambat</p>
              <p class="st-kpi__value" data-testid="report-late">
                {{ attendanceSummary.late_count }}
              </p>
            </div>
            <div>
              <p class="st-kpi__label">Absen</p>
              <p class="st-kpi__value" data-testid="report-absent">
                {{ attendanceSummary.absent_count }}
              </p>
            </div>
            <div>
              <p class="st-kpi__label">Izin</p>
              <p class="st-kpi__value" data-testid="report-excused">
                {{ attendanceSummary.excused_count }}
              </p>
            </div>
          </div>
        </UiCard>

        <div
          class="st-grid2 dashboard__lab-grid"
          :class="{ 'dashboard__lab-grid--single': visibleLabs.length === 1 }"
        >
          <UiCard
            v-for="lab in visibleLabs"
            :key="lab.id"
            :title="lab.name"
            subtitle="Status sesi saat ini"
          >
            <template #header>
              <UiBadge :tone="labOnline(lab.name) > 0 ? 'present' : 'neutral'">
                {{
                  labDeviceCount(lab.name)
                    ? `${labOnline(lab.name)}/${labDeviceCount(lab.name)} Kamera Siap`
                    : 'Belum Ada Perangkat'
                }}
              </UiBadge>
            </template>
            <div class="st-list">
              <div v-for="s in sessionsForLab(lab.name)" :key="s.id" class="st-listrow">
                <div>
                  <p class="st-listrow__title">
                    {{ s.subject }} · {{ s.class_name }} · {{ s.teacher_name }}
                  </p>
                  <p class="st-listrow__desc">
                    {{ s.student_count }} siswa ·
                    {{ s.status === 'manual_override' ? 'Override manual' : 'Otomatis' }}
                  </p>
                </div>
                <UiButton variant="outlined" @click="go(`/app/sessions/${s.id}`)"
                  >Detail Lab</UiButton
                >
              </div>
              <UiEmptyState
                v-if="!sessionsForLab(lab.name).length"
                title="Tidak ada sesi aktif"
                description="Belum ada sesi berjalan di laboratorium ini."
              />
            </div>
          </UiCard>
        </div>

        <div class="st-grid2">
          <UiCard title="Aksi Cepat Operasional">
            <template #header
              ><UiButton variant="primary" @click="go('/app/sessions')"
                >Buka Sesi Presensi</UiButton
              ></template
            >
            <div class="st-list">
              <div class="st-listrow">
                <div>
                  <p class="st-listrow__title">Perbarui kehadiran langsung</p>
                  <p class="st-listrow__desc">
                    Guru dan aslab mengubah status hadir, terlambat, izin, atau absen langsung di
                    halaman sesi tanpa antrean persetujuan.
                  </p>
                </div>
                <UiButton variant="text" @click="go('/app/sessions')">Ke Sesi</UiButton>
              </div>
              <div class="st-listrow">
                <div>
                  <p class="st-listrow__title">Daftarkan wajah siswa</p>
                  <p class="st-listrow__desc">
                    Pendaftaran wajah memakai kamera perangkat yang sama dengan pengenalan agar
                    tidak berebut akses.
                  </p>
                </div>
                <UiButton variant="text" @click="go('/app/enrollment')">Ke Pendaftaran</UiButton>
              </div>
            </div>
          </UiCard>
          <UiCard title="Ringkasan EWS & Aktivitas Administrasi">
            <template #header
              ><UiButton variant="outlined" @click="go('/app/accounts')"
                >Kelola Staf</UiButton
              ></template
            >
            <div class="st-list">
              <div class="st-listrow">
                <div>
                  <p class="st-listrow__title">EWS: {{ atRisk.length }} siswa melewati ambang</p>
                  <p class="st-listrow__desc">Pantau keterlambatan dan absen berulang.</p>
                </div>
                <UiButton variant="text" @click="go('/app/ews')">Lihat EWS</UiButton>
              </div>
              <div class="st-listrow">
                <div>
                  <p class="st-listrow__title">Audit aktivitas staf</p>
                  <p class="st-listrow__desc">
                    Perubahan akun, penugasan, dan pembaruan kehadiran tercatat.
                  </p>
                </div>
                <UiButton variant="text" @click="go('/app/audit')">Audit</UiButton>
              </div>
            </div>
          </UiCard>
        </div>
      </template>

      <!-- GURU -->
      <template v-else-if="isTeacher">
        <UiPageHeader
          :title="`Selamat datang, ${firstName}`"
          description="Pantau praktikum aktif dan rekapitulasi kehadiran kelas penugasan Anda"
        >
          <template #actions
            ><span class="st-chip st-chip--on">{{ todayLabel }}</span></template
          >
        </UiPageHeader>

        <UiCard v-if="activeSessions[0]" :title="activeSessions[0].subject">
          <template #header>
            <UiBadge tone="present">Sedang Berlangsung</UiBadge>
            <UiButton variant="primary" @click="go(`/app/sessions/${activeSessions[0].id}`)"
              >Pantau Sesi</UiButton
            >
          </template>
          <p class="st-listrow__desc">
            {{ activeSessions[0].laboratory_name }} · Kelas {{ activeSessions[0].class_name }} ·
            {{ activeSessions[0].student_count }} siswa
          </p>
        </UiCard>
        <UiEmptyState
          v-else
          title="Tidak ada sesi aktif"
          description="Belum ada praktikum berjalan pada kelas penugasan Anda."
        />

        <div class="st-grid2">
          <UiCard title="Kelas Penugasan Aktif">
            <template #header
              ><UiButton variant="text" @click="go('/app/my-classes')"
                >Buka Roster Kelas</UiButton
              ></template
            >
            <div class="st-list">
              <div v-for="c in myClasses" :key="c.id" class="st-listrow">
                <div>
                  <p class="st-listrow__title">{{ c.name }}</p>
                  <p class="st-listrow__desc">Tahun ajaran {{ c.academic_year }}</p>
                </div>
                <UiBadge tone="present">Aktif</UiBadge>
              </div>
              <UiEmptyState
                v-if="!myClasses.length"
                title="Belum ada penugasan kelas"
                description="Hubungi admin untuk penugasan kelas."
              />
            </div>
          </UiCard>
          <UiCard title="Peringatan Dini (EWS)">
            <template #header
              ><UiButton variant="text" @click="go('/app/ews')"
                >Tindak Lanjut EWS</UiButton
              ></template
            >
            <div class="st-list">
              <div
                v-for="row in atRisk.slice(0, 3)"
                :key="row.student_id"
                class="st-listrow"
                data-testid="at-risk-row"
              >
                <div>
                  <p class="st-listrow__title">EWS: {{ row.full_name }}</p>
                  <p class="st-listrow__desc">{{ atRiskReason(row) }}</p>
                </div>
                <UiButton variant="text" @click="go('/app/ews')">Lihat Detail</UiButton>
              </div>
              <UiEmptyState
                v-if="!atRisk.length"
                title="Semua aman"
                description="Tidak ada siswa terpantau."
              />
            </div>
          </UiCard>
        </div>
      </template>

      <!-- LABORAN -->
      <template v-else>
        <UiPageHeader
          title="Dashboard Laboran"
          :description="
            myLabs.length
              ? `Kesiapan perangkat, sesi presensi, dan laporan operasional di ${myLabs.map((l) => l.name ?? l.code).join(', ')}`
              : 'Menunggu penugasan laboratorium dari admin'
          "
        />
        <div v-if="!myLabs.length" class="master-data__alert" role="alert">
          Belum ada penugasan laboratorium. Hubungi admin agar perangkat, sesi, dan pendaftaran
          wajah dapat diakses.
        </div>
        <div class="st-grid2">
          <UiCard title="Perangkat dan kamera">
            <template #header><span /></template>
            <div class="st-list">
              <div v-for="d in devices.slice(0, 3)" :key="d.device_id" class="st-listrow">
                <div>
                  <p class="st-listrow__title">{{ d.name }}</p>
                  <p class="st-listrow__desc">
                    Terakhir terhubung:
                    {{ d.last_seen_at ? formatDateTime(d.last_seen_at, 'Asia/Jakarta') : '-' }}
                  </p>
                </div>
                <UiBadge :tone="(d.health_status ?? '') === 'online' ? 'present' : 'neutral'">
                  {{
                    (d.health_status ?? '') === 'online'
                      ? 'Kamera siap'
                      : (d.health_status ?? '') === 'offline'
                        ? 'Offline'
                        : (d.health_status ?? '') === 'warning'
                          ? 'Perlu perhatian'
                          : '-'
                  }}
                </UiBadge>
              </div>
              <UiEmptyState
                v-if="!devices.length"
                title="Belum ada perangkat"
                description="Perangkat laboratorium akan tampil di sini setelah ditugaskan."
              />
            </div>
            <div style="margin-top: 12px">
              <UiButton variant="primary" @click="go('/app/camera-preview')"
                >Preview kamera</UiButton
              >
            </div>
          </UiCard>
          <div class="st-list">
            <UiCard
              v-if="canViewSessions"
              title="Sesi Presensi"
              subtitle="Pantau sesi berjalan pada lab penugasan Anda."
            >
              <UiButton variant="primary" @click="go('/app/sessions')">Pantau sesi</UiButton>
            </UiCard>
            <UiCard
              v-if="canViewReports"
              title="Laporan Kehadiran"
              subtitle="Rekapitulasi riwayat presensi kelas-kelas pada lab penugasan (akses lihat saja)."
            >
              <UiButton variant="primary" @click="go('/app/reports')">Lihat laporan</UiButton>
            </UiCard>
          </div>
        </div>
        <UiCard
          title="Antrean dan sinkronisasi"
          subtitle="Status antrean pengiriman perangkat lab penugasan"
        >
          <p class="st-kpi__value">0 menunggu <UiBadge tone="present">Tersinkron</UiBadge></p>
        </UiCard>
        <UiCard title="Pendaftaran Wajah" subtitle="Template wajah aktif siswa lab penugasan">
          <UiButton variant="primary" @click="go('/app/enrollment')">Pendaftaran Wajah</UiButton>
        </UiCard>
      </template>
    </template>
  </div>
</template>

<style scoped>
.dashboard__date-filter {
  position: relative;
  display: flex;
  align-items: center;
  width: min(230px, 100%);
}
.dashboard__date-filter .st-input {
  width: 100%;
  min-width: 0;
  padding-right: 44px;
}
.dashboard__date-filter .st-input::-webkit-calendar-picker-indicator {
  display: none;
}
.dashboard__lab-grid--single {
  grid-template-columns: minmax(0, 1fr);
}
.dashboard__calendar-button {
  position: absolute;
  right: 4px;
  display: grid;
  width: 36px;
  height: 36px;
  z-index: 1;
  place-items: center;
  border: 0;
  border-radius: var(--st-radius-sm);
  background: transparent;
  color: var(--st-text-muted);
  cursor: pointer;
}
.dashboard__calendar-button:hover,
.dashboard__calendar-button:focus-visible {
  background: var(--st-surface-container);
  color: var(--st-primary);
}
.dashboard__calendar-button svg {
  width: 20px;
  height: 20px;
  fill: none;
  stroke: currentColor;
  stroke-linecap: round;
  stroke-linejoin: round;
  stroke-width: 1.7;
}
.dashboard__attendance-summary {
  grid-template-columns: repeat(5, minmax(0, 1fr));
}
@media (max-width: 760px) {
  .dashboard__attendance-summary {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
.st-kpi__label {
  margin: 0 0 6px;
  font-size: 0.72rem;
  font-weight: 600;
  color: var(--st-text-muted);
}
.st-kpi__value {
  margin: 0;
  font-size: 1.5rem;
  font-weight: 800;
  color: var(--st-text-main);
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
</style>
