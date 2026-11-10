<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ApiError, listAccounts, listAuditActivity, type AuditEntry } from '../api/client'
import { formatDateTimeLocal } from '../utils/dateFormat'
import UiButton from '../components/ui/UiButton.vue'
import UiCard from '../components/ui/UiCard.vue'
import UiEmptyState from '../components/ui/UiEmptyState.vue'
import UiInput from '../components/ui/UiInput.vue'
import UiPageHeader from '../components/ui/UiPageHeader.vue'

const expandedId = ref<string | null>(null)

const items = ref<AuditEntry[]>([])
const total = ref(0)
const actorNames = ref<Record<string, string>>({})

function actorLabel(id: string | null | undefined): string {
  if (!id) return '—'
  return actorNames.value[id] ?? id
}

async function loadActorNames(): Promise<void> {
  try {
    const page = await listAccounts({ limit: 100, offset: 0 })
    const map: Record<string, string> = {}
    for (const a of page.items) map[a.id] = `${a.full_name} · ${a.email}`
    actorNames.value = map
  } catch {
    actorNames.value = {}
  }
}
const action = ref('')
const entityType = ref('')
const isLoading = ref(false)
const error = ref<string | null>(null)

function formatError(err: unknown): string {
  if (err instanceof ApiError) return err.message
  return 'Audit belum dapat dimuat.'
}

async function load(): Promise<void> {
  isLoading.value = true
  error.value = null
  try {
    const page = await listAuditActivity({
      action: action.value || undefined,
      entity_type: entityType.value || undefined,
      limit: 50,
      offset: 0,
    })
    items.value = page.items
    total.value = page.pagination.total
  } catch (err) {
    error.value = formatError(err)
  } finally {
    isLoading.value = false
  }
}

onMounted(() => {
  void loadActorNames()
  void load()
})
</script>

<template>
  <div class="st-page" aria-label="Audit aktivitas">
    <UiPageHeader
      eyebrow="Administrasi · jejak teraudit"
      title="Audit Aktivitas & Integritas Sistem"
      description="Jejak kepatuhan operasional akademik presensi. Sandi, PIN, token, gambar, dan embedding disembunyikan dari respons."
    >
      <template #actions>
        <UiButton variant="secondary" type="button" @click="load">Muat ulang</UiButton>
      </template>
    </UiPageHeader>
    <UiCard title="Parameter forensik log">
      <form style="display: grid; gap: 10px" @submit.prevent="load">
        <div class="st-grid2">
          <label class="st-field"
            ><span>Aksi</span>
            <UiInput
              v-model="action"
              data-testid="audit-action"
              placeholder="mis. attendance.correction.decided"
            />
          </label>
          <label class="st-field"
            ><span>Tipe entitas</span>
            <UiInput
              v-model="entityType"
              data-testid="audit-entity"
              placeholder="mis. attendance_correction"
            />
          </label>
        </div>
        <div>
          <UiButton type="submit" variant="primary" data-testid="audit-filter"
            >Terapkan filter</UiButton
          >
        </div>
      </form>
    </UiCard>
    <p v-if="isLoading" class="st-table__muted">Memuat…</p>
    <p v-if="error" class="st-alert st-alert--error" role="alert">{{ error }}</p>
    <p class="st-table__muted" data-testid="audit-total">Total {{ total }} peristiwa</p>
    <UiCard v-if="items.length" title="Peristiwa">
      <div class="st-tablewrap">
        <table class="st-table">
          <thead>
            <tr>
              <th>Waktu & tanggal</th>
              <th>Aksi</th>
              <th>Entitas</th>
              <th>Aktor</th>
              <th><span class="st-table__actions">Detail</span></th>
            </tr>
          </thead>
          <tbody>
            <template v-for="a in items" :key="a.id">
              <tr data-testid="audit-row">
                <td class="st-table__mono">{{ formatDateTimeLocal(a.created_at) }}</td>
                <td>{{ a.action }}</td>
                <td>{{ a.entity_type }}</td>
                <td>
                  <strong>{{ actorLabel(a.actor_user_id).split(' · ')[0] }}</strong
                  ><br /><span class="st-table__muted st-table__mono">{{
                    actorLabel(a.actor_user_id).split(' · ')[1] ?? a.actor_user_id ?? '—'
                  }}</span>
                </td>
                <td class="st-table__actions">
                  <button
                    v-if="a.before_state || a.after_state"
                    class="st-rowbtn"
                    type="button"
                    @click="expandedId = expandedId === a.id ? null : a.id"
                  >
                    {{ expandedId === a.id ? 'Sembunyikan' : 'Lihat' }}
                  </button>
                  <span v-else>-</span>
                </td>
              </tr>
              <tr v-if="expandedId === a.id">
                <td colspan="5">
                  <pre v-if="a.before_state">Sebelum: {{ a.before_state }}</pre>
                  <pre v-if="a.after_state">Sesudah: {{ a.after_state }}</pre>
                </td>
              </tr>
            </template>
          </tbody>
        </table>
      </div>
    </UiCard>
    <UiEmptyState v-else-if="!isLoading" title="Belum ada peristiwa audit" />
  </div>
</template>
