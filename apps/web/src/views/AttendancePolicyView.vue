<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import UiButton from '../components/ui/UiButton.vue'
import UiCard from '../components/ui/UiCard.vue'
import UiInput from '../components/ui/UiInput.vue'
import UiPageHeader from '../components/ui/UiPageHeader.vue'
import UiStat from '../components/ui/UiStat.vue'
import {
  ApiError,
  getAtRiskPolicy,
  getSessionOpeningPolicy,
  saveSessionOpeningPolicy,
  updateAtRiskPolicy,
  type AtRiskPolicyResponse,
  type SessionOpeningPolicyResponse,
} from '../api/client'

const policy = ref<SessionOpeningPolicyResponse | null>(null)
const atRisk = ref<AtRiskPolicyResponse | null>(null)
const form = ref({
  auto_open_minutes_before: 0,
  auto_open_minutes_after: 15,
  default_grace_period_minutes: 15,
})
const ewsForm = ref({ window_days: 30, absence_pct_threshold: 20, late_count_threshold: 3 })
// Contoh waktu lokal (Asia/Jakarta) agar dampak angka mudah dibaca.
// Jadwal contoh 13.00: jendela buka, batas terlambat, dan tutup otomatis di akhir jadwal.
const exampleOpen = computed(() => {
  const before = form.value.auto_open_minutes_before
  const after = form.value.auto_open_minutes_after
  const pad = (n: number): string => String(n).padStart(2, '0')
  const start = 13 * 60
  const fmt = (m: number): string => `${pad(Math.floor(m / 60))}.${pad(m % 60)}`
  const late = start + form.value.default_grace_period_minutes
  return (
    `Contoh jadwal 13.00: sesi boleh dibuka ${fmt(start - before)}-${fmt(start + after)}; ` +
    `terlambat setelah ${fmt(late)}; sesi ditutup otomatis pada jam akhir jadwal.`
  )
})
const error = ref<string | null>(null)
const message = ref<string | null>(null)
const isSaving = ref(false)

function formatError(err: unknown): string {
  if (err instanceof ApiError) return err.message
  return 'Kebijakan belum dapat dimuat.'
}

async function load(): Promise<void> {
  error.value = null
  try {
    policy.value = await getSessionOpeningPolicy()
    atRisk.value = await getAtRiskPolicy()
    form.value = {
      auto_open_minutes_before: policy.value.auto_open_minutes_before,
      auto_open_minutes_after: policy.value.auto_open_minutes_after,
      default_grace_period_minutes: policy.value.default_grace_period_minutes,
    }
    ewsForm.value = {
      window_days: atRisk.value.window_days ?? 30,
      absence_pct_threshold: atRisk.value.absence_pct_threshold ?? 20,
      late_count_threshold: atRisk.value.late_count_threshold ?? 3,
    }
  } catch (err) {
    error.value = formatError(err)
  }
}

async function save(): Promise<void> {
  if (isSaving.value) return
  isSaving.value = true
  message.value = null
  try {
    policy.value = await saveSessionOpeningPolicy({
      mode: policy.value?.mode ?? 'manual',
      ...form.value,
    })
    atRisk.value = await updateAtRiskPolicy({ ...ewsForm.value })
    message.value = 'Kebijakan tersimpan. Mode global lama diabaikan; worker memakai mode per guru.'
  } catch (err) {
    error.value = formatError(err)
  } finally {
    isSaving.value = false
  }
}

onMounted(() => void load())
</script>

<template>
  <div class="st-page" aria-label="Kebijakan presensi">
    <UiPageHeader
      eyebrow="Administrasi · parameter sekolah yang efektif"
      title="Kebijakan Presensi Laboratorium"
      description="Parameter operasional mesin presensi otomatis, toleransi kehadiran, dan ambang batas EWS efektif sekolah. Nilai dibaca worker secara deterministik."
    >
      <template #actions>
        <UiButton variant="secondary" type="button" @click="load">Muat ulang</UiButton>
      </template>
    </UiPageHeader>
    <p v-if="error" class="st-alert st-alert--error" role="alert">{{ error }}</p>
    <p v-if="message" class="st-alert st-alert--success" role="status">{{ message }}</p>

    <div class="st-kpi">
      <UiStat
        label="Buka otomatis"
        :value="`${form.auto_open_minutes_before} mnt sblm jadwal`"
        caption="Kiosk dan sensor standby sebelum praktikum"
      />
      <UiStat
        label="Batas tepat waktu"
        :value="`+${form.default_grace_period_minutes} mnt`"
        caption="Validasi status Hadir Tepat Waktu berakhir"
        tone="success"
      />
      <UiStat
        label="Jendela buka"
        :value="`+${form.auto_open_minutes_after} mnt`"
        caption="Sesi boleh dibuka sesudah jadwal"
      />
      <UiStat
        label="Ambang EWS"
        :value="`${ewsForm.absence_pct_threshold}% / ${ewsForm.late_count_threshold}x`"
        caption="Absen / terlambat kumulatif"
        tone="warning"
      />
    </div>

    <div class="st-grid2">
      <UiCard
        title="Panel 1: Parameter sesi & toleransi waktu"
        subtitle="Konfigurasi runtime untuk gateway IoT presensi muka siswa"
      >
        <form style="display: grid; gap: 10px" @submit.prevent="save">
          <label class="st-field"
            ><span>Buka otomatis (menit sebelum jadwal)</span>
            <UiInput
              v-model.number="form.auto_open_minutes_before"
              type="number"
              min="0"
              max="15"
              data-testid="policy-before"
            />
          </label>
          <label class="st-field"
            ><span>Buka otomatis (menit sesudah jadwal)</span>
            <UiInput
              v-model.number="form.auto_open_minutes_after"
              type="number"
              min="0"
              max="15"
              data-testid="policy-after"
            />
          </label>
          <label class="st-field"
            ><span>Toleransi terlambat (menit, default sesi baru)</span>
            <UiInput
              v-model.number="form.default_grace_period_minutes"
              type="number"
              min="0"
              max="1440"
              data-testid="policy-grace"
            />
          </label>
          <p class="st-table__muted" data-testid="policy-example">{{ exampleOpen }}</p>
          <UiButton type="submit" variant="primary" :disabled="isSaving" data-testid="policy-save">
            {{ isSaving ? 'Menyimpan…' : 'Simpan kebijakan' }}
          </UiButton>
        </form>
      </UiCard>
      <UiCard title="Panel 3: Ambang batas EWS" subtitle="Sistem peringatan dini akademik">
        <form style="display: grid; gap: 10px" @submit.prevent="save">
          <label class="st-field"
            ><span>Jendela analisis (hari)</span>
            <UiInput v-model.number="ewsForm.window_days" type="number" min="1" max="365" />
          </label>
          <label class="st-field"
            ><span>Ambang absen (%)</span>
            <UiInput
              v-model.number="ewsForm.absence_pct_threshold"
              type="number"
              min="0"
              max="100"
              step="0.1"
              data-testid="policy-ews-absent"
            />
          </label>
          <label class="st-field"
            ><span>Ambang terlambat (kali)</span>
            <UiInput
              v-model.number="ewsForm.late_count_threshold"
              type="number"
              min="1"
              max="100"
              data-testid="policy-ews-late"
            />
          </label>
          <UiButton
            type="submit"
            variant="primary"
            :disabled="isSaving"
            data-testid="policy-save-ews"
          >
            {{ isSaving ? 'Menyimpan…' : 'Simpan ambang EWS' }}
          </UiButton>
        </form>
      </UiCard>
    </div>
  </div>
</template>
