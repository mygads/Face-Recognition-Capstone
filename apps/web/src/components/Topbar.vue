<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { listLaborantAssignments, listMyClasses } from '../api/client'
import { useAuthStore } from '../stores/auth'

defineOptions({ name: 'AppTopbar' })

defineProps<{
  theme: 'light' | 'dark'
  sidebarExpanded: boolean
}>()

defineEmits<{
  toggleSidebar: []
  toggleTheme: []
}>()

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

const displayName = computed(() => auth.account?.full_name ?? 'Staf sekolah')
const firstName = computed(() => displayName.value.split(' ').at(0) ?? 'S')
const roles = computed(() => auth.account?.roles ?? [])
const isAdmin = computed(() => roles.value.includes('ADMIN'))
const isTeacher = computed(() => !isAdmin.value && roles.value.includes('TEACHER'))
const isLaborant = computed(() => !isAdmin.value && roles.value.includes('LABORANT'))

const scopeLabel = ref('')

async function loadScope(): Promise<void> {
  scopeLabel.value = ''
  try {
    if (isAdmin.value) {
      scopeLabel.value = 'Cakupan: Semua Laboratorium'
    } else if (isTeacher.value) {
      const page = await listMyClasses({ limit: 5 })
      const names = (page.items ?? []).map((c) => c.name).filter(Boolean)
      scopeLabel.value = names.length
        ? `Penugasan: ${names.slice(0, 2).join(', ')}`
        : 'Penugasan: -'
    } else if (isLaborant.value && auth.account?.id) {
      const res = await listLaborantAssignments(auth.account.id)
      const labs = (res.items ?? []).map((a) => a.name ?? a.code ?? '').filter(Boolean)
      scopeLabel.value = labs.length ? labs.slice(0, 2).join(', ') : 'Belum ada penugasan'
    }
  } catch {
    scopeLabel.value = ''
  }
}

onMounted(loadScope)
watch(
  () => auth.account?.id,
  () => void loadScope(),
)

const dashboardLabel = computed(() => {
  if (isAdmin.value) return 'Dashboard Admin'
  if (isTeacher.value) return 'Dashboard Guru'
  return 'Dashboard Laboran'
})
const scheduleLabel = computed(() => {
  if (isAdmin.value) return 'Jadwal Praktikum'
  if (isTeacher.value) return 'Jadwal Saya'
  return 'Jadwal Laboratorium'
})
const correctionLabel = computed(() => (isAdmin.value ? 'Koreksi Kehadiran' : 'Koreksi Saya'))
const breadcrumbs = computed<string[]>(() => {
  switch (route.name) {
    case 'dashboard':
      return [dashboardLabel.value]
    case 'profile':
      return [isTeacher.value ? 'Profil & Preferensi' : 'Profil']
    case 'master-data':
      return ['Data Master']
    case 'my-classes':
      return ['Kelas Saya']
    case 'my-class-detail':
      return ['Kelas Saya', 'Detail Kelas']
    case 'accounts':
      return ['Pengaturan', 'Akun Staf']
    case 'ai-setup':
      return ['Perangkat & AI', 'Konfigurasi AI']
    case 'camera-preview':
      return ['Perangkat & AI', 'Preview Kamera']
    case 'devices':
      return ['Perangkat & AI', 'Perangkat']
    case 'kiosks':
      return ['Perangkat & AI', 'Layar Presensi']
    case 'reports':
      return ['Pemantauan', 'Laporan Kehadiran']
    case 'ews':
      return ['Pemantauan', 'Peringatan Dini']
    case 'schedules':
      return [scheduleLabel.value]
    case 'sessions':
      return ['Sesi Presensi']
    case 'session-detail':
      return ['Sesi Presensi', 'Detail Sesi']
    case 'enrollment':
      return ['Pendaftaran Wajah']
    case 'corrections':
      return [correctionLabel.value]
    case 'correction-detail':
      return [correctionLabel.value, 'Detail Koreksi']
    case 'attendance-policy':
      return ['Pengaturan', 'Kebijakan Presensi']
    case 'audit':
      return ['Pengaturan', 'Audit Aktivitas']
    case 'forbidden':
      return ['Akses Tidak Tersedia']
    default:
      return [String((route.meta as { title?: string }).title ?? 'Ruang kerja')]
  }
})
const profileLabel = computed(() => (isTeacher.value ? 'Profil & Preferensi' : 'Profil'))

async function logout(): Promise<void> {
  await auth.logout()
  await router.replace({ name: 'login' })
}
</script>

<template>
  <header class="app-topbar">
    <div class="app-topbar__left">
      <button
        class="app-topbar__icon-button"
        type="button"
        aria-controls="app-sidebar"
        :aria-expanded="sidebarExpanded"
        aria-label="Buka atau ciutkan navigasi"
        @click="$emit('toggleSidebar')"
      >
        <span class="st-material-icon" aria-hidden="true">menu</span>
      </button>
      <nav class="app-topbar__breadcrumb" aria-label="Breadcrumb">
        <RouterLink to="/app/dashboard" class="app-topbar__breadcrumb-home" aria-label="Beranda">
          <span class="st-material-icon" aria-hidden="true">home</span>
        </RouterLink>
        <template v-for="(crumb, index) in breadcrumbs" :key="index">
          <span class="app-topbar__breadcrumb-sep" aria-hidden="true">/</span>
          <span
            class="app-topbar__breadcrumb-item"
            :class="{ 'app-topbar__breadcrumb-item--current': index === breadcrumbs.length - 1 }"
            >{{ crumb }}</span
          >
        </template>
      </nav>
    </div>

    <div class="app-topbar__right">
      <span
        v-if="scopeLabel"
        class="app-topbar__scope"
        data-testid="scope-chip"
        :title="scopeLabel"
      >
        <span class="app-topbar__scope-dot" aria-hidden="true" />
        <span class="app-topbar__scope-text">{{ scopeLabel }}</span>
      </span>
      <RouterLink class="app-topbar__avatar-link" to="/app/profile" aria-label="Profil saya">
        <span class="app-topbar__avatar" aria-hidden="true">{{ firstName.charAt(0) }}</span>
      </RouterLink>
      <RouterLink class="app-topbar__profile-link" to="/app/profile">
        {{ profileLabel }}
      </RouterLink>
      <button
        class="app-topbar__logout"
        type="button"
        aria-label="Keluar dari aplikasi"
        @click="logout"
      >
        <span class="st-material-icon" aria-hidden="true">logout</span>
        <span class="app-topbar__logout-text">Keluar</span>
      </button>
      <button
        class="app-topbar__theme-button"
        type="button"
        data-testid="theme-toggle"
        :aria-label="theme === 'light' ? 'Aktifkan tema gelap' : 'Aktifkan tema terang'"
        :title="theme === 'light' ? 'Aktifkan tema gelap' : 'Aktifkan tema terang'"
        @click="$emit('toggleTheme')"
      >
        <span class="st-material-icon" aria-hidden="true">{{
          theme === 'light' ? 'dark_mode' : 'light_mode'
        }}</span>
      </button>
    </div>
  </header>
</template>
