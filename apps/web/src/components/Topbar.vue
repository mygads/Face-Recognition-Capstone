<script setup lang="ts">
defineOptions({ name: 'AppTopbar' })

defineProps<{
  theme: 'light' | 'dark'
  sidebarExpanded: boolean
}>()

defineEmits<{
  toggleSidebar: []
  toggleTheme: []
}>()
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
        <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <path d="M4 7h16M4 12h16M4 17h16" />
        </svg>
      </button>
      <span class="app-topbar__context">Portal sekolah <span>/</span> Praktikum</span>
    </div>

    <div class="app-topbar__right">
      <span class="app-topbar__environment">Internal</span>
      <RouterLink class="app-topbar__profile-link" to="/app/profile">Profil</RouterLink>
      <button
        class="app-topbar__theme-button"
        type="button"
        data-testid="theme-toggle"
        :aria-label="theme === 'light' ? 'Aktifkan tema gelap' : 'Aktifkan tema terang'"
        @click="$emit('toggleTheme')"
      >
        <svg v-if="theme === 'light'" viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <circle cx="12" cy="12" r="3.75" />
          <path
            d="M12 2.75v2M12 19.25v2M21.25 12h-2M4.75 12h-2m15.79-6.54-1.42 1.42M6.88 17.12l-1.42 1.42m13.08 0-1.42-1.42M6.88 6.88 5.46 5.46"
          />
        </svg>
        <svg v-else viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <path d="M20.2 15.1A8.5 8.5 0 0 1 8.9 3.8 8.5 8.5 0 1 0 20.2 15.1Z" />
        </svg>
        <span>{{ theme === 'light' ? 'Gelap' : 'Terang' }}</span>
      </button>
    </div>
  </header>
</template>
