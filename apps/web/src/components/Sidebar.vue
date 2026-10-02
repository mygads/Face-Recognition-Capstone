<script setup lang="ts">
import { computed } from 'vue'
import { useAuthStore } from '../stores/auth'

defineOptions({ name: 'AppSidebar' })

defineProps<{
  collapsed: boolean
  mobileOpen: boolean
}>()

const emit = defineEmits<{
  navigate: []
}>()
const auth = useAuthStore()
const canManageSchedules = computed(
  () => auth.account?.roles.some((role) => role === 'ADMIN' || role === 'TEACHER') ?? false,
)
const canOperateSessions = computed(
  () =>
    auth.account?.roles.some((role) => ['ADMIN', 'TEACHER', 'LABORANT'].includes(role)) ?? false,
)
const canManageEnrollment = computed(
  () => auth.account?.roles.some((role) => role === 'ADMIN' || role === 'LABORANT') ?? false,
)
const canViewDevices = computed(
  () => auth.account?.roles.some((role) => role === 'ADMIN' || role === 'LABORANT') ?? false,
)
const canViewReports = computed(
  () => auth.account?.roles.some((role) => role === 'ADMIN' || role === 'TEACHER') ?? false,
)
const canManageMasterData = computed(() => auth.account?.roles.includes('ADMIN') ?? false)
const canManageAccounts = computed(() => auth.account?.roles.includes('ADMIN') ?? false)
const canManageSettings = computed(() => auth.account?.roles.includes('ADMIN') ?? false)
</script>

<template>
  <aside
    id="app-sidebar"
    class="app-sidebar"
    :class="{ 'app-sidebar--collapsed': collapsed, 'app-sidebar--open': mobileOpen }"
  >
    <RouterLink
      class="app-sidebar__brand"
      to="/app/dashboard"
      :aria-label="collapsed ? 'Presensi Praktikum' : undefined"
      @click="emit('navigate')"
    >
      <span class="app-sidebar__brand-mark" aria-hidden="true">P</span>
      <span class="app-sidebar__brand-name">
        Presensi
        <small>Praktikum</small>
      </span>
    </RouterLink>

    <nav class="app-sidebar__nav" aria-label="Navigasi utama">
      <p class="app-sidebar__section-label">Ruang kerja</p>
      <RouterLink
        class="app-sidebar__link"
        active-class="app-sidebar__link--active"
        to="/app/dashboard"
        :aria-label="collapsed ? 'Ringkasan' : undefined"
        data-testid="dashboard-link"
        @click="emit('navigate')"
      >
        <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <rect x="3.5" y="3.5" width="7" height="7" rx="1.5" />
          <rect x="13.5" y="3.5" width="7" height="7" rx="1.5" />
          <rect x="3.5" y="13.5" width="7" height="7" rx="1.5" />
          <rect x="13.5" y="13.5" width="7" height="7" rx="1.5" />
        </svg>
        <span class="app-sidebar__link-label">Ringkasan</span>
      </RouterLink>
      <RouterLink
        v-if="canManageMasterData"
        class="app-sidebar__link"
        active-class="app-sidebar__link--active"
        to="/app/master-data"
        :aria-label="collapsed ? 'Data master' : undefined"
        data-testid="master-data-link"
        @click="emit('navigate')"
      >
        <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <path d="M4 5.5h16v4H4zM4 14.5h7v4H4zM15 14.5h5v4h-5z" />
          <path d="M8 9.5v5M17.5 9.5v5" />
        </svg>
        <span class="app-sidebar__link-label">Data master</span>
      </RouterLink>
      <RouterLink
        v-if="canManageAccounts"
        class="app-sidebar__link"
        active-class="app-sidebar__link--active"
        to="/app/accounts"
        :aria-label="collapsed ? 'Kelola akun staf' : undefined"
        data-testid="accounts-link"
        @click="emit('navigate')"
      >
        <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <circle cx="9" cy="8" r="3" />
          <path d="M3.5 19c.5-3.2 2.3-5 5.5-5s5 1.8 5.5 5M17 8v6M14 11h6" />
        </svg>
        <span class="app-sidebar__link-label">Kelola akun staf</span>
      </RouterLink>
      <RouterLink
        v-if="canManageSettings"
        class="app-sidebar__link"
        active-class="app-sidebar__link--active"
        to="/app/ai-setup"
        :aria-label="collapsed ? 'AI dan kamera' : undefined"
        data-testid="ai-setup-link"
        @click="emit('navigate')"
      >
        <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <path d="M9 3.5h6M10 3.5v5l-5.5 9.3A2 2 0 0 0 6.2 21h11.6a2 2 0 0 0 1.7-3.2L14 8.5v-5" />
          <path d="M7.5 15h9" />
        </svg>
        <span class="app-sidebar__link-label">AI & kamera</span>
      </RouterLink>
      <RouterLink
        v-if="canManageSchedules"
        class="app-sidebar__link"
        active-class="app-sidebar__link--active"
        to="/app/schedules"
        :aria-label="collapsed ? 'Jadwal praktikum' : undefined"
        data-testid="schedules-link"
        @click="emit('navigate')"
      >
        <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <rect x="3.5" y="5" width="17" height="15.5" rx="2" />
          <path d="M7.5 3.5v3M16.5 3.5v3M3.5 9h17M7.5 12.5h3M13.5 12.5h3M7.5 16h3" />
        </svg>
        <span class="app-sidebar__link-label">Jadwal praktikum</span>
      </RouterLink>
      <RouterLink
        v-if="canOperateSessions"
        class="app-sidebar__link"
        active-class="app-sidebar__link--active"
        to="/app/sessions"
        :aria-label="collapsed ? 'Sesi presensi' : undefined"
        data-testid="sessions-link"
        @click="emit('navigate')"
      >
        <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <rect x="3.5" y="4" width="17" height="16" rx="2" />
          <path d="M7.5 8h9M7.5 12h9M7.5 16h5" />
          <circle cx="18" cy="16" r="2.5" />
        </svg>
        <span class="app-sidebar__link-label">Sesi presensi</span>
      </RouterLink>
      <RouterLink
        v-if="canManageEnrollment"
        class="app-sidebar__link"
        active-class="app-sidebar__link--active"
        to="/app/enrollment"
        :aria-label="collapsed ? 'Pendaftaran siswa' : undefined"
        data-testid="enrollment-link"
        @click="emit('navigate')"
      >
        <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <rect x="3" y="4" width="18" height="16" rx="2" />
          <circle cx="9" cy="10" r="2.5" />
          <path d="M5.5 17c.7-2 2-3 3.5-3s2.8 1 3.5 3M15 9h3M15 12h3M15 15h3" />
        </svg>
        <span class="app-sidebar__link-label">Pendaftaran siswa</span>
      </RouterLink>
      <RouterLink
        v-if="canViewDevices"
        class="app-sidebar__link"
        active-class="app-sidebar__link--active"
        to="/app/devices"
        :aria-label="collapsed ? 'Perangkat' : undefined"
        data-testid="devices-link"
        @click="emit('navigate')"
      >
        <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <rect x="3.5" y="5" width="17" height="13" rx="2" />
          <path d="M8 21h8M12 18v3M7.5 9h9M7.5 13h4" />
        </svg>
        <span class="app-sidebar__link-label">Perangkat</span>
      </RouterLink>
      <RouterLink
        v-if="canViewReports"
        class="app-sidebar__link"
        active-class="app-sidebar__link--active"
        to="/app/reports"
        :aria-label="collapsed ? 'Laporan kehadiran' : undefined"
        data-testid="reports-link"
        @click="emit('navigate')"
      >
        <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <path d="M5 20V11M12 20V4M19 20v-7" />
          <path d="M3 20.5h18" />
        </svg>
        <span class="app-sidebar__link-label">Laporan kehadiran</span>
      </RouterLink>
    </nav>

    <div class="app-sidebar__footer">
      <span class="app-sidebar__footer-mark" aria-hidden="true">S</span>
      <span class="app-sidebar__footer-copy">Sistem internal sekolah</span>
    </div>
  </aside>
</template>
