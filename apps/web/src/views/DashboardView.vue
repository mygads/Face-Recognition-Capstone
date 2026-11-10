<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  ApiError,
  getSessionRoster,
  listAtRiskStudents,
  listAttendanceCorrections,
  listAttendanceSessions,
  listDevices,
  listLaborantAssignments,
  listLaboratories,
  listMyClasses,
  type AtRiskStudentRow,
  type AttendanceCorrectionResponse,
  type AttendanceSession,
  type Device,
  type Laboratory,
  type SchoolClass,
} from '../api/client'
import { useAuthStore } from '../stores/auth'
import { formatDateTime } from '../utils/dateFormat'
import { attendanceStatusLabel } from '../utils/attendanceStatus'
import UiBadge from '../components/ui/UiBadge.vue'
import UiButton from '../components/ui/UiButton.vue'
import UiCard from '../components/ui/UiCard.vue'
import UiEmptyState from '../components/ui/UiEmptyState.vue'
import UiInput from '../components/ui/UiInput.vue'
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
const dateFilter = ref('')

const labs = ref<Laboratory[]>([])
const devices = ref<Device[]>([])
const activeSessions = ref<AttendanceSession[]>([])
const pendingCorrections = ref<AttendanceCorrectionResponse[]>([])
const atRisk = ref<AtRiskStudentRow[]>([])
const myClasses = ref<SchoolClass[]>([])
const myLabs = ref<{ laboratory_id: string; code: string | null; name: string | null }[]>([])
const rosterNames = ref<Record<string, string>>({})

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

function correctionStudent(id: string | null | undefined): string {
  if (!id) return 'Siswa'
  return rosterNames.value[id] ?? 'Siswa'
}

function atRiskReason(row: AtRiskStudentRow): string {
  if (row.reasons.includes('sering_terlambat'))
    return `Terlambat ${row.late_count}x dari ${row.total_sessions} sesi`
  return `Absen ${row.absent_count}x dari ${row.total_sessions} sesi`
}

async function resolveCorrectionNames(): Promise<void> {
  const sessionIds = [
    ...new Set(pendingCorrections.value.map((c) => c.session_id).filter(Boolean)),
  ] as string[]
  for (const sid of sessionIds.slice(0, 5)) {
    try {
      const roster = await getSessionRoster(sid)
      for (const entry of roster) {
        if (entry.student_id) rosterNames.value[entry.student_id] = entry.full_name
        rosterNames.value[entry.student_number] = entry.full_name
      }
    } catch {
      /* abaikan */
    }
  }
}

async function load(): Promise<void> {
  isLoading.value = true
  pageError.value = null
  try {
    if (isAdmin.value) {
      const [labPage, devPage, sessPage, corrPage, riskPage] = await Promise.all([
        listLaboratories({ limit: 100, offset: 0 }).catch(() => ({ items: [] as Laboratory[] })),
        listDevices({ limit: 100, offset: 0 }).catch(() => ({ items: [] as Device[] })),
        listAttendanceSessions({ status: 'active', limit: 100, offset: 0 }).catch(() => ({
          items: [] as AttendanceSession[],
        })),
        listAttendanceCorrections({ decision_status: 'pending', limit: 20, offset: 0 }).catch(
          () => ({
            items: [] as AttendanceCorrectionResponse[],
          }),
        ),
        listAtRiskStudents({ limit: 25, offset: 0 }).catch(() => ({
          items: [] as AtRiskStudentRow[],
        })),
      ])
      labs.value = labPage.items ?? []
      devices.value = devPage.items ?? []
      activeSessions.value = sessPage.items ?? []
      pendingCorrections.value = corrPage.items ?? []
      atRisk.value = (riskPage.items ?? []) as AtRiskStudentRow[]
      await resolveCorrectionNames()
    } else if (isTeacher.value) {
      const [clsPage, sessPage, corrPage, riskPage] = await Promise.all([
        listMyClasses({ limit: 50 }).catch(() => ({ items: [] as SchoolClass[] })),
        listAttendanceSessions({ status: 'active', limit: 100, offset: 0 }).catch(() => ({
          items: [] as AttendanceSession[],
        })),
        listAttendanceCorrections({ decision_status: 'pending', limit: 20, offset: 0 }).catch(
          () => ({
            items: [] as AttendanceCorrectionResponse[],
          }),
        ),
        listAtRiskStudents({ limit: 25, offset: 0 }).catch(() => ({
          items: [] as AtRiskStudentRow[],
        })),
      ])
      myClasses.value = clsPage.items ?? []
      const classNames = new Set(myClasses.value.map((c) => c.name))
      activeSessions.value = (sessPage.items ?? []).filter((s) => classNames.has(s.class_name))
      pendingCorrections.value = corrPage.items ?? []
      atRisk.value = (riskPage.items ?? []) as AtRiskStudentRow[]
      await resolveCorrectionNames()
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
          description="Ringkasan operasional presensi praktikum, infrastruktur dua laboratorium, dan antrean koreksi"
        >
          <template #actions>
            <UiSelect v-model="labFilter" aria-label="Filter laboratorium">
              <option value="">Semua Laboratorium</option>
              <option v-for="lab in labs" :key="lab.id" :value="lab.id">{{ lab.name }}</option>
            </UiSelect>
            <UiInput
              v-model="dateFilter"
              type="date"
              aria-label="Filter tanggal"
              style="max-width: 180px"
            />
          </template>
        </UiPageHeader>

        <div class="st-kpi">
          <UiCard>
            <p class="st-kpi__label">Sesi Praktikum Aktif</p>
            <p class="st-kpi__value">
              {{ activeSessions.length }} Sesi <UiBadge tone="present">Berjalan</UiBadge>
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
            <p class="st-kpi__label">Antrean Koreksi Kehadiran</p>
            <p class="st-kpi__value">
              {{ pendingCorrections.length }} <UiBadge tone="late">Menunggu</UiBadge>
            </p>
          </UiCard>
          <UiCard>
            <p class="st-kpi__label">Siswa Terpantau EWS</p>
            <p class="st-kpi__value">
              {{ atRisk.length }} Siswa <UiBadge tone="neutral">Watchlist</UiBadge>
            </p>
          </UiCard>
        </div>

        <div class="st-grid2">
          <UiCard
            v-for="lab in visibleLabs"
            :key="lab.id"
            :title="lab.name"
            :subtitle="`Sesi aktif di ${lab.name}`"
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
          <UiCard title="Antrean Koreksi Kehadiran">
            <template #header
              ><UiButton variant="primary" @click="go('/app/corrections')"
                >Tinjau Koreksi</UiButton
              ></template
            >
            <div class="st-list">
              <div v-for="c in pendingCorrections.slice(0, 5)" :key="c.id" class="st-listrow">
                <div>
                  <p class="st-listrow__title">{{ correctionStudent(c.student_id) }}</p>
                  <p class="st-listrow__desc">
                    Usulan: {{ attendanceStatusLabel(c.previous_status) }} →
                    {{ attendanceStatusLabel(c.corrected_status) }} · {{ c.reason }}
                  </p>
                </div>
                <UiBadge tone="late">Menunggu</UiBadge>
              </div>
              <UiEmptyState
                v-if="!pendingCorrections.length"
                title="Antrean kosong"
                description="Tidak ada pengajuan koreksi menunggu keputusan."
              />
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
                    Perubahan akun, penugasan, dan keputusan koreksi tercatat.
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
          <UiCard title="Pengajuan Koreksi & Peringatan Dini">
            <template #header
              ><UiButton variant="text" @click="go('/app/ews')"
                >Tindak Lanjut EWS</UiButton
              ></template
            >
            <div class="st-list">
              <div v-for="c in pendingCorrections.slice(0, 3)" :key="c.id" class="st-listrow">
                <div>
                  <p class="st-listrow__title">
                    {{ correctionStudent(c.student_id) }} · Ajukan Koreksi
                  </p>
                  <p class="st-listrow__desc">
                    Usulan status {{ attendanceStatusLabel(c.corrected_status) }}
                  </p>
                </div>
                <UiBadge tone="late">Menunggu Keputusan</UiBadge>
              </div>
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
                v-if="!pendingCorrections.length && !atRisk.length"
                title="Semua aman"
                description="Tidak ada koreksi menunggu atau siswa terpantau."
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
