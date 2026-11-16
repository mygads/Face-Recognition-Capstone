<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  ApiError,
  createKiosk,
  listDevices,
  listKiosks,
  listLaboratories,
  resetKioskPin,
  revokeKiosk,
  updateKiosk,
  type Device,
  type Kiosk,
  type Laboratory,
} from '../api/client'
import { useAuthStore } from '../stores/auth'
import UiBadge from '../components/ui/UiBadge.vue'
import UiButton from '../components/ui/UiButton.vue'
import UiCard from '../components/ui/UiCard.vue'
import UiInput from '../components/ui/UiInput.vue'
import UiPageHeader from '../components/ui/UiPageHeader.vue'
import UiSelect from '../components/ui/UiSelect.vue'

const auth = useAuthStore()
const isAdmin = computed(() => auth.account?.roles.includes('ADMIN') ?? false)
const kiosks = ref<Kiosk[]>([])
const devices = ref<Device[]>([])
const labs = ref<Laboratory[]>([])
const isLoading = ref(false)
const error = ref<string | null>(null)
const message = ref<string | null>(null)
const lastPin = ref<string | null>(null)
const form = ref({ device_id: '', laboratory_id: '', display_name: '', camera_label: '',
  token_ttl_hours: '' as string })

function formatError(err: unknown): string {
  if (err instanceof ApiError) return err.message
  return 'Data layar presensi belum dapat dimuat.'
}

async function load(): Promise<void> {
  isLoading.value = true
  error.value = null
  try {
    const [k, d, l] = await Promise.all([
      listKiosks({ limit: 100, offset: 0 }),
      listDevices({ limit: 100, offset: 0 }),
      listLaboratories({ limit: 100, offset: 0 }),
    ])
    kiosks.value = k.items
    devices.value = d.items
    labs.value = l.items
    if (!form.value.device_id && d.items.length) {
      form.value.device_id = d.items[0].device_id
      form.value.laboratory_id = d.items[0].laboratory_id
    }
  } catch (err) {
    error.value = formatError(err)
  } finally {
    isLoading.value = false
  }
}

async function submit(): Promise<void> {
  message.value = null
  lastPin.value = null
  try {
    await createKiosk({
      device_id: form.value.device_id,
      laboratory_id: form.value.laboratory_id,
      display_name: form.value.display_name.trim(),
      camera_label: form.value.camera_label.trim() || null,
      token_ttl_hours: form.value.token_ttl_hours === '' ? null : Number(form.value.token_ttl_hours),
    })
    form.value.display_name = ''
    form.value.token_ttl_hours = ''
    message.value = 'Layar terdaftar. Buat PIN lalu aktifkan di komputer lab (/presensi).'
    await load()
  } catch (err) {
    error.value = formatError(err)
  }
}

async function makePin(k: Kiosk): Promise<void> {
  try {
    const res = await resetKioskPin(k.id)
    lastPin.value = res.temporary_pin
    message.value = `PIN baru layar "${k.display_name}" (sekali tampil).`
    await load()
  } catch (err) {
    error.value = formatError(err)
  }
}

async function setTtl(k: Kiosk, raw: string): Promise<void> {
  try {
    await updateKiosk(k.id, {
      token_ttl_hours: raw === '' ? null : Number(raw),
    })
    message.value = `TTL token layar "${k.display_name}" diperbarui.`
    await load()
  } catch (err) {
    error.value = formatError(err)
  }
}

async function toggle(k: Kiosk): Promise<void> {
  try {
    await updateKiosk(k.id, { is_active: !k.is_active })
    await load()
  } catch (err) {
    error.value = formatError(err)
  }
}

async function revoke(k: Kiosk): Promise<void> {
  try {
    await revokeKiosk(k.id)
    message.value = `Akses layar "${k.display_name}" dicabut.`
    await load()
  } catch (err) {
    error.value = formatError(err)
  }
}

onMounted(() => void load())
</script>

<template>
  <div class="st-page" aria-label="Layar presensi">
    <UiPageHeader
      eyebrow="Infrastruktur · kiosk siswa"
      title="Layar Presensi"
      description="Admin memilih perangkat, memberi nama layar, membuat/reset PIN, dan mencabut akses. PIN baru hanya tampil sekali."
    >
      <template #actions>
        <UiButton variant="secondary" type="button" @click="load">Muat ulang</UiButton>
      </template>
    </UiPageHeader>
    <p v-if="isLoading" class="st-table__muted">Memuat…</p>
    <p v-if="error" class="st-alert st-alert--error" role="alert">{{ error }}</p>
    <p v-if="message" class="st-alert st-alert--success" role="status">{{ message }}</p>
    <p v-if="lastPin" class="st-alert st-alert--success" data-testid="kiosk-pin-once">
      PIN sementara (sekali tampil): <strong>{{ lastPin }}</strong>
    </p>
    <UiCard
      v-if="isAdmin"
      title="Daftarkan layar"
      subtitle="Pilih perangkat, beri nama layar, lalu buat PIN."
    >
      <form style="display: grid; gap: 10px" @submit.prevent="submit">
        <div class="st-grid2">
          <label class="st-field"
            ><span>Perangkat</span>
            <UiSelect v-model="form.device_id" data-testid="kiosk-device" required>
              <option v-for="d in devices" :key="d.device_id" :value="d.device_id">
                {{ d.name }} · {{ d.laboratory_name }}
              </option>
            </UiSelect>
          </label>
          <label class="st-field"
            ><span>Laboratorium</span>
            <UiSelect v-model="form.laboratory_id" data-testid="kiosk-lab" required>
              <option v-for="l in labs" :key="l.id" :value="l.id">
                {{ l.code }} - {{ l.name }}
              </option>
            </UiSelect>
          </label>
          <label class="st-field"
            ><span>Nama layar</span>
            <UiInput
              v-model="form.display_name"
              data-testid="kiosk-name"
              maxlength="120"
              required
            />
          </label>
          <label class="st-field"
            ><span>Label kamera</span>
            <UiInput v-model="form.camera_label" data-testid="kiosk-camera" maxlength="120" />
          </label>
          <label class="st-field"
            ><span>TTL token (jam)</span>
            <UiSelect v-model="form.token_ttl_hours" data-testid="kiosk-ttl">
              <option value="">Default global</option>
              <option value="1">1 jam</option>
              <option value="2">2 jam</option>
              <option value="4">4 jam</option>
              <option value="8">8 jam</option>
              <option value="12">12 jam</option>
            </UiSelect>
          </label>
        </div>
        <div>
          <UiButton type="submit" variant="primary" data-testid="kiosk-create"
            >Daftarkan layar</UiButton
          >
        </div>
      </form>
    </UiCard>
    <UiCard v-if="kiosks.length" title="Layar terdaftar" :subtitle="`${kiosks.length} layar`">
      <div class="st-tablewrap">
        <table class="st-table">
          <thead>
            <tr>
              <th>Layar</th>
              <th>Kamera</th>
              <th>PIN</th>
              <th>TTL token</th>
              <th>Status</th>
              <th><span class="st-table__actions">Aksi</span></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="k in kiosks" :key="k.id" data-testid="kiosk-row">
              <td>
                <strong>{{ k.display_name }}</strong>
              </td>
              <td>{{ k.camera_label ?? '-' }}</td>
              <td>
                <UiBadge :tone="k.has_pin ? 'present' : 'neutral'">{{
                  k.has_pin ? 'Terpasang' : 'Belum'
                }}</UiBadge>
              </td>
              <td>
                <UiSelect
                  :model-value="k.token_ttl_hours == null ? '' : String(k.token_ttl_hours)"
                  :aria-label="`TTL token ${k.display_name}`"
                  data-testid="kiosk-ttl-row"
                  @update:model-value="(v) => void setTtl(k, String(v ?? ''))"
                >
                  <option value="">Default</option>
                  <option value="1">1 jam</option>
                  <option value="2">2 jam</option>
                  <option value="4">4 jam</option>
                  <option value="8">8 jam</option>
                  <option value="12">12 jam</option>
                </UiSelect>
              </td>
              <td>
                <UiBadge :tone="k.is_active ? 'present' : 'neutral'">{{
                  k.is_active ? 'Aktif' : 'Nonaktif'
                }}</UiBadge>
              </td>
              <td v-if="isAdmin" class="st-table__actions">
                <button class="st-rowbtn" type="button" @click="makePin(k)">Buat/reset PIN</button>
                <button class="st-rowbtn" type="button" @click="toggle(k)">
                  {{ k.is_active ? 'Nonaktifkan' : 'Aktifkan' }}
                </button>
                <button class="st-rowbtn st-link--danger" type="button" @click="revoke(k)">
                  Cabut
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </UiCard>
  </div>
</template>
