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
import DashboardView from '../views/DashboardView.vue'
import DevicesView from '../views/DevicesView.vue'
import EnrollmentView from '../views/EnrollmentView.vue'
import ForbiddenView from '../views/ForbiddenView.vue'
import LoginView from '../views/LoginView.vue'
import MasterDataView from '../views/MasterDataView.vue'
import ChangePasswordView from '../views/ChangePasswordView.vue'
import AccountsView from '../views/AccountsView.vue'
import ProfileView from '../views/ProfileView.vue'
import ReportsView from '../views/ReportsView.vue'
import ScheduleView from '../views/ScheduleView.vue'
import SessionsView from '../views/SessionsView.vue'
import AiSetupView from '../views/AiSetupView.vue'
import CameraPreviewView from '../views/CameraPreviewView.vue'

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
          description: 'Pantau kehadiran dan konektivitas perangkat secara live.',
        },
      },
      {
        path: 'profile',
        name: 'profile',
        component: ProfileView,
        meta: {
          title: 'Profil akun',
          description: 'Lihat informasi akun dan perbarui kata sandi.',
        },
      },
      {
        path: 'master-data',
        name: 'master-data',
        component: MasterDataView,
        meta: {
          title: 'Data master',
          description: 'Kelola data siswa, kelas, dan laboratorium.',
          requiredRoles: ['ADMIN'],
        },
      },
      {
        path: 'accounts',
        name: 'accounts',
        component: AccountsView,
        meta: {
          title: 'Kelola akun staf',
          description: 'Buat akun guru dan laboran untuk menggunakan sistem.',
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
          description: 'Lihat kamera AI_EDGE dan kandidat identitas secara langsung.',
          requiredRoles: ['ADMIN', 'LABORANT'],
          pageHeaderInView: true,
        },
      },
      {
        path: 'devices',
        name: 'devices',
        component: DevicesView,
        meta: {
          title: 'Perangkat',
          description: 'Kelola penempatan dan pantau kondisi perangkat presensi.',
          requiredRoles: ['ADMIN', 'LABORANT'],
          pageHeaderInView: true,
        },
      },
      {
        path: 'reports',
        name: 'reports',
        component: ReportsView,
        meta: {
          title: 'Laporan kehadiran',
          description: 'Tinjau kehadiran berdasarkan siswa, kelas, lab, sesi, dan periode.',
          requiredRoles: ['ADMIN', 'TEACHER'],
        },
      },
      {
        path: 'schedules',
        name: 'schedules',
        component: ScheduleView,
        meta: {
          title: 'Jadwal praktikum',
          description: 'Atur kelas, laboratorium, guru, dan waktu praktikum.',
          requiredRoles: ['ADMIN', 'TEACHER'],
        },
      },
      {
        path: 'sessions',
        name: 'sessions',
        component: SessionsView,
        meta: {
          title: 'Sesi presensi',
          description: 'Buka sesi praktikum dan pantau roster presensi.',
          requiredRoles: ['ADMIN', 'TEACHER', 'LABORANT'],
        },
      },
      {
        path: 'enrollment',
        name: 'enrollment',
        component: EnrollmentView,
        meta: {
          title: 'Pendaftaran siswa',
          description: 'Daftarkan atau perbarui template wajah siswa dengan bantuan kamera.',
          requiredRoles: ['ADMIN', 'LABORANT'],
        },
      },
      {
        path: 'forbidden',
        name: 'forbidden',
        component: ForbiddenView,
        meta: {
          title: 'Akses tidak tersedia',
          description: 'Akun Anda tidak memiliki role yang dibutuhkan untuk halaman ini.',
        },
      },
    ],
  },
  {
    path: '/:pathMatch(.*)*',
    redirect: '/',
  },
]

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

    if (to.name === 'login' && hasSession) {
      if (auth.passwordChangeRequired) return { name: 'change-password' }
      const requestedRoute = to.query.redirect
      return typeof requestedRoute === 'string' && requestedRoute.startsWith('/')
        ? requestedRoute
        : { name: 'dashboard' }
    }
    return true
  })
}

declare module 'vue-router' {
  interface RouteMeta {
    layout?: 'auth' | 'authenticated'
    requiresAuth?: boolean
    requiredRoles?: string[]
    title?: string
    description?: string
    pageHeaderInView?: boolean
  }
}

export const router = createAppRouter()
