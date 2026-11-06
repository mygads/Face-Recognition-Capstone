<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import {
  ApiError,
  getPublicDisplay,
  listPublicLaboratories,
  type PublicDisplay,
  type PublicLaboratory,
} from '../api/client'

const labs = ref<PublicLaboratory[]>([])
const labId = ref('')
const pin = ref('')
const display = ref<PublicDisplay | null>(null)
const error = ref<string | null>(null)
const isLoadingLabs = ref(false)
const isLoadingDisplay = ref(false)
let timer: ReturnType<typeof setInterval> | undefined

function formatError(err: unknown): string {
  if (err instanceof ApiError) return err.message
  return 'Layar tidak dapat dimuat.'
}

async function loadLabs(): Promise<void> {
  isLoadingLabs.value = true
  try {
    labs.value = await listPublicLaboratories()
    if (!labId.value && labs.value.length) labId.value = labs.value[0].id
  } catch (err) {
    error.value = formatError(err)
  } finally {
    isLoadingLabs.value = false
  }
}

async function loadDisplay(silent = false): Promise<void> {
  if (!labId.value || !pin.value) return
  if (!silent) isLoadingDisplay.value = true
  try {
    display.value = await getPublicDisplay(labId.value, pin.value)
    error.value = null
  } catch (err) {
    if (!silent) error.value = formatError(err)
  } finally {
    if (!silent) isLoadingDisplay.value = false
  }
}

function startPolling(): void {
  stopPolling()
  timer = setInterval(() => void loadDisplay(true), 5000)
}

function stopPolling(): void {
  if (timer) clearInterval(timer)
  timer = undefined
}

async function submit(): Promise<void> {
  await loadDisplay()
  startPolling()
}

onMounted(() => void loadLabs())
onBeforeUnmount(() => stopPolling())
</script>

<template>
  <section class="display-view" aria-label="Layar presensi publik">
    <div class="display-view__setup">
      <p class="master-data__eyebrow">Layar presensi · tanpa login</p>
      <h1>Presensi Praktikum — Layar Lab</h1>
      <p class="accounts-view__hint">
        Pilih laboratorium lalu masukkan PIN layar yang diberikan admin. Tampilan ini fullscreen
        untuk siswa: hanya nama, NIS, dan status sudah-masuk / belum.
      </p>
      <form class="master-data__form" @submit.prevent="submit">
        <label>
          Laboratorium
          <select v-model="labId" data-testid="display-lab-select" required>
            <option value="" disabled>Pilih lab</option>
            <option v-for="lab in labs" :key="lab.id" :value="lab.id">
              {{ lab.code }} — {{ lab.name }}
            </option>
          </select>
        </label>
        <label>
          PIN layar
          <input
            v-model="pin"
            type="password"
            inputmode="numeric"
            minlength="4"
            maxlength="32"
            placeholder="••••"
            data-testid="display-pin-input"
            required
          />
        </label>
        <div class="master-data__form-actions">
          <button class="button button--primary" type="submit" :disabled="isLoadingDisplay">
            {{ isLoadingDisplay ? 'Memuat…' : 'Tampilkan layar' }}
          </button>
        </div>
      </form>
      <p v-if="error" class="master-data__alert" role="alert">{{ error }}</p>
    </div>

    <div v-if="display" class="display-view__board" data-testid="display-board">
      <div class="display-view__board-head">
        <h2>{{ display.laboratory_name }}</h2>
        <p v-if="display.subject">
          {{ display.subject }} · {{ display.status }} · Hadir {{ display.present_count }} ·
          Terlambat {{ display.late_count }} / {{ display.total_roster }}
        </p>
        <p v-else>Belum ada sesi aktif di lab ini.</p>
      </div>
      <ul v-if="display.students.length" class="display-view__grid">
        <li
          v-for="s in display.students"
          :key="s.student_number"
          class="display-view__card"
          :class="{
            'display-view__card--present': s.status === 'present',
            'display-view__card--late': s.status === 'late',
          }"
          data-testid="display-student"
        >
          <strong>{{ s.full_name }}</strong>
          <small>{{ s.student_number }}</small>
          <span>{{
            s.status === 'present'
              ? 'SUDAH MASUK ✓'
              : s.status === 'late'
                ? 'TERLAMBAT'
                : s.status === 'excused'
                  ? 'IZIN'
                  : 'BELUM MASUK'
          }}</span>
        </li>
      </ul>
    </div>
  </section>
</template>

<style scoped>
.display-view {
  min-height: 100vh;
  background: #0f172a;
  color: #f8fafc;
  padding: 24px;
}
.display-view__setup {
  max-width: 560px;
  margin: 0 auto 24px;
  background: #1e293b;
  border-radius: 12px;
  padding: 20px;
}
.display-view__board-head {
  text-align: center;
  margin-bottom: 16px;
}
.display-view__grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 12px;
  list-style: none;
  padding: 0;
}
.display-view__card {
  background: #334155;
  border-radius: 10px;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  border: 2px solid transparent;
}
.display-view__card--present {
  border-color: #22c55e;
}
.display-view__card--late {
  border-color: #f59e0b;
}
</style>
