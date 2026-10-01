import { createApp } from 'vue'
import { createPinia } from 'pinia'
import './style.scss'
import App from './App.vue'
import { configureApiAuth } from './api/client'
import { useAuthStore } from './stores/auth'
import { installAuthGuard, router } from './router'

const pinia = createPinia()
installAuthGuard(router, pinia)
configureApiAuth({
  getAccessToken: () => useAuthStore(pinia).getValidAccessToken(),
  onUnauthorized: () => {
    const auth = useAuthStore(pinia)
    auth.logout()
    if (router.currentRoute.value.meta.requiresAuth) {
      void router.replace({
        name: 'login',
        query: { redirect: router.currentRoute.value.fullPath },
      })
    }
  },
})

createApp(App).use(pinia).use(router).mount('#app')
