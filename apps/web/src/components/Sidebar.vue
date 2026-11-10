<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'
import { useAuthStore } from '../stores/auth'

defineOptions({ name: 'AppSidebar' })

defineProps<{
  collapsed: boolean
  mobileOpen: boolean
}>()

const emit = defineEmits<{
  navigate: []
}>()

interface MenuChild {
  label: string
  to: string
  testid?: string
  activeWhen?: string[]
}

interface MenuEntry {
  label: string
  icon: string
  to?: string
  testid?: string
  children?: MenuChild[]
  activeWhen?: string[]
  groupKey?: string
}

interface MenuGroup {
  heading: string
  entries: MenuEntry[]
}

const auth = useAuthStore()
const route = useRoute()

const expandedGroups = ref<Record<string, boolean>>({
  'data-master': true,
  'perangkat-ai': true,
  pengaturan: true,
})

function hasPerm(...perms: string[]): boolean {
  const roles = auth.account?.roles ?? []
  if (roles.includes('ADMIN')) return true
  const permsSet = (auth.account?.permissions ?? []) as string[]
  return perms.some((perm) => permsSet.includes(perm))
}

const isAdmin = computed(() => (auth.account?.roles ?? []).includes('ADMIN'))
const isTeacher = computed(() => !isAdmin.value && (auth.account?.roles ?? []).includes('TEACHER'))
const menuGroups = computed<MenuGroup[]>(() => {
  if (isAdmin.value) {
    return [
      {
        heading: 'Ruang kerja',
        entries: [
          {
            label: 'Dashboard Admin',
            icon: 'dashboard',
            to: '/app/dashboard',
            testid: 'dashboard-link',
          },
        ],
      },
      {
        heading: 'Akademik',
        entries: [
          {
            label: 'Data Master',
            icon: 'database',
            groupKey: 'data-master',
            activeWhen: ['/app/master-data'],
            children: [
              { label: 'Siswa', to: '/app/master-data/students' },
              { label: 'Kelas', to: '/app/master-data/classes' },
              { label: 'Laboratorium', to: '/app/master-data/laboratories' },
            ],
          },
          {
            label: 'Jadwal Praktikum',
            icon: 'calendar_month',
            to: '/app/schedules',
            testid: 'schedules-link',
          },
        ],
      },
      {
        heading: 'Presensi',
        entries: [
          {
            label: 'Sesi Presensi',
            icon: 'schedule',
            to: '/app/sessions',
            testid: 'sessions-link',
          },
          {
            label: 'Pendaftaran Wajah',
            icon: 'face',
            to: '/app/enrollment',
            testid: 'enrollment-link',
          },
          {
            label: 'Koreksi Kehadiran',
            icon: 'edit_note',
            to: '/app/corrections',
            testid: 'corrections-link',
          },
        ],
      },
      {
        heading: 'Pemantauan',
        entries: [
          {
            label: 'Laporan Kehadiran',
            icon: 'bar_chart',
            to: '/app/reports',
            testid: 'reports-link',
          },
          {
            label: 'Peringatan Dini',
            icon: 'warning',
            to: '/app/ews',
            testid: 'ews-link',
          },
        ],
      },
      {
        heading: 'Infrastruktur',
        entries: [
          {
            label: 'Perangkat & AI',
            icon: 'devices',
            groupKey: 'perangkat-ai',
            activeWhen: ['/app/devices', '/app/camera-preview', '/app/kiosks', '/app/ai-setup'],
            children: [
              { label: 'Perangkat', to: '/app/devices', testid: 'devices-link' },
              { label: 'Preview Kamera', to: '/app/camera-preview', testid: 'camera-preview-link' },
              { label: 'Layar Presensi', to: '/app/kiosks', testid: 'kiosks-link' },
              { label: 'Konfigurasi AI', to: '/app/ai-setup', testid: 'ai-setup-link' },
            ],
          },
        ],
      },
      {
        heading: 'Administrasi',
        entries: [
          {
            label: 'Pengaturan',
            icon: 'settings',
            groupKey: 'pengaturan',
            activeWhen: ['/app/accounts', '/app/attendance-policy', '/app/audit'],
            children: [
              { label: 'Akun Staf', to: '/app/accounts', testid: 'accounts-link' },
              {
                label: 'Kebijakan Presensi',
                to: '/app/attendance-policy',
                testid: 'attendance-policy-link',
              },
              { label: 'Audit Aktivitas', to: '/app/audit', testid: 'audit-link' },
            ],
          },
        ],
      },
    ]
  }
  if (isTeacher.value) {
    return [
      {
        heading: 'Ruang kerja',
        entries: [
          {
            label: 'Dashboard Guru',
            icon: 'dashboard',
            to: '/app/dashboard',
            testid: 'dashboard-link',
          },
        ],
      },
      {
        heading: 'Akademik',
        entries: [
          {
            label: 'Kelas Saya',
            icon: 'groups',
            to: '/app/my-classes',
            testid: 'my-classes-link',
          },
          {
            label: 'Jadwal Saya',
            icon: 'calendar_month',
            to: '/app/schedules',
            testid: 'schedules-link',
          },
        ],
      },
      {
        heading: 'Presensi',
        entries: [
          {
            label: 'Sesi Presensi',
            icon: 'schedule',
            to: '/app/sessions',
            testid: 'sessions-link',
          },
          {
            label: 'Koreksi Saya',
            icon: 'edit_note',
            to: '/app/corrections',
            testid: 'corrections-link',
          },
        ],
      },
      {
        heading: 'Pemantauan',
        entries: [
          {
            label: 'Laporan Kehadiran',
            icon: 'bar_chart',
            to: '/app/reports',
            testid: 'reports-link',
          },
          {
            label: 'Peringatan Dini',
            icon: 'warning',
            to: '/app/ews',
            testid: 'ews-link',
          },
        ],
      },
    ]
  }
  const groups: MenuGroup[] = [
    {
      heading: 'Ruang kerja',
      entries: [
        {
          label: 'Dashboard Laboran',
          icon: 'dashboard',
          to: '/app/dashboard',
          testid: 'dashboard-link',
        },
      ],
    },
  ]
  const presensi: MenuEntry[] = []
  if (hasPerm('session_view', 'session_operate')) {
    presensi.push({
      label: 'Sesi Presensi',
      icon: 'schedule',
      to: '/app/sessions',
      testid: 'sessions-link',
    })
  }
  if (hasPerm('enrollment_manage')) {
    presensi.push({
      label: 'Pendaftaran Wajah',
      icon: 'face',
      to: '/app/enrollment',
      testid: 'enrollment-link',
    })
  }
  if (hasPerm('attendance_correct')) {
    presensi.push({
      label: 'Koreksi Saya',
      icon: 'edit_note',
      to: '/app/corrections',
      testid: 'corrections-link',
    })
  }
  if (presensi.length) groups.push({ heading: 'Presensi', entries: presensi })
  const pemantauan: MenuEntry[] = []
  if (hasPerm('reports_read', 'reports_export')) {
    pemantauan.push({
      label: 'Laporan Kehadiran',
      icon: 'bar_chart',
      to: '/app/reports',
      testid: 'reports-link',
    })
  }
  if (hasPerm('ews_read', 'ews_follow_up')) {
    pemantauan.push({
      label: 'Peringatan Dini',
      icon: 'warning',
      to: '/app/ews',
      testid: 'ews-link',
    })
  }
  if (pemantauan.length) groups.push({ heading: 'Pemantauan', entries: pemantauan })
  const infra: MenuEntry[] = []
  if (hasPerm('schedule_read', 'schedule_manage')) {
    infra.push({
      label: 'Jadwal Laboratorium',
      icon: 'calendar_month',
      to: '/app/schedules',
      testid: 'schedules-link',
    })
  }
  if (hasPerm('device_operate')) {
    infra.push({
      label: 'Perangkat',
      icon: 'devices',
      to: '/app/devices',
      testid: 'devices-link',
    })
    infra.push({
      label: 'Preview Kamera',
      icon: 'videocam',
      to: '/app/camera-preview',
      testid: 'camera-preview-link',
    })
  }
  if (infra.length) {
    const akademikIdx = groups.findIndex((g) => g.heading === 'Presensi')
    void akademikIdx
    groups.push({ heading: 'Infrastruktur', entries: infra })
  }
  return groups
})

function isEntryActive(entry: Pick<MenuEntry, 'to' | 'activeWhen' | 'children'>): boolean {
  const path = route.path
  if (entry.to && (path === entry.to || path.startsWith(entry.to + '/'))) return true
  if (entry.activeWhen?.some((prefix) => path.startsWith(prefix))) return true
  if (entry.children?.some((child) => path === child.to || path.startsWith(child.to + '/')))
    return true
  return false
}

function toggleGroup(key: string): void {
  expandedGroups.value[key] = !expandedGroups.value[key]
}
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
      <span class="app-sidebar__brand-lockup">
        <img
          class="app-sidebar__brand-logo"
          src="/logo-sekolah.png"
          alt="Logo SMA Cimahi"
          width="52"
          height="52"
        />
        <span class="app-sidebar__brand-name">
          Presensi Praktikum
          <small>SMA Taruna Nusantara Kampus Cimahi</small>
        </span>
      </span>
    </RouterLink>

    <nav class="app-sidebar__nav" aria-label="Navigasi utama">
      <template v-for="group in menuGroups" :key="group.heading">
        <p class="app-sidebar__section-label">{{ group.heading }}</p>
        <template v-for="entry in group.entries" :key="entry.label">
          <RouterLink
            v-if="entry.to"
            class="app-sidebar__link"
            :class="{ 'app-sidebar__link--active': isEntryActive(entry) }"
            :to="entry.to"
            :data-testid="entry.testid"
            @click="emit('navigate')"
          >
            <span class="st-material-icon" aria-hidden="true">{{ entry.icon }}</span>
            <span class="app-sidebar__link-label">{{ entry.label }}</span>
          </RouterLink>
          <div v-else class="app-sidebar__group">
            <button
              class="app-sidebar__link app-sidebar__group-toggle"
              :class="{ 'app-sidebar__link--active': isEntryActive(entry) }"
              type="button"
              :aria-expanded="entry.groupKey ? expandedGroups[entry.groupKey] : true"
              @click="entry.groupKey && toggleGroup(entry.groupKey)"
            >
              <span class="st-material-icon" aria-hidden="true">{{ entry.icon }}</span>
              <span class="app-sidebar__link-label">{{ entry.label }}</span>
              <span class="st-material-icon app-sidebar__group-caret" aria-hidden="true"
                >expand_more</span
              >
            </button>
            <div
              v-if="!entry.groupKey || expandedGroups[entry.groupKey]"
              class="app-sidebar__group-children"
            >
              <RouterLink
                v-for="child in entry.children"
                :key="child.label"
                class="app-sidebar__link app-sidebar__link--child"
                :class="{ 'app-sidebar__link--active': isEntryActive(child) }"
                :to="child.to"
                :data-testid="child.testid"
                @click="emit('navigate')"
              >
                <span class="app-sidebar__link-label">{{ child.label }}</span>
              </RouterLink>
            </div>
          </div>
        </template>
      </template>
    </nav>
  </aside>
</template>
