import { defineStore } from 'pinia'
import { ref } from 'vue'
import {
  ApiError,
  changePassword,
  getCurrentAccount,
  loginWithPassword,
  type AuthenticatedAccount,
} from '../api/client'

export const useAuthStore = defineStore('auth', () => {
  const accessToken = ref<string | null>(null)
  const expiresAt = ref<number | null>(null)
  const account = ref<AuthenticatedAccount | null>(null)
  const passwordChangeRequired = ref(false)
  const isLoading = ref(false)
  const errorMessage = ref<string | null>(null)
  let expiryTimer: ReturnType<typeof setTimeout> | undefined

  function clearSession(): void {
    if (expiryTimer !== undefined) clearTimeout(expiryTimer)
    expiryTimer = undefined
    accessToken.value = null
    expiresAt.value = null
    account.value = null
    passwordChangeRequired.value = false
  }

  function getValidAccessToken(): string | null {
    if (!accessToken.value || !expiresAt.value || expiresAt.value <= Date.now()) {
      clearSession()
      return null
    }
    return accessToken.value
  }

  function hasActiveSession(): boolean {
    return getValidAccessToken() !== null
  }

  function logout(): void {
    clearSession()
    errorMessage.value = null
  }

  async function login(email: string, password: string): Promise<void> {
    clearSession()
    errorMessage.value = null
    isLoading.value = true

    try {
      const token = await loginWithPassword(email, password)
      accessToken.value = token.access_token
      expiresAt.value = Date.now() + token.expires_in_seconds * 1000
      expiryTimer = setTimeout(clearSession, token.expires_in_seconds * 1000)
      passwordChangeRequired.value = Boolean(token.password_change_required)
      if (passwordChangeRequired.value) return
      account.value = await getCurrentAccount()
    } catch (error) {
      clearSession()
      errorMessage.value =
        error instanceof ApiError && error.status === 401
          ? 'Email atau kata sandi tidak valid.'
          : 'Tidak dapat masuk saat ini. Periksa koneksi lalu coba lagi.'
      throw error
    } finally {
      isLoading.value = false
    }
  }

  async function updatePassword(currentPassword: string, newPassword: string): Promise<void> {
    await changePassword({
      current_password: currentPassword,
      new_password: newPassword,
    })
    logout()
  }

  return {
    accessToken,
    expiresAt,
    account,
    passwordChangeRequired,
    isLoading,
    errorMessage,
    getValidAccessToken,
    hasActiveSession,
    login,
    logout,
    updatePassword,
  }
})
