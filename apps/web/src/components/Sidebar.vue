<script setup lang="ts">
defineOptions({ name: 'AppSidebar' })

defineProps<{
  collapsed: boolean
  mobileOpen: boolean
}>()

const emit = defineEmits<{
  navigate: []
}>()
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
    </nav>

    <div class="app-sidebar__footer">
      <span class="app-sidebar__footer-mark" aria-hidden="true">S</span>
      <span class="app-sidebar__footer-copy">Sistem internal sekolah</span>
    </div>
  </aside>
</template>
