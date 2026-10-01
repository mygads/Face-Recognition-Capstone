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
import ForbiddenView from '../views/ForbiddenView.vue'
import LoginView from '../views/LoginView.vue'
import MasterDataView from '../views/MasterDataView.vue'

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
          description: 'Ruang kerja presensi praktikum.',
        },
      },
      {
        path: 'master-data',
        name: 'master-data',
        component: MasterDataView,
        meta: {
          title: 'Data master',
          description: 'Kelola data siswa, kelas, dan laboratorium.',
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
  router.beforeEach((to) => {
    const auth = useAuthStore(pinia)
    const requiresAuth = to.matched.some((record) => record.meta.requiresAuth)
    const hasSession = auth.hasActiveSession()

    if (requiresAuth && !hasSession) {
      return { name: 'login', query: { redirect: to.fullPath } }
    }

    if (requiresAuth && to.meta.requiredRoles?.length) {
      const hasRole = to.meta.requiredRoles.some((role) => auth.account?.roles.includes(role))
      if (!hasRole) return { name: 'forbidden' }
    }

    if (to.name === 'login' && hasSession) return { name: 'dashboard' }
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
  }
}

export const router = createAppRouter()
