<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import PageHeader from './PageHeader.vue'
import Sidebar from './Sidebar.vue'
import Topbar from './Topbar.vue'

type Theme = 'light' | 'dark'

const themeStorageKey = 'presensi.theme'
const route = useRoute()
const sidebarCollapsed = ref(false)
const mobileDrawerOpen = ref(false)
const mobileViewportQuery = window.matchMedia?.('(max-width: 900px)')
const isMobileViewport = ref(mobileViewportQuery?.matches ?? window.innerWidth <= 900)

function syncViewport(query?: MediaQueryListEvent) {
  isMobileViewport.value =
    query?.matches ?? mobileViewportQuery?.matches ?? window.innerWidth <= 900
  if (!isMobileViewport.value) mobileDrawerOpen.value = false
}

onMounted(() => mobileViewportQuery?.addEventListener('change', syncViewport))
onBeforeUnmount(() => mobileViewportQuery?.removeEventListener('change', syncViewport))

function getInitialTheme(): Theme {
  try {
    const savedTheme = localStorage.getItem(themeStorageKey)
    if (savedTheme === 'light' || savedTheme === 'dark') return savedTheme
  } catch {
    // Storage may be unavailable in private browsing contexts.
  }

  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

const theme = ref<Theme>(getInitialTheme())

watch(
  theme,
  (currentTheme) => {
    document.documentElement.dataset.theme = currentTheme
    try {
      localStorage.setItem(themeStorageKey, currentTheme)
    } catch {
      // Keep the current theme for this page even when storage is unavailable.
    }
  },
  { immediate: true },
)

const pageTitle = computed(() => String(route.meta.title ?? 'Ringkasan'))
const pageDescription = computed(() =>
  String(route.meta.description ?? 'Ruang kerja presensi praktikum.'),
)
const sidebarExpanded = computed(() => {
  return isMobileViewport.value ? mobileDrawerOpen.value : !sidebarCollapsed.value
})

function toggleSidebar() {
  if (isMobileViewport.value) {
    mobileDrawerOpen.value = !mobileDrawerOpen.value
    return
  }

  sidebarCollapsed.value = !sidebarCollapsed.value
}

function closeMobileDrawer() {
  mobileDrawerOpen.value = false
}

function toggleTheme() {
  theme.value = theme.value === 'light' ? 'dark' : 'light'
}
</script>

<template>
  <div
    class="app-shell"
    :class="{
      'app-shell--sidebar-collapsed': sidebarCollapsed,
      'app-shell--drawer-open': mobileDrawerOpen,
    }"
    data-testid="app-shell"
  >
    <Sidebar
      :collapsed="sidebarCollapsed"
      :mobile-open="mobileDrawerOpen"
      @navigate="closeMobileDrawer"
    />

    <button
      v-if="mobileDrawerOpen"
      class="app-shell__backdrop"
      type="button"
      aria-label="Tutup navigasi"
      @click="closeMobileDrawer"
    />

    <div class="app-shell__workspace">
      <Topbar
        :theme="theme"
        :sidebar-expanded="sidebarExpanded"
        @toggle-sidebar="toggleSidebar"
        @toggle-theme="toggleTheme"
      />

      <main id="main-content" class="app-shell__main" tabindex="-1">
        <PageHeader
          v-if="!route.meta.pageHeaderInView"
          eyebrow="Presensi praktikum"
          :title="pageTitle"
          :description="pageDescription"
        />
        <RouterView />
      </main>

      <footer class="app-shell__footer">
        <span>Sistem presensi praktikum</span>
        <span>Area internal sekolah</span>
      </footer>
    </div>
  </div>
</template>
