import { defineStore } from 'pinia'
import { ref } from 'vue'
import {
  ApiError,
  changePassword,
  endOperatorSession,
  getCurrentAccount,
  loginWithPassword,
  refreshOperatorSession,
  type AccessToken,
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
  let restoreAttempted = false
  let refreshPromise: Promise<boolean> | undefined
  let onSessionExpired: () => void = () => undefined

  function clearSession(): void {
    if (expiryTimer !== undefined) clearTimeout(expiryTimer)
    expiryTimer = undefined
    accessToken.value = null
    expiresAt.value = null
    account.value = null
    passwordChangeRequired.value = false
  }

  function setSessionExpiredHandler(handler: () => void): void {
    onSessionExpired = handler
  }

  function setAccessToken(token: AccessToken): void {
    if (expiryTimer !== undefined) clearTimeout(expiryTimer)
    restoreAttempted = false
    accessToken.value = token.access_token
    expiresAt.value = Date.now() + token.expires_in_seconds * 1000
    passwordChangeRequired.value = Boolean(token.password_change_required)
    const refreshDelay = Math.max(1_000, token.expires_in_seconds * 1000 - 30_000)
    expiryTimer = setTimeout(() => {
      void refreshSession(true)
    }, refreshDelay)
  }

  function getValidAccessToken(): string | null {
    if (!accessToken.value || !expiresAt.value || expiresAt.value <= Date.now()) {
      return null
    }
    return accessToken.value
  }

  function hasActiveSession(): boolean {
    return getValidAccessToken() !== null
  }

  async function logout(): Promise<void> {
    restoreAttempted = true
    clearSession()
    errorMessage.value = null
    await endOperatorSession().catch(() => undefined)
  }

  function handleRejectedAccessToken(): void {
    clearSession()
    restoreAttempted = false
  }

  async function refreshSession(notifyFailure = false): Promise<boolean> {
    if (refreshPromise) return refreshPromise
    refreshPromise = (async () => {
      try {
        const token = await refreshOperatorSession()
        setAccessToken(token)
        if (passwordChangeRequired.value) {
          account.value = null
        } else {
          account.value = await getCurrentAccount()
        }
        return true
      } catch {
        clearSession()
        restoreAttempted = true
        if (notifyFailure) onSessionExpired()
        return false
      } finally {
        refreshPromise = undefined
      }
    })()
    return refreshPromise
  }

  async function restoreSession(): Promise<void> {
    if (hasActiveSession() || restoreAttempted) return
    restoreAttempted = true
    await refreshSession()
  }

  async function login(email: string, password: string): Promise<void> {
    clearSession()
    restoreAttempted = true
    errorMessage.value = null
    isLoading.value = true

    try {
      const token = await loginWithPassword(email, password)
      setAccessToken(token)
      if (passwordChangeRequired.value) return
      account.value = await getCurrentAccount()
    } catch (error) {
      clearSession()
      restoreAttempted = true
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
    restoreAttempted = true
    clearSession()
  }

  return {
    accessToken,
    expiresAt,
    account,
    passwordChangeRequired,
    isLoading,
    errorMessage,
    setSessionExpiredHandler,
    getValidAccessToken,
    hasActiveSession,
    restoreSession,
    handleRejectedAccessToken,
    login,
    logout,
    updatePassword,
  }
})
