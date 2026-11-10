<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import PasswordChangeForm from '../components/PasswordChangeForm.vue'
import { useAuthStore } from '../stores/auth'
import { permissionLabel } from '../utils/permissions'
import UiButton from '../components/ui/UiButton.vue'
import UiCard from '../components/ui/UiCard.vue'
import UiPageHeader from '../components/ui/UiPageHeader.vue'
import {
  ApiError,
  getOpeningPreference,
  listMyClasses,
  saveOpeningPreference,
  type SchoolClass,
} from '../api/client'

const auth = useAuthStore()
const router = useRouter()
const isTeacher = computed(() => auth.account?.roles.includes('TEACHER') ?? false)
const openingMode = ref<'manual' | 'automatic'>('manual')
const prefMessage = ref<string | null>(null)
const prefError = ref<string | null>(null)
const assignedClasses = ref<SchoolClass[]>([])

function formatError(err: unknown): string {
  if (err instanceof ApiError) return err.message
  return 'Preferensi belum dapat dimuat.'
}

async function load(): Promise<void> {
  if (!isTeacher.value) return
  try {
    const pref = await getOpeningPreference()
    openingMode.value = pref.opening_mode
    const page = await listMyClasses({ limit: 100, offset: 0 })
    assignedClasses.value = page.items
  } catch (err) {
    prefError.value = formatError(err)
  }
}

async function save(): Promise<void> {
  prefError.value = null
  try {
    await saveOpeningPreference({ opening_mode: openingMode.value })
    prefMessage.value = 'Preferensi tersimpan. Berlaku untuk sesi berikutnya.'
  } catch (err) {
    prefError.value = formatError(err)
  }
}

async function finishPasswordChange(): Promise<void> {
  await auth.logout()
  await router.replace({ name: 'login', query: { passwordChanged: '1' } })
}

onMounted(() => void load())
</script>

<template>
  <div class="st-page" aria-label="Profil akun">
    <UiPageHeader
      eyebrow="Akun"
      title="Profil akun"
      description="Informasi akun, penugasan, dan preferensi sesi."
    />
    <UiCard title="Informasi akun" :subtitle="auth.account?.full_name ?? 'Akun'">
      <dl class="st-def">
        <div>
          <dt>Email</dt>
          <dd>{{ auth.account?.email }}</dd>
        </div>
        <div>
          <dt>Role</dt>
          <dd>{{ auth.account?.roles.join(', ') }}</dd>
        </div>
        <div>
          <dt>Izin efektif</dt>
          <dd>
            <ul class="st-chips">
              <li v-for="perm in auth.account?.permissions ?? []" :key="perm" class="st-chip">
                {{ permissionLabel(perm) }}
              </li>
            </ul>
            <span v-if="!(auth.account?.permissions ?? []).length">-</span>
          </dd>
        </div>
      </dl>
    </UiCard>

    <UiCard v-if="isTeacher" title="Cara sesi saya dibuka" subtitle="Preferensi pembukaan sesi">
      <form @submit.prevent="save">
        <div class="st-radio-cards">
          <label
            class="st-radio-card"
            :class="{ 'st-radio-card--active': openingMode === 'manual' }"
          >
            <input v-model="openingMode" type="radio" value="manual" data-testid="opening-manual" />
            Saya membuka sesi sendiri
          </label>
          <label
            class="st-radio-card"
            :class="{ 'st-radio-card--active': openingMode === 'automatic' }"
          >
            <input
              v-model="openingMode"
              type="radio"
              value="automatic"
              data-testid="opening-automatic"
            />
            Sesi saya dibuka otomatis sesuai jadwal
          </label>
        </div>
        <p v-if="prefMessage" class="st-alert st-alert--success" role="status">{{ prefMessage }}</p>
        <p v-if="prefError" class="st-alert st-alert--error" role="alert">{{ prefError }}</p>
        <div style="margin-top: 12px">
          <UiButton type="submit" variant="primary" data-testid="opening-save">
            Simpan preferensi
          </UiButton>
        </div>
      </form>
      <div v-if="assignedClasses.length" data-testid="profile-classes">
        <h3 class="st-section">Kelas yang ditugaskan</h3>
        <ul class="st-list">
          <li v-for="c in assignedClasses" :key="c.id" class="st-list__item">
            <span
              ><strong>{{ c.name }}</strong
              ><br /><span class="st-table__muted">{{ c.code }}</span></span
            >
          </li>
        </ul>
      </div>
    </UiCard>

    <UiCard
      title="Ubah kata sandi"
      subtitle="Gunakan kata sandi unik yang tidak dipakai pada layanan lain."
    >
      <PasswordChangeForm @saved="finishPasswordChange" />
    </UiCard>
  </div>
</template>
