import {
  createRouter,
  createWebHistory,
  type Router,
  type RouterHistory,
  type RouteRecordRaw,
} from 'vue-router'
import AppShell from '../components/AppShell.vue'
import AuthLayout from '../layouts/AuthLayout.vue'
import DashboardView from '../views/DashboardView.vue'
import LoginView from '../views/LoginView.vue'

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
    meta: { layout: 'authenticated' },
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

export const router = createAppRouter()
