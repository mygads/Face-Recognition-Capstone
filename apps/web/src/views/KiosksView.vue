<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  ApiError,
  createKiosk,
  listDevices,
  listKiosks,
  listLaboratories,
  resetKioskPin,
  revokeLaboratoryDisplayPin,
  revokeKiosk,
  setLaboratoryDisplayPin,
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
import UiModal from '../components/ui/UiModal.vue'
import UiPageHeader from '../components/ui/UiPageHeader.vue'
import UiSelect from '../components/ui/UiSelect.vue'

const auth = useAuthStore()
const isAdmin = computed(() => auth.account?.roles.includes('ADMIN') ?? false)
const kiosks = ref<Kiosk[]>([])
const devices = ref<Device[]>([])
const labs = ref<Laboratory[]>([])
const displayPinDrafts = ref<Record<string, string>>({})
const displayPinMessage = ref<string | null>(null)
const displayPinError = ref<string | null>(null)
const editingDisplayPinLabId = ref<string | null>(null)
const editingDisplayPinLab = computed(
  () => labs.value.find((lab) => lab.id === editingDisplayPinLabId.value) ?? null,
)
const isSavingDisplayPin = ref(false)
const isRegisterDialogOpen = ref(false)
const isCreatingKiosk = ref(false)
const registrationError = ref<string | null>(null)
const editingKioskId = ref<string | null>(null)
const kioskEditError = ref<string | null>(null)
const editingKiosk = computed(
  () => kiosks.value.find((kiosk) => kiosk.id === editingKioskId.value) ?? null,
)
const kioskEditForm = ref({ display_name: '', camera_label: '', token_ttl_hours: '' })
const deletingDisplayPinLabId = ref<string | null>(null)
const deletingDisplayPinLab = computed(
  () => labs.value.find((lab) => lab.id === deletingDisplayPinLabId.value) ?? null,
)
const isDeletingDisplayPin = ref(false)
const isLoading = ref(false)
const error = ref<string | null>(null)
const message = ref<string | null>(null)
const lastPin = ref<string | null>(null)
const form = ref({
  device_id: '',
  display_name: '',
  camera_label: '',
  token_ttl_hours: '' as string,
})
const selectedDevice = computed(
  () => devices.value.find((device) => device.device_id === form.value.device_id) ?? null,
)

function kioskDeviceName(kiosk: Kiosk): string {
  return (
    devices.value.find((device) => device.device_id === kiosk.device_id)?.name ??
    'Perangkat tidak tersedia'
  )
}

function kioskLaboratory(kiosk: Kiosk): Laboratory | undefined {
  return labs.value.find((laboratory) => laboratory.id === kiosk.laboratory_id)
}

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
  registrationError.value = null
  if (isCreatingKiosk.value) return
  isCreatingKiosk.value = true
  try {
    await createKiosk({
      device_id: form.value.device_id,
      laboratory_id: selectedDevice.value?.laboratory_id ?? '',
      display_name: form.value.display_name.trim(),
      camera_label: form.value.camera_label.trim() || null,
      token_ttl_hours:
        form.value.token_ttl_hours === '' ? null : Number(form.value.token_ttl_hours),
    })
    form.value.display_name = ''
    form.value.token_ttl_hours = ''
    isRegisterDialogOpen.value = false
    message.value = 'Layar terdaftar. Buat PIN lalu aktifkan di komputer lab (/presensi).'
    await load()
  } catch (err) {
    registrationError.value = formatError(err)
  } finally {
    isCreatingKiosk.value = false
  }
}

function closeRegistrationDialog(): void {
  if (isCreatingKiosk.value) return
  isRegisterDialogOpen.value = false
  registrationError.value = null
}

function openKioskEdit(kiosk: Kiosk): void {
  editingKioskId.value = kiosk.id
  kioskEditForm.value = {
    display_name: kiosk.display_name,
    camera_label: kiosk.camera_label ?? '',
    token_ttl_hours: kiosk.token_ttl_hours === null ? '' : String(kiosk.token_ttl_hours),
  }
  kioskEditError.value = null
}

function closeKioskEdit(): void {
  editingKioskId.value = null
  kioskEditError.value = null
}

async function saveKioskEdit(): Promise<void> {
  const kiosk = editingKiosk.value
  if (!kiosk) return
  kioskEditError.value = null
  try {
    await updateKiosk(kiosk.id, {
      display_name: kioskEditForm.value.display_name.trim(),
      camera_label: kioskEditForm.value.camera_label.trim() || null,
      token_ttl_hours:
        kioskEditForm.value.token_ttl_hours === ''
          ? null
          : Number(kioskEditForm.value.token_ttl_hours),
    })
    message.value = `Pengaturan layar "${kioskEditForm.value.display_name.trim()}" diperbarui.`
    closeKioskEdit()
    await load()
  } catch (err) {
    kioskEditError.value = formatError(err)
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

function editDisplayPin(labId: string): void {
  editingDisplayPinLabId.value = labId
  displayPinDrafts.value[labId] = ''
  displayPinError.value = null
  displayPinMessage.value = null
}

function setDisplayPinDraft(labId: string, value: string): void {
  displayPinDrafts.value[labId] = value.replace(/[^0-9]/g, '').slice(0, 32)
  displayPinError.value = null
}

function cancelDisplayPinEdit(): void {
  const labId = editingDisplayPinLabId.value
  if (labId) displayPinDrafts.value[labId] = ''
  editingDisplayPinLabId.value = null
  displayPinError.value = null
}

function closeDeleteDisplayPin(): void {
  if (isDeletingDisplayPin.value) return
  deletingDisplayPinLabId.value = null
  displayPinError.value = null
}

async function deleteDisplayPin(labId: string): Promise<void> {
  if (isDeletingDisplayPin.value) return
  isDeletingDisplayPin.value = true
  displayPinError.value = null
  try {
    await revokeLaboratoryDisplayPin(labId)
    labs.value = labs.value.map((lab) =>
      lab.id === labId ? { ...lab, has_display_pin: false } : lab,
    )
    const lab = labs.value.find((item) => item.id === labId)
    displayPinMessage.value = `PIN publik ${lab?.code ?? ''} dihapus. Sesi layar publik yang aktif dicabut.`
    deletingDisplayPinLabId.value = null
  } catch (err) {
    displayPinError.value = formatError(err)
  } finally {
    isDeletingDisplayPin.value = false
  }
}

async function saveDisplayPin(labId: string): Promise<void> {
  if (isSavingDisplayPin.value) return
  const pin = displayPinDrafts.value[labId] ?? ''
  if (!/^[0-9]{4,32}$/.test(pin)) {
    displayPinError.value = 'PIN harus berisi 4–32 angka.'
    return
  }
  isSavingDisplayPin.value = true
  displayPinError.value = null
  displayPinMessage.value = null
  try {
    await setLaboratoryDisplayPin(labId, pin)
    labs.value = labs.value.map((lab) =>
      lab.id === labId ? { ...lab, has_display_pin: true } : lab,
    )
    const lab = labs.value.find((item) => item.id === labId)
    displayPinMessage.value = `PIN publik untuk ${lab?.code ?? labId} diperbarui.`
    displayPinDrafts.value[labId] = ''
    editingDisplayPinLabId.value = null
  } catch (err) {
    displayPinError.value = err instanceof Error ? err.message : 'Gagal menyimpan PIN.'
  } finally {
    isSavingDisplayPin.value = false
  }
}

onMounted(() => void load())
</script>

<template>
  <div class="st-page" aria-label="Layar presensi">
    <UiPageHeader
      eyebrow="Infrastruktur · kiosk siswa"
      title="Layar Presensi"
      description="Kelola layar kiosk, PIN, dan masa sesi akses."
    >
      <template #actions>
        <UiButton
          v-if="isAdmin"
          variant="primary"
          type="button"
          data-testid="open-kiosk-registration"
          @click="isRegisterDialogOpen = true"
        >
          <span class="st-material-icon" aria-hidden="true">add</span>
          Daftarkan layar
        </UiButton>
        <a
          class="st-btn st-btn--secondary"
          href="/presensi"
          target="_blank"
          rel="noopener noreferrer"
          data-testid="open-kiosk-new-tab"
        >
          <span class="st-material-icon" aria-hidden="true">open_in_new</span>
          Buka kiosk di tab baru
        </a>
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
      title="PIN publik per laboratorium"
      subtitle="PIN ini dipakai untuk masuk ke /display dalam mode laboratorium."
    >
      <p class="st-table__muted kiosks-view__section-note">
        Layar kiosk terdaftar memakai PIN kiosk sendiri di tabel Layar terdaftar.
      </p>
      <p v-if="displayPinMessage" class="st-alert st-alert--success" role="status">
        {{ displayPinMessage }}
      </p>
      <div class="st-tablewrap">
        <table class="st-table" data-testid="laboratory-display-pin-table">
          <thead>
            <tr>
              <th scope="col">Laboratorium</th>
              <th scope="col">Status PIN</th>
              <th scope="col"><span class="st-table__actions">Aksi</span></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="lab in labs" :key="lab.id">
              <td>
                <div class="kiosks-view__lab-cell">
                  <strong>{{ lab.name }}</strong>
                  <small>{{ lab.code }}</small>
                </div>
              </td>
              <td>
                <UiBadge :tone="lab.has_display_pin ? 'present' : 'neutral'">
                  {{ lab.has_display_pin ? 'Sudah diatur' : 'Belum diatur' }}
                </UiBadge>
              </td>
              <td class="st-table__actions">
                <UiButton
                  variant="outlined"
                  type="button"
                  :aria-label="`${lab.has_display_pin ? 'Ubah' : 'Atur'} PIN untuk ${lab.name}`"
                  :data-testid="`edit-public-pin-${lab.id}`"
                  @click="editDisplayPin(lab.id)"
                >
                  <span class="st-material-icon" aria-hidden="true">{{
                    lab.has_display_pin ? 'edit' : 'add'
                  }}</span>
                  {{ lab.has_display_pin ? 'Ubah PIN' : 'Atur PIN' }}
                </UiButton>
                <UiButton
                  v-if="lab.has_display_pin"
                  variant="danger-soft"
                  type="button"
                  :aria-label="`Hapus PIN untuk ${lab.name}`"
                  :data-testid="`delete-public-pin-${lab.id}`"
                  @click="deletingDisplayPinLabId = lab.id"
                >
                  <span class="st-material-icon" aria-hidden="true">delete</span>
                  Hapus
                </UiButton>
              </td>
            </tr>
            <tr v-if="!labs.length">
              <td colspan="3" class="master-data__empty">Belum ada laboratorium.</td>
            </tr>
          </tbody>
        </table>
      </div>
    </UiCard>
    <UiCard v-if="kiosks.length" title="Layar terdaftar" :subtitle="`${kiosks.length} layar`">
      <div class="st-tablewrap">
        <table class="st-table kiosks-view__registered-table">
          <thead>
            <tr>
              <th>Layar</th>
              <th>Perangkat & laboratorium</th>
              <th>Kamera</th>
              <th>PIN kiosk</th>
              <th>Masa berlaku token</th>
              <th>Status</th>
              <th><span class="st-table__actions">Aksi</span></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="k in kiosks" :key="k.id" data-testid="kiosk-row">
              <td>
                <strong>{{ k.display_name }}</strong>
              </td>
              <td>
                <div class="kiosks-view__lab-cell">
                  <strong>{{ kioskDeviceName(k) }}</strong>
                  <small>
                    {{ kioskLaboratory(k)?.code ?? 'Laboratorium' }} ·
                    {{ kioskLaboratory(k)?.name ?? 'tidak tersedia' }}
                  </small>
                </div>
              </td>
              <td>{{ k.camera_label ?? '-' }}</td>
              <td>
                <UiBadge :tone="k.has_pin ? 'present' : 'neutral'">{{
                  k.has_pin ? 'Terpasang' : 'Belum'
                }}</UiBadge>
              </td>
              <td>
                {{ k.token_ttl_hours == null ? 'Default server' : `${k.token_ttl_hours} jam` }}
              </td>
              <td>
                <UiBadge :tone="k.is_active ? 'present' : 'neutral'">{{
                  k.is_active ? 'Aktif' : 'Nonaktif'
                }}</UiBadge>
              </td>
              <td v-if="isAdmin" class="st-table__actions">
                <button
                  class="st-rowbtn"
                  type="button"
                  :data-testid="`edit-kiosk-${k.id}`"
                  @click="openKioskEdit(k)"
                >
                  Ubah
                </button>
                <button
                  class="st-rowbtn"
                  type="button"
                  :data-testid="`kiosk-pin-action-${k.id}`"
                  @click="makePin(k)"
                >
                  {{ k.has_pin ? 'Reset PIN' : 'Buat PIN' }}
                </button>
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

    <UiModal
      v-if="isRegisterDialogOpen"
      title="Daftarkan layar kiosk"
      data-testid="kiosk-registration-dialog"
      @close="closeRegistrationDialog"
    >
      <p class="st-table__muted kiosks-view__section-note">
        Pilih perangkat dan beri nama layar. Laboratorium mengikuti perangkat yang dipilih.
      </p>
      <form id="kiosk-registration-form" class="kiosks-view__form" @submit.prevent="submit">
        <label class="st-field">
          <span>Perangkat</span>
          <UiSelect v-model="form.device_id" data-testid="kiosk-device" required>
            <option v-for="device in devices" :key="device.device_id" :value="device.device_id">
              {{ device.name }} · {{ device.laboratory_name }}
            </option>
          </UiSelect>
        </label>
        <div class="st-field">
          <span>Laboratorium perangkat</span>
          <div class="kiosks-view__readonly-value" data-testid="selected-kiosk-lab">
            {{ selectedDevice?.laboratory_name ?? 'Pilih perangkat terlebih dahulu' }}
          </div>
        </div>
        <label class="st-field">
          <span>Nama layar</span>
          <UiInput v-model="form.display_name" data-testid="kiosk-name" maxlength="120" required />
        </label>
        <label class="st-field">
          <span>Label kamera <small>Opsional</small></span>
          <UiInput v-model="form.camera_label" data-testid="kiosk-camera" maxlength="120" />
        </label>
        <label class="st-field">
          <span>Masa berlaku token</span>
          <UiSelect v-model="form.token_ttl_hours" data-testid="kiosk-ttl">
            <option value="">Ikuti default server</option>
            <option value="1">1 jam</option>
            <option value="2">2 jam</option>
            <option value="4">4 jam</option>
            <option value="8">8 jam</option>
            <option value="12">12 jam</option>
          </UiSelect>
        </label>
        <p class="st-table__muted kiosks-view__ttl-help">
          TTL menentukan lama satu token akses berlaku. Layar mencoba memperbaruinya otomatis
          sebelum habis. Jika pembaruan gagal atau akses dicabut, PIN perlu dimasukkan lagi.
        </p>
        <p v-if="registrationError" class="st-alert st-alert--error" role="alert">
          {{ registrationError }}
        </p>
      </form>
      <template #footer>
        <UiButton
          variant="secondary"
          type="button"
          :disabled="isCreatingKiosk"
          @click="closeRegistrationDialog"
        >
          Batal
        </UiButton>
        <UiButton
          variant="primary"
          type="submit"
          form="kiosk-registration-form"
          data-testid="kiosk-create"
          :disabled="isCreatingKiosk || !devices.length"
        >
          {{ isCreatingKiosk ? 'Mendaftarkan…' : 'Daftarkan layar' }}
        </UiButton>
      </template>
    </UiModal>

    <UiModal
      v-if="editingKiosk"
      title="Edit layar kiosk"
      data-testid="kiosk-edit-dialog"
      @close="closeKioskEdit"
    >
      <p class="st-table__muted kiosks-view__section-note">
        {{ kioskDeviceName(editingKiosk) }} ·
        {{ kioskLaboratory(editingKiosk)?.name ?? 'Laboratorium' }}
      </p>
      <form id="kiosk-edit-form" class="kiosks-view__form" @submit.prevent="saveKioskEdit">
        <label class="st-field">
          <span>Nama layar</span>
          <UiInput v-model="kioskEditForm.display_name" maxlength="120" required />
        </label>
        <label class="st-field">
          <span>Label kamera</span>
          <UiInput v-model="kioskEditForm.camera_label" maxlength="120" />
        </label>
        <label class="st-field">
          <span>Masa berlaku token</span>
          <UiSelect v-model="kioskEditForm.token_ttl_hours" data-testid="edit-kiosk-ttl">
            <option value="">Ikuti default server</option>
            <option value="1">1 jam</option>
            <option value="2">2 jam</option>
            <option value="4">4 jam</option>
            <option value="8">8 jam</option>
            <option value="12">12 jam</option>
          </UiSelect>
        </label>
        <p class="st-table__muted kiosks-view__ttl-help">
          Lama satu token akses kiosk berlaku. Sistem mencoba memperbaruinya otomatis sebelum habis.
        </p>
        <p v-if="kioskEditError" class="st-alert st-alert--error" role="alert">
          {{ kioskEditError }}
        </p>
      </form>
      <template #footer>
        <UiButton variant="secondary" type="button" @click="closeKioskEdit">Batal</UiButton>
        <UiButton
          variant="primary"
          type="submit"
          form="kiosk-edit-form"
          data-testid="save-kiosk-edit"
        >
          Simpan perubahan
        </UiButton>
      </template>
    </UiModal>

    <UiModal
      v-if="editingDisplayPinLab"
      :title="`${editingDisplayPinLab.has_display_pin ? 'Ubah' : 'Atur'} PIN publik · ${editingDisplayPinLab.code}`"
      data-testid="laboratory-display-pin-dialog"
      @close="cancelDisplayPinEdit"
    >
      <p class="st-table__muted">PIN lama tidak ditampilkan. Masukkan 4–32 angka.</p>
      <form
        id="laboratory-display-pin-form"
        class="kiosks-view__pin-form"
        @submit.prevent="saveDisplayPin(editingDisplayPinLab.id)"
      >
        <label for="laboratory-display-pin-input">PIN baru</label>
        <UiInput
          id="laboratory-display-pin-input"
          :model-value="displayPinDrafts[editingDisplayPinLab.id] ?? ''"
          type="password"
          inputmode="numeric"
          pattern="[0-9]{4,32}"
          minlength="4"
          maxlength="32"
          autocomplete="off"
          :invalid="Boolean(displayPinError)"
          required
          data-testid="laboratory-display-pin-input"
          @update:model-value="setDisplayPinDraft(editingDisplayPinLab.id, $event)"
        />
        <p v-if="displayPinError" class="st-alert st-alert--error" role="alert">
          {{ displayPinError }}
        </p>
      </form>
      <template #footer>
        <UiButton
          variant="secondary"
          type="button"
          :disabled="isSavingDisplayPin"
          @click="cancelDisplayPinEdit"
        >
          Batal
        </UiButton>
        <UiButton
          variant="primary"
          type="button"
          :disabled="isSavingDisplayPin"
          form="laboratory-display-pin-form"
          data-testid="save-laboratory-display-pin"
          @click="saveDisplayPin(editingDisplayPinLab.id)"
        >
          {{ isSavingDisplayPin ? 'Menyimpan…' : 'Simpan PIN' }}
        </UiButton>
      </template>
    </UiModal>

    <UiModal
      v-if="deletingDisplayPinLab"
      :title="`Hapus PIN publik · ${deletingDisplayPinLab.name}`"
      data-testid="delete-public-pin-dialog"
      @close="closeDeleteDisplayPin"
    >
      <p>
        Pengguna tidak dapat membuka sesi laboratorium di <strong>/display</strong> sampai PIN baru
        diatur. Sesi layar publik yang sedang aktif juga akan dicabut.
      </p>
      <p v-if="displayPinError" class="st-alert st-alert--error" role="alert">
        {{ displayPinError }}
      </p>
      <template #footer>
        <UiButton
          variant="secondary"
          type="button"
          :disabled="isDeletingDisplayPin"
          @click="closeDeleteDisplayPin"
        >
          Batal
        </UiButton>
        <UiButton
          variant="danger"
          type="button"
          :disabled="isDeletingDisplayPin"
          data-testid="confirm-delete-public-pin"
          @click="deleteDisplayPin(deletingDisplayPinLab.id)"
        >
          {{ isDeletingDisplayPin ? 'Menghapus…' : 'Hapus PIN' }}
        </UiButton>
      </template>
    </UiModal>
  </div>
</template>

<style scoped>
.kiosks-view__form {
  display: grid;
  gap: 16px;
}

.kiosks-view__section-note {
  margin-top: 0;
  margin-bottom: 16px;
}

.kiosks-view__readonly-value {
  min-height: 44px;
  display: flex;
  align-items: center;
  padding: 0 12px;
  border: 1px solid var(--border-color-light);
  border-radius: var(--radius-sm);
  color: var(--text);
  background: var(--bg-surface-secondary);
}

.kiosks-view__ttl-help {
  margin: -8px 0 0;
}

.kiosks-view__lab-cell {
  display: grid;
  gap: 4px;
}

.kiosks-view__lab-cell small {
  color: var(--text-muted);
  font-size: 0.78rem;
}

.kiosks-view__registered-table {
  min-width: 900px;
}

.kiosks-view__registered-table .st-table__actions {
  white-space: nowrap;
}

.kiosks-view__pin-form {
  display: grid;
  gap: 16px;
}
</style>
