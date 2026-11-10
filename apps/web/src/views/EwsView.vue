<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  ApiError,
  createEwsFollowUp,
  listAtRiskStudents,
  listAttendanceReportRows,
  listEwsFollowUps,
  updateEwsFollowUp,
  type AtRiskPage,
  type AttendanceReportRow,
  type EwsFollowUp,
} from '../api/client'
import { useAuthStore } from '../stores/auth'
import { formatDateTimeLocal } from '../utils/dateFormat'
import UiAvatar from '../components/ui/UiAvatar.vue'
import UiBadge from '../components/ui/UiBadge.vue'
import UiButton from '../components/ui/UiButton.vue'
import UiCard from '../components/ui/UiCard.vue'
import UiDrawer from '../components/ui/UiDrawer.vue'
import UiEmptyState from '../components/ui/UiEmptyState.vue'
import UiPageHeader from '../components/ui/UiPageHeader.vue'
import UiStat from '../components/ui/UiStat.vue'
import UiTextarea from '../components/ui/UiTextarea.vue'

const auth = useAuthStore()
const canFollowUp = computed(() => {
  const perms = (auth.account?.permissions ?? []) as string[]
  if ((auth.account?.roles ?? []).includes('ADMIN')) return true
  return perms.includes('ews_follow_up')
})
const canViewReports = computed(() => {
  const perms = (auth.account?.permissions ?? []) as string[]
  if ((auth.account?.roles ?? []).includes('ADMIN')) return true
  return perms.includes('reports_read')
})
const page = ref<AtRiskPage | null>(null)
const selectedStudent = ref<string | null>(null)
const notes = ref<EwsFollowUp[]>([])
const triggerRows = ref<AttendanceReportRow[]>([])
const triggersLoading = ref(false)
const noteText = ref('')
const isLoading = ref(false)
const error = ref<string | null>(null)
const detailError = ref<string | null>(null)
const message = ref<string | null>(null)
const selectedStudentNumber = computed(() => selectedRow.value?.student_number ?? '')
const selectedRow = computed(
  () => page.value?.items.find((s) => s.student_id === selectedStudent.value) ?? null,
)
const openNotesCount = computed(() => notes.value.filter((n) => n.status === 'open').length)
const riskTone = computed(() => {
  if (!page.value || !selectedRow.value) return 'late'
  return selectedRow.value.absence_pct >= page.value.effective_absence_pct_threshold
    ? 'absent'
    : 'late'
})
const riskLabel = computed(() =>
  riskTone.value === 'absent' ? 'Tingkat Risiko: Tinggi' : 'Tingkat Risiko: Sedang',
)
const triggerList = computed(() =>
  triggerRows.value.filter((r) => r.status === 'absent' || r.status === 'late').slice(0, 5),
)

function sourceLabel(source: AttendanceReportRow['source']): string {
  if (source === 'face_recognition') return 'Rekaman biometrik'
  if (source === 'manual') return 'Penanda manual'
  if (source === 'system') return 'Tercatat oleh sistem'
  return 'Sumber tidak tercatat'
}

function formatError(err: unknown): string {
  if (err instanceof ApiError) return err.message
  return 'Data peringatan dini belum dapat dimuat.'
}

async function load(): Promise<void> {
  isLoading.value = true
  error.value = null
  try {
    page.value = await listAtRiskStudents({ limit: 50, offset: 0 })
  } catch (err) {
    error.value = formatError(err)
  } finally {
    isLoading.value = false
  }
}

async function openStudent(studentId: string): Promise<void> {
  selectedStudent.value = studentId
  noteText.value = ''
  message.value = null
  detailError.value = null
  triggerRows.value = []
  try {
    notes.value = await listEwsFollowUps(studentId)
  } catch (err) {
    detailError.value = formatError(err)
  }
  triggersLoading.value = true
  try {
    const windowDays = page.value?.effective_window_days ?? 30
    const ends = new Date()
    const starts = new Date(ends.getTime() - windowDays * 24 * 60 * 60 * 1000)
    const rows = await listAttendanceReportRows({
      starts_on: starts.toISOString().slice(0, 10),
      ends_on: ends.toISOString().slice(0, 10),
      student_id: studentId,
      limit: 10,
    })
    triggerRows.value = rows.items ?? []
  } catch {
    triggerRows.value = []
  } finally {
    triggersLoading.value = false
  }
}

async function addNote(): Promise<void> {
  if (!selectedStudent.value || !noteText.value.trim()) return
  try {
    await createEwsFollowUp(selectedStudent.value, noteText.value.trim())
    noteText.value = ''
    notes.value = await listEwsFollowUps(selectedStudent.value)
    message.value = 'Catatan tindak lanjut tersimpan.'
  } catch (err) {
    detailError.value = formatError(err)
  }
}

async function markDone(note: EwsFollowUp): Promise<void> {
  if (!selectedStudent.value) return
  try {
    await updateEwsFollowUp(selectedStudent.value, note.id, 'done')
    notes.value = await listEwsFollowUps(selectedStudent.value)
  } catch (err) {
    detailError.value = formatError(err)
  }
}

onMounted(() => void load())
</script>

<template>
  <div class="st-page" aria-label="Peringatan dini">
    <UiPageHeader
      eyebrow="Pemantauan"
      title="Sistem Peringatan Dini (Early Warning System)"
      description="Pemantauan otomatis indikator ketidakhadiran dan keterlambatan praktikum siswa berdasarkan ambang batas akademik definitif."
    >
      <template #actions>
        <UiButton
          v-if="canFollowUp && (page?.items.length ?? 0) > 0"
          variant="primary"
          type="button"
          @click="page && openStudent(page.items[0].student_id)"
          >Form Bimbingan Baru</UiButton
        >
      </template>
    </UiPageHeader>
    <p v-if="page" class="st-table__muted" data-testid="ews-thresholds">
      Jendela {{ page.effective_window_days }} hari · ambang absen
      {{ page.effective_absence_pct_threshold }}% · ambang terlambat
      {{ page.effective_late_count_threshold }}x
    </p>
    <p v-if="isLoading" class="st-table__muted">Memuat watchlist…</p>
    <p v-if="error" class="st-alert st-alert--error" role="alert">{{ error }}</p>

    <div v-if="page" class="st-kpi">
      <UiStat
        label="Ambang keterlambatan"
        :value="`> ${page.effective_late_count_threshold} sesi`"
        caption="Maksimal toleransi kehadiran terlambat per semester"
        tone="warning"
      />
      <UiStat
        label="Ambang ketidakhadiran (absen)"
        :value="`> ${page.effective_absence_pct_threshold}%`"
        caption="Batas tanpa keterangan sah sebelum sanksi praktikum"
        tone="danger"
      />
      <UiStat
        label="Total terpantau watchlist"
        :value="`${page.pagination.total} siswa`"
        :caption="`${page.items.length} siswa pada halaman ini`"
        tone="info"
      />
    </div>

    <UiCard
      title="Watchlist siswa terpantau EWS"
      subtitle="Daftar siswa yang mencapai ambang batas anomali presensi pada periode semester berjalan."
    >
      <div class="st-tablewrap">
        <table class="st-table">
          <thead>
            <tr>
              <th scope="col">No</th>
              <th scope="col">Nomor siswa</th>
              <th scope="col">Nama siswa</th>
              <th scope="col">Kelas</th>
              <th scope="col">Indikator pemicu</th>
              <th scope="col">Jumlah kejadian</th>
              <th scope="col">Status</th>
              <th scope="col"><span class="st-table__actions">Aksi</span></th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="page && !page.items.length && !isLoading">
              <td colspan="8"><UiEmptyState title="Belum ada siswa yang perlu perhatian" /></td>
            </tr>
            <tr
              v-for="(st, i) in page?.items ?? []"
              v-else
              :key="st.student_id"
              data-testid="ews-row"
            >
              <td class="st-table__num">{{ String(i + 1).padStart(2, '0') }}</td>
              <td class="st-table__mono">{{ st.student_number }}</td>
              <td>
                <span class="st-table__who"
                  ><UiAvatar :name="st.full_name" />{{ st.full_name }}</span
                >
              </td>
              <td>{{ st.class_name }}</td>
              <td>
                <UiBadge
                  :tone="
                    page && st.absence_pct >= page.effective_absence_pct_threshold
                      ? 'absent'
                      : 'late'
                  "
                >
                  {{
                    page && st.absence_pct >= page.effective_absence_pct_threshold
                      ? 'Akumulasi Absen'
                      : 'Akumulasi Terlambat'
                  }}
                </UiBadge>
              </td>
              <td class="st-table__mono">
                {{ st.absence_pct }}% absen · {{ st.late_count }}x terlambat
              </td>
              <td>
                <UiBadge
                  :tone="
                    page && st.absence_pct >= page.effective_absence_pct_threshold
                      ? 'absent'
                      : 'late'
                  "
                >
                  {{
                    page && st.absence_pct >= page.effective_absence_pct_threshold
                      ? 'Perlu Tindak Lanjut'
                      : 'Dipantau'
                  }}
                </UiBadge>
              </td>
              <td class="st-table__actions">
                <button class="st-rowbtn" type="button" @click="openStudent(st.student_id)">
                  Detail siswa
                </button>
                <RouterLink
                  v-if="canViewReports"
                  class="st-link"
                  :to="`/app/reports?student_number=${st.student_number}`"
                  data-testid="ews-to-report"
                  >Riwayat →</RouterLink
                >
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </UiCard>

    <UiDrawer
      v-if="selectedStudent !== null"
      title="Detail peringatan dini"
      @close="selectedStudent = null"
    >
      <div v-if="selectedStudent" data-testid="ews-detail">
        <p v-if="detailError" class="st-alert st-alert--error" role="alert">{{ detailError }}</p>
        <p v-if="message" class="st-alert st-alert--success" role="status">{{ message }}</p>
        <div v-if="selectedRow" class="st-ewshead">
          <p class="st-ewshead__name">
            {{ selectedRow.full_name }}
            <span class="st-table__muted">(NIS: {{ selectedRow.student_number }})</span>
          </p>
          <p class="st-ewshead__chips">
            <UiBadge tone="info">{{ selectedRow.class_name }}</UiBadge>
            <UiBadge :tone="openNotesCount > 0 ? 'absent' : 'late'"
              >Status: {{ openNotesCount > 0 ? 'Terbuka' : 'Dipantau' }}</UiBadge
            >
          </p>
          <p class="st-table__muted">{{ notes[0]?.author_name ?? 'Guru pengampu' }}</p>
        </div>
        <div class="st-ewssec">
          <div class="st-ewssec__head">
            <h3>Ringkasan pemicu sistem</h3>
            <UiBadge :tone="riskTone">{{ riskLabel }}</UiBadge>
          </div>
          <p v-if="selectedRow" class="st-table__muted">
            {{ selectedRow.absent_count }}x absen · {{ selectedRow.late_count }}x terlambat dari
            {{ selectedRow.total_sessions }} sesi terpantau.
          </p>
        </div>
        <div class="st-ewssec">
          <div class="st-ewssec__head">
            <h3>Sesi terkait pemicu EWS</h3>
            <span class="st-chip">{{ triggerList.length }} sesi perlu perhatian</span>
          </div>
          <p v-if="triggersLoading" class="st-table__muted">Memuat sesi terkait…</p>
          <ol v-else-if="triggerList.length" class="st-ewslist">
            <li
              v-for="(row, idx) in triggerList"
              :key="row.attendance_record_id ?? row.session_id"
              class="st-ewslist__item"
            >
              <span class="st-ewslist__num" aria-hidden="true">{{ idx + 1 }}</span>
              <div>
                <p class="st-listrow__title">{{ row.subject || 'Sesi praktikum' }}</p>
                <p class="st-listrow__desc">
                  {{ formatDateTimeLocal(row.session_opened_at) }} · {{ row.laboratory_name }}
                </p>
                <p class="st-listrow__desc">
                  {{ sourceLabel(row.source) }}{{ row.note ? ` · ${row.note}` : '' }}
                </p>
              </div>
              <UiBadge :tone="row.status === 'absent' ? 'absent' : 'late'">{{
                row.status === 'absent' ? 'Absen' : 'Terlambat'
              }}</UiBadge>
            </li>
          </ol>
          <p v-else class="st-table__muted">Tidak ada sesi absen/terlambat pada jendela pantau.</p>
        </div>
        <div class="st-ewssec">
          <div class="st-ewssec__head">
            <h3>Riwayat tindak lanjut guru</h3>
            <span class="st-table__muted">{{ openNotesCount }} catatan aktif</span>
          </div>
        </div>
        <ul class="st-list">
          <li v-for="n in notes" :key="n.id" class="st-list__item" data-testid="ews-note">
            <div>
              <p class="st-listrow__title">{{ n.author_name ?? 'Petugas' }}</p>
              <p class="st-listrow__desc">
                {{ n.status }} · {{ formatDateTimeLocal(n.created_at) }}
              </p>
              <p>{{ n.note }}</p>
            </div>
            <UiButton
              v-if="n.status === 'open' && canFollowUp"
              variant="secondary"
              type="button"
              @click="markDone(n)"
              >Tandai selesai</UiButton
            >
          </li>
        </ul>
        <form
          v-if="canFollowUp"
          style="display: grid; gap: 8px; margin-top: 12px"
          @submit.prevent="addNote"
        >
          <label class="st-field"
            ><span>Catatan tindak lanjut</span>
            <UiTextarea
              v-model="noteText"
              data-testid="ews-note-input"
              maxlength="2000"
              required
              rows="3"
            />
          </label>
          <div class="st-detailactions">
            <RouterLink
              v-if="canViewReports && selectedStudentNumber"
              class="st-btnlink"
              :to="`/app/reports?student_number=${selectedStudentNumber}`"
              >Lihat Laporan Siswa</RouterLink
            >
            <UiButton type="submit" variant="primary" data-testid="ews-note-save"
              >+ Tambah Tindak Lanjut</UiButton
            >
          </div>
        </form>
        <RouterLink
          v-else-if="canViewReports && selectedStudentNumber"
          class="st-link"
          :to="`/app/reports?student_number=${selectedStudentNumber}`"
          >Lihat Laporan Siswa</RouterLink
        >
      </div>
    </UiDrawer>
  </div>
</template>
