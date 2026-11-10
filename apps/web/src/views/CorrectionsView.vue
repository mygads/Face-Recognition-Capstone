<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import {
  decideAttendanceCorrection,
  getAttendanceCorrection,
  getSessionRoster,
  listAttendanceCorrections,
  listAttendanceSessions,
  type AttendanceCorrectionResponse,
} from '../api/client'
import { formatApiError } from '../utils/apiError'
import { useAuthStore } from '../stores/auth'
import UiAvatar from '../components/ui/UiAvatar.vue'
import UiBadge from '../components/ui/UiBadge.vue'
import UiButton from '../components/ui/UiButton.vue'
import UiCard from '../components/ui/UiCard.vue'
import UiEmptyState from '../components/ui/UiEmptyState.vue'
import UiField from '../components/ui/UiField.vue'
import UiInput from '../components/ui/UiInput.vue'
import UiPageHeader from '../components/ui/UiPageHeader.vue'
import { attendanceStatusLabel, correctionDecisionLabel } from '../utils/attendanceStatus'
import UiSearchInput from '../components/ui/UiSearchInput.vue'

const auth = useAuthStore()
const route = useRoute()
const isAdmin = computed(() => auth.account?.roles.includes('ADMIN') ?? false)
const tab = ref<'pending' | 'approved' | 'rejected'>('pending')
const items = ref<AttendanceCorrectionResponse[]>([])
const total = ref(0)
const detail = ref<AttendanceCorrectionResponse | null>(null)
const isLoading = ref(false)
const detailLoading = ref(false)
const error = ref<string | null>(null)
const detailError = ref<string | null>(null)
const message = ref<string | null>(null)
const decisionNote = ref('')
const searchText = ref('')
const counts = ref({ pending: 0, approved: 0, rejected: 0 })
const studentNames = ref<Record<string, string>>({})
const sessionSubjects = ref<Record<string, string>>({})

function formatError(err: unknown): string {
  return formatApiError(err, 'Data koreksi belum dapat dimuat.')
}

function ticketOf(id: string): string {
  return `KOR-${id.replace(/-/g, '').slice(0, 8).toUpperCase()}`
}

function studentNameOf(item: AttendanceCorrectionResponse): string {
  if (item.student_id && studentNames.value[item.student_id])
    return studentNames.value[item.student_id]
  return item.student_id ? `Siswa ${item.student_id.slice(0, 8)}` : '-'
}

function sessionNameOf(item: AttendanceCorrectionResponse): string {
  if (item.session_id && sessionSubjects.value[item.session_id])
    return sessionSubjects.value[item.session_id]
  return item.session_id ? `Sesi ${item.session_id.slice(0, 8)}` : '-'
}

const statusLabel = attendanceStatusLabel
const decisionLabel = correctionDecisionLabel
function statusTone(
  status: string,
): 'present' | 'late' | 'absent' | 'excused' | 'neutral' | 'info' {
  if (status === 'present') return 'present'
  if (status === 'late') return 'late'
  if (status === 'absent') return 'absent'
  if (status === 'excused') return 'excused'
  return 'neutral'
}

const filteredItems = computed(() => {
  const q = searchText.value.trim().toLowerCase()
  if (!q) return items.value
  return items.value.filter(
    (item) =>
      studentNameOf(item).toLowerCase().includes(q) ||
      item.reason.toLowerCase().includes(q) ||
      ticketOf(item.id).toLowerCase().includes(q),
  )
})

async function loadCounts(): Promise<void> {
  try {
    const [p, a, r] = await Promise.all([
      listAttendanceCorrections({ decision_status: 'pending', limit: 1, offset: 0 }),
      listAttendanceCorrections({ decision_status: 'approved', limit: 1, offset: 0 }),
      listAttendanceCorrections({ decision_status: 'rejected', limit: 1, offset: 0 }),
    ])
    counts.value = {
      pending: p.pagination.total,
      approved: a.pagination.total,
      rejected: r.pagination.total,
    }
  } catch {
    counts.value = { pending: 0, approved: 0, rejected: 0 }
  }
}

async function enrichList(list: AttendanceCorrectionResponse[]): Promise<void> {
  const sessionIds = [
    ...new Set(list.map((item) => item.session_id).filter((id): id is string => Boolean(id))),
  ]
  try {
    const page = await listAttendanceSessions({ limit: 100, offset: 0 })
    const map: Record<string, string> = {}
    for (const session of page.items) map[session.id] = session.subject
    sessionSubjects.value = map
  } catch {
    sessionSubjects.value = {}
  }
  const names: Record<string, string> = {}
  await Promise.all(
    sessionIds.map(async (sessionId) => {
      try {
        const roster = await getSessionRoster(sessionId)
        for (const entry of roster) names[entry.student_id] = entry.full_name
      } catch {
        /* abaikan sesi yang tidak dapat dibaca */
      }
    }),
  )
  studentNames.value = names
}

async function loadList(): Promise<void> {
  isLoading.value = true
  error.value = null
  try {
    const page = await listAttendanceCorrections({
      decision_status: tab.value,
      limit: 50,
      offset: 0,
    })
    items.value = page.items
    total.value = page.pagination.total
    await enrichList(page.items)
  } catch (err) {
    error.value = formatError(err)
  } finally {
    isLoading.value = false
  }
}

async function loadDetail(id: string): Promise<void> {
  detailLoading.value = true
  detailError.value = null
  message.value = null
  decisionNote.value = ''
  try {
    detail.value = await getAttendanceCorrection(id)
  } catch (err) {
    detailError.value = formatError(err)
    detail.value = null
  } finally {
    detailLoading.value = false
  }
}

async function decide(decision: 'approved' | 'rejected'): Promise<void> {
  if (!detail.value) return
  if (decision === 'rejected' && !decisionNote.value.trim()) {
    detailError.value = 'Alasan penolakan wajib diisi pada catatan keputusan.'
    return
  }
  try {
    detail.value = await decideAttendanceCorrection(detail.value.id, {
      decision,
      decision_note: decisionNote.value || null,
    })
    message.value =
      decision === 'approved'
        ? 'Koreksi disetujui. Rekap, laporan, dan EWS memakai status baru.'
        : 'Koreksi ditolak. Status final tidak berubah.'
    await Promise.all([loadList(), loadCounts()])
  } catch (err) {
    detailError.value = formatError(err)
  }
}

watch(tab, () => void loadList())
watch(
  () => route.params.correctionId,
  (next) => {
    if (next) void loadDetail(String(next))
    else detail.value = null
  },
)

onMounted(async () => {
  await Promise.all([loadList(), loadCounts()])
  const wanted = route.params.correctionId
  if (wanted) await loadDetail(String(wanted))
})
</script>

<template>
  <div class="st-page">
    <UiPageHeader
      :title="isAdmin ? 'Koreksi Kehadiran' : 'Koreksi Saya'"
      :description="
        isAdmin
          ? 'Antrean pengajuan koreksi dari seluruh sesi. Keputusan admin memperbarui rekap, laporan, dan EWS.'
          : 'Riwayat pengajuan koreksi Anda. Keputusan dibuat admin; rekap diperbarui otomatis setelah disetujui.'
      "
    >
      <template v-if="!isAdmin" #actions>
        <span class="st-chip">Pengusul: {{ auth.account?.full_name ?? '-' }}</span>
      </template>
    </UiPageHeader>

    <p v-if="message" class="st-alert st-alert--success" role="status">{{ message }}</p>
    <p v-if="error" class="st-alert st-alert--error" role="alert">{{ error }}</p>

    <div class="st-grid3">
      <UiCard title="Menunggu Peninjauan" subtitle="Butuh tindakan">
        <p class="st-kpi">{{ counts.pending }} <small>Pengajuan</small></p>
      </UiCard>
      <UiCard title="Disetujui" subtitle="Rekap diperbarui">
        <p class="st-kpi">{{ counts.approved }} <small>Pengajuan</small></p>
      </UiCard>
      <UiCard title="Ditolak" subtitle="Status final tidak berubah">
        <p class="st-kpi">{{ counts.rejected }} <small>Pengajuan</small></p>
      </UiCard>
    </div>

    <div v-if="!detail" class="st-card">
      <div class="st-scope" role="tablist" aria-label="Status koreksi">
        <button
          v-for="t in ['pending', 'approved', 'rejected'] as const"
          :key="t"
          role="tab"
          type="button"
          :class="{ 'st-scope--active': tab === t }"
          :aria-selected="tab === t"
          :data-testid="`correction-tab-${t}`"
          @click="tab = t"
        >
          {{
            t === 'pending'
              ? `Menunggu Keputusan (${counts.pending})`
              : t === 'approved'
                ? `Disetujui (${counts.approved})`
                : `Ditolak (${counts.rejected})`
          }}
        </button>
      </div>
      <form class="st-toolbar" @submit.prevent>
        <UiSearchInput
          v-model="searchText"
          placeholder="Cari nama siswa atau NIS…"
          aria-label="Cari koreksi"
        />
      </form>
      <p v-if="isLoading" class="st-table__muted">Memuat antrean…</p>
      <div v-else-if="filteredItems.length" class="st-tablewrap">
        <table class="st-table">
          <thead>
            <tr>
              <th scope="col">No</th>
              <th scope="col">Nama Siswa</th>
              <th scope="col">Sesi Praktikum</th>
              <th scope="col">Status Lama</th>
              <th scope="col">Status Usulan</th>
              <th scope="col">Alasan Pengajuan</th>
              <th scope="col">Tanggal Pengajuan</th>
              <th scope="col" class="st-table__actions">Aksi</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(c, idx) in filteredItems" :key="c.id" data-testid="correction-row">
              <td>{{ idx + 1 }}</td>
              <td>
                <span class="st-identity">
                  <UiAvatar :name="studentNameOf(c)" />
                  <span
                    ><strong>{{ studentNameOf(c) }}</strong
                    ><br /><span class="st-table__muted">{{ ticketOf(c.id) }}</span></span
                  >
                </span>
              </td>
              <td>{{ sessionNameOf(c) }}</td>
              <td>
                <UiBadge :tone="statusTone(c.previous_status)">{{
                  statusLabel(c.previous_status)
                }}</UiBadge>
              </td>
              <td>
                <UiBadge :tone="statusTone(c.corrected_status)">{{
                  statusLabel(c.corrected_status)
                }}</UiBadge>
              </td>
              <td class="st-table__muted">{{ c.reason }}</td>
              <td class="st-table__mono">{{ c.created_at.slice(0, 16).replace('T', ' ') }}</td>
              <td class="st-table__actions">
                <RouterLink class="st-btnlink" :to="`/app/corrections/${c.id}`"
                  >Tinjau →</RouterLink
                >
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <UiEmptyState
        v-else
        :title="`Belum ada pengajuan ${tab}`"
        description="Pengajuan baru dari roster atau laporan akan muncul di sini."
      />
    </div>

    <div v-else class="st-page" data-testid="correction-detail">
      <div class="st-detailhead">
        <UiButton variant="text" size="sm" @click="detail = null"
          >← Kembali ke Antrean Koreksi</UiButton
        >
        <UiBadge tone="neutral">ID Tiket: {{ ticketOf(detail.id) }}</UiBadge>
      </div>
      <p v-if="detailLoading" class="st-table__muted">Memuat detail…</p>
      <p v-if="detailError" class="st-alert st-alert--error" role="alert">{{ detailError }}</p>
      <div class="st-card">
        <div class="st-detailhead">
          <div>
            <h2 class="st-card__title">Tinjau Pengajuan {{ ticketOf(detail.id) }}</h2>
            <p class="st-table__muted">
              Diajukan {{ detail.created_at.slice(0, 16).replace('T', ' ') }} via portal presensi.
            </p>
          </div>
          <UiBadge
            :tone="
              detail.decision_status === 'approved'
                ? 'present'
                : detail.decision_status === 'rejected'
                  ? 'absent'
                  : 'late'
            "
            >{{
              detail.decision_status === 'pending'
                ? 'Menunggu Keputusan'
                : decisionLabel(detail.decision_status)
            }}</UiBadge
          >
        </div>
        <div v-if="isAdmin && detail.decision_status === 'pending'" class="st-detailactions">
          <UiButton variant="danger" data-testid="correction-reject" @click="decide('rejected')"
            ><span class="st-material-icon" aria-hidden="true">close</span>Tolak Pengajuan</UiButton
          >
          <UiButton variant="primary" data-testid="correction-approve" @click="decide('approved')"
            ><span class="st-material-icon" aria-hidden="true">check_circle</span>Setujui
            Koreksi</UiButton
          >
        </div>
      </div>
      <div class="st-split">
        <div class="st-page">
          <div class="st-card">
            <div class="st-detailhead">
              <h2 class="st-card__title">Perubahan Status Presensi</h2>
            </div>
            <div class="st-compare">
              <div class="st-compare__card">
                <p class="st-compare__label">Status tercatat saat ini</p>
                <p>
                  <UiBadge :tone="statusTone(detail.previous_status)">{{
                    statusLabel(detail.previous_status)
                  }}</UiBadge>
                </p>
                <p class="st-table__muted">Status yang dipakai rekap saat ini.</p>
              </div>
              <span class="st-material-icon st-compare__arrow" aria-hidden="true"
                >arrow_forward</span
              >
              <div class="st-compare__card st-compare__card--new">
                <p class="st-compare__label">Usulan status koreksi</p>
                <p>
                  <UiBadge :tone="statusTone(detail.corrected_status)">{{
                    statusLabel(detail.corrected_status)
                  }}</UiBadge>
                </p>
                <p class="st-table__muted">Berlaku setelah admin menyetujui.</p>
              </div>
            </div>
          </div>
          <div class="st-card">
            <h2 class="st-card__title">Alasan Pengajuan Koreksi</h2>
            <p class="st-table__muted">Pernyataan pengaju:</p>
            <blockquote class="st-quote">“{{ detail.reason }}”</blockquote>
          </div>
          <div class="st-card">
            <h2 class="st-card__title">Catatan Peninjauan Administrasi</h2>
            <div v-if="isAdmin && detail.decision_status === 'pending'">
              <UiField
                label="Catatan Keputusan (wajib bila menolak)"
                hint="Alasan penolakan wajib diisi."
              >
                <UiInput
                  v-model="decisionNote"
                  data-testid="correction-decision-note"
                  maxlength="2000"
                  placeholder="Contoh: bukti belum cukup, ajukan ulang dengan surat"
                />
              </UiField>
            </div>
            <p v-else-if="detail.decision_note" class="st-quote">{{ detail.decision_note }}</p>
            <p v-else class="st-table__muted">Belum ada catatan peninjauan.</p>
          </div>
        </div>
        <div class="st-page">
          <div class="st-card">
            <h2 class="st-card__title">Identitas Siswa</h2>
            <p class="st-identity">
              <UiAvatar :name="studentNameOf(detail)" />
              <span
                ><strong>{{ studentNameOf(detail) }}</strong
                ><br /><span class="st-table__muted">{{ ticketOf(detail.id) }}</span></span
              >
            </p>
          </div>
          <div class="st-card">
            <h2 class="st-card__title">Konteks Sesi Praktikum</h2>
            <dl class="st-kv">
              <div>
                <dt>Sesi Praktikum</dt>
                <dd>{{ sessionNameOf(detail) }}</dd>
              </div>
            </dl>
          </div>
          <div class="st-card">
            <h2 class="st-card__title">Jejak Pengajuan</h2>
            <dl class="st-kv">
              <div>
                <dt>Diajukan</dt>
                <dd>{{ detail.created_at.slice(0, 16).replace('T', ' ') }}</dd>
              </div>
              <div>
                <dt>Diputuskan</dt>
                <dd>
                  {{
                    detail.decided_at
                      ? detail.decided_at.slice(0, 16).replace('T', ' ')
                      : 'Menunggu keputusan'
                  }}
                </dd>
              </div>
            </dl>
          </div>
        </div>
      </div>
    </div>
    <div v-if="!isAdmin && !detail" class="st-card">
      <h2 class="st-card__title">Ketentuan &amp; Prosedur Verifikasi Koreksi</h2>
      <p class="st-table__muted">
        Pengajuan koreksi diverifikasi dan diputuskan administrator. Status rekap diperbarui
        otomatis setelah disetujui. Guru tidak dapat menyetujui koreksi sendiri.
      </p>
    </div>
  </div>
</template>
