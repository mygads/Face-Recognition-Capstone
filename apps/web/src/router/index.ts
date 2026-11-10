import {
  createRouter,
  createWebHistory,
  type Router,
  type RouterHistory,
  type RouteRecordRaw,
} from 'vue-router'
import type { Pinia } from 'pinia'
import { useAuthStore } from '../stores/auth'
import AppShell from '../components/AppShell.vue'
import AuthLayout from '../layouts/AuthLayout.vue'
const DashboardView = () => import('../views/DashboardView.vue')
const DevicesView = () => import('../views/DevicesView.vue')
const EnrollmentView = () => import('../views/EnrollmentView.vue')
const ForbiddenView = () => import('../views/ForbiddenView.vue')
const LoginView = () => import('../views/LoginView.vue')
const MasterDataView = () => import('../views/MasterDataView.vue')
const ChangePasswordView = () => import('../views/ChangePasswordView.vue')
const AccountsView = () => import('../views/AccountsView.vue')
const ProfileView = () => import('../views/ProfileView.vue')
const ReportsView = () => import('../views/ReportsView.vue')
const ScheduleView = () => import('../views/ScheduleView.vue')
const SessionsView = () => import('../views/SessionsView.vue')
const AiSetupView = () => import('../views/AiSetupView.vue')
const CameraPreviewView = () => import('../views/CameraPreviewView.vue')
const MyClassesView = () => import('../views/MyClassesView.vue')
const CorrectionsView = () => import('../views/CorrectionsView.vue')
const EwsView = () => import('../views/EwsView.vue')
const KiosksView = () => import('../views/KiosksView.vue')
const AttendancePolicyView = () => import('../views/AttendancePolicyView.vue')
const AuditView = () => import('../views/AuditView.vue')

export const routes: RouteRecordRaw[] = [
  {
    path: '/',
    redirect: '/app/dashboard',
  },
  {
    path: '/auth',
    component: AuthLayout,
    meta: { layout: 'auth' },
    redirect: '/auth/login',
    children: [
      {
        path: 'login',
        name: 'login',
        component: LoginView,
      },
      {
        path: 'change-password',
        name: 'change-password',
        component: ChangePasswordView,
      },
    ],
  },
  {
    path: '/app',
    component: AppShell,
    redirect: '/app/dashboard',
    meta: { layout: 'authenticated', requiresAuth: true },
    children: [
      {
        path: 'dashboard',
        name: 'dashboard',
        component: DashboardView,
        meta: {
          title: 'Ringkasan',
          description: 'Ruang kerja sesuai peran: admin, guru, atau laboran.',
        },
      },
      {
        path: 'profile',
        name: 'profile',
        component: ProfileView,
        meta: {
          title: 'Profil akun',
          description: 'Lihat informasi akun, penugasan, dan preferensi sesi.',
        },
      },
      {
        path: 'master-data',
        name: 'master-data',
        component: MasterDataView,
        meta: {
          title: 'Data master',
          description: 'Kelola data identitas siswa, kelas, dan laboratorium.',
          requiredPermissions: ['manage_master_data'],
        },
      },
      {
        path: 'master-data/students',
        name: 'master-data-students',
        component: MasterDataView,
        meta: {
          title: 'Data master',
          description: 'Kelola data identitas siswa, kelas, dan laboratorium.',
          requiredPermissions: ['manage_master_data'],
        },
      },
      {
        path: 'master-data/classes',
        name: 'master-data-classes',
        component: MasterDataView,
        meta: {
          title: 'Data master',
          description: 'Kelola data identitas siswa, kelas, dan laboratorium.',
          requiredPermissions: ['manage_master_data'],
        },
      },
      {
        path: 'master-data/classes/:id',
        name: 'master-data-class-detail',
        component: MasterDataView,
        meta: {
          title: 'Data master',
          description: 'Detail kelas dan anggota.',
          requiredPermissions: ['manage_master_data'],
        },
      },
      {
        path: 'master-data/laboratories',
        name: 'master-data-laboratories',
        component: MasterDataView,
        meta: {
          title: 'Data master',
          description: 'Kelola data identitas siswa, kelas, dan laboratorium.',
          requiredPermissions: ['manage_master_data'],
        },
      },
      {
        path: 'master-data/laboratories/:id',
        name: 'master-data-laboratory-detail',
        component: MasterDataView,
        meta: {
          title: 'Data master',
          description: 'Detail laboratorium, perangkat, dan kelas yang dilayani.',
          requiredPermissions: ['manage_master_data'],
        },
      },
      {
        path: 'my-classes',
        name: 'my-classes',
        component: MyClassesView,
        meta: {
          title: 'Kelas saya',
          description: 'Daftar kelas yang ditugaskan beserta roster siswa.',
          requiredPermissions: ['roster_read'],
          pageHeaderInView: true,
        },
      },
      {
        path: 'my-classes/:classId',
        name: 'my-class-detail',
        component: MyClassesView,
        meta: {
          title: 'Kelas saya',
          description: 'Detail kelas penugasan dan roster siswa.',
          requiredPermissions: ['roster_read'],
          pageHeaderInView: true,
        },
      },
      {
        path: 'accounts',
        name: 'accounts',
        component: AccountsView,
        meta: {
          title: 'Kelola akun staf',
          description: 'Akun, status, penugasan, izin tambahan, dan reset sandi.',
          requiredRoles: ['ADMIN'],
          pageHeaderInView: true,
        },
      },
      {
        path: 'ai-setup',
        name: 'ai-setup',
        component: AiSetupView,
        meta: {
          title: 'AI & kamera',
          description: 'Periksa kesiapan model AI, threshold, dan kamera perangkat.',
          requiredRoles: ['ADMIN'],
          pageHeaderInView: true,
        },
      },
      {
        path: 'camera-preview',
        name: 'camera-preview',
        component: CameraPreviewView,
        meta: {
          title: 'Preview kamera',
          description: 'Preview teknis staf: pilih lab lalu perangkat.',
          requiredPermissions: ['device_operate'],
          pageHeaderInView: true,
        },
      },
      {
        path: 'devices',
        name: 'devices',
        component: DevicesView,
        meta: {
          title: 'Perangkat',
          description: 'Pantau kondisi perangkat presensi di lab penugasan.',
          requiredPermissions: ['device_operate'],
          pageHeaderInView: true,
        },
      },
      {
        path: 'kiosks',
        name: 'kiosks',
        component: KiosksView,
        meta: {
          title: 'Layar presensi',
          description: 'Daftar kiosk per lab/perangkat, PIN, dan status pairing.',
          requiredPermissions: ['device_operate'],
          pageHeaderInView: true,
        },
      },
      {
        path: 'reports',
        name: 'reports',
        component: ReportsView,
        meta: {
          title: 'Laporan kehadiran',
          description: 'Riwayat kehadiran dan ekspor sesuai cakupan peran.',
          requiredPermissions: ['reports_read'],
        },
      },
      {
        path: 'ews',
        name: 'ews',
        component: EwsView,
        meta: {
          title: 'Peringatan dini',
          description: 'Watchlist ketidakhadiran dan tindak lanjut.',
          requiredPermissions: ['ews_read'],
          pageHeaderInView: true,
        },
      },
      {
        path: 'schedules',
        name: 'schedules',
        component: ScheduleView,
        meta: {
          title: 'Jadwal praktikum',
          description: 'Agenda dan daftar pertemuan sesuai cakupan peran.',
          requiredPermissions: ['schedule_read'],
        },
      },
      {
        path: 'sessions',
        name: 'sessions',
        component: SessionsView,
        meta: {
          title: 'Sesi presensi',
          description: 'Operasional pertemuan: buka, pantau, tutup.',
          requiredPermissions: ['session_view'],
        },
      },
      {
        path: 'sessions/:sessionId',
        name: 'session-detail',
        component: SessionsView,
        meta: {
          title: 'Detail sesi',
          description: 'Ringkasan, roster, dan riwayat satu sesi.',
          requiredPermissions: ['session_view'],
        },
      },
      {
        path: 'enrollment',
        name: 'enrollment',
        component: EnrollmentView,
        meta: {
          title: 'Pendaftaran wajah',
          description:
            'Buat atau perbarui data acuan wajah siswa (berbeda dari data master identitas & keanggotaan kelas).',
          requiredPermissions: ['enrollment_manage'],
        },
      },
      {
        path: 'corrections',
        name: 'corrections',
        component: CorrectionsView,
        meta: {
          title: 'Koreksi kehadiran',
          description: 'Antrean pengajuan, keputusan, dan jejak sebelum/sesudah.',
          requiredPermissions: ['attendance_correct'],
          pageHeaderInView: true,
        },
      },
      {
        path: 'corrections/:correctionId',
        name: 'correction-detail',
        component: CorrectionsView,
        meta: {
          title: 'Detail koreksi',
          description: 'Bukti, status lama, usulan, alasan, dan riwayat.',
          requiredPermissions: ['attendance_correct'],
          pageHeaderInView: true,
        },
      },
      {
        path: 'attendance-policy',
        name: 'attendance-policy',
        component: AttendancePolicyView,
        meta: {
          title: 'Kebijakan presensi',
          description: 'Jendela otomatis, toleransi, dan ambang EWS yang berlaku.',
          requiredRoles: ['ADMIN'],
          pageHeaderInView: true,
        },
      },
      {
        path: 'audit',
        name: 'audit',
        component: AuditView,
        meta: {
          title: 'Audit aktivitas',
          description: 'Jejak perubahan akun, penugasan, koreksi, dan PIN.',
          requiredRoles: ['ADMIN'],
          pageHeaderInView: true,
        },
      },
      {
        path: 'forbidden',
        name: 'forbidden',
        component: ForbiddenView,
        meta: {
          title: 'Akses tidak tersedia',
          description: 'Akun Anda tidak memiliki izin untuk halaman ini.',
        },
      },
    ],
  },
  {
    path: '/presensi',
    name: 'presensi',
    component: () => import('../views/DisplayView.vue'),
    meta: {
      layout: 'auth',
      title: 'Layar presensi',
      description: 'Kiosk siswa tanpa login staf: pilih lab & kamera, PIN, fullscreen.',
    },
  },
  {
    path: '/display',
    redirect: '/presensi',
  },
  {
    path: '/:pathMatch(.*)*',
    redirect: '/',
  },
]

/** Post-login redirect targets must stay inside this app.

Accepts only absolute in-app paths: a single leading slash, never a
protocol-relative (`//host`) or backslash-escaped (`/\\`) target that a
browser would resolve outside this origin.
*/
export function isSafeRedirectPath(value: unknown): value is string {
  return (
    typeof value === 'string' &&
    value.startsWith('/') &&
    !value.startsWith('//') &&
    !value.startsWith('/\\')
  )
}

export function createAppRouter(history: RouterHistory = createWebHistory()): Router {
  return createRouter({ history, routes })
}

export function installAuthGuard(router: Router, pinia: Pinia): void {
  router.beforeEach(async (to) => {
    const auth = useAuthStore(pinia)
    await auth.restoreSession()
    const requiresAuth = to.matched.some((record) => record.meta.requiresAuth)
    const hasSession = auth.hasActiveSession()

    if (requiresAuth && !hasSession) {
      return { name: 'login', query: { redirect: to.fullPath } }
    }

    if (auth.passwordChangeRequired && to.name !== 'change-password') {
      return { name: 'change-password' }
    }

    if (to.name === 'change-password' && !hasSession) {
      return { name: 'login' }
    }

    if (requiresAuth && to.meta.requiredRoles?.length) {
      const hasRole = to.meta.requiredRoles.some((role) => auth.account?.roles.includes(role))
      if (!hasRole) return { name: 'forbidden' }
    }

    if (requiresAuth && to.meta.requiredPermissions?.length) {
      const roles = auth.account?.roles ?? []
      const perms = (auth.account?.permissions ?? []) as string[]
      const isAdmin = roles.includes('ADMIN')
      if (!isAdmin) {
        const missing = to.meta.requiredPermissions.filter((perm) => !perms.includes(perm))
        if (missing.length) return { name: 'forbidden' }
      }
    }

    if (to.name === 'login' && hasSession) {
      if (auth.passwordChangeRequired) return { name: 'change-password' }
      const requestedRoute = to.query.redirect
      return isSafeRedirectPath(requestedRoute) ? requestedRoute : { name: 'dashboard' }
    }
    return true
  })
}

declare module 'vue-router' {
  interface RouteMeta {
    layout?: 'auth' | 'authenticated'
    requiresAuth?: boolean
    requiredRoles?: string[]
    requiredPermissions?: string[]
    title?: string
    description?: string
    pageHeaderInView?: boolean
  }
}

export const router = createAppRouter()
