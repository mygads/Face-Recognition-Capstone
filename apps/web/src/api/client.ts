import createClient, { type Middleware } from 'openapi-fetch'
import type { components, paths } from './generated/schema'

export type AuthenticatedAccount = components['schemas']['CurrentUserResponse']
export type AccessToken = components['schemas']['TokenResponse']
type ErrorDetail = components['schemas']['ErrorDetail']
type ErrorEnvelope = components['schemas']['ErrorEnvelope']

type ApiAuthHandlers = {
  getAccessToken: () => string | null
  onUnauthorized: () => void
}

let authHandlers: ApiAuthHandlers = {
  getAccessToken: () => null,
  onUnauthorized: () => undefined,
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly details?: ErrorDetail[] | null,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

export function configureApiAuth(handlers: ApiAuthHandlers): void {
  authHandlers = handlers
}

const authMiddleware: Middleware = {
  onRequest({ request }) {
    const token = authHandlers.getAccessToken()
    if (token) request.headers.set('Authorization', `Bearer ${token}`)
    return request
  },
  onResponse({ response, schemaPath }) {
    if (response.status === 401 && schemaPath !== '/api/v1/auth/login') {
      authHandlers.onUnauthorized()
    }
  },
  onError() {
    return new ApiError(0, 'network_error', 'Tidak dapat terhubung ke server.')
  },
}

const apiClient = createClient<paths>({ baseUrl: '' })
apiClient.use(authMiddleware)

type ApiResult<T> = {
  data?: T
  error?: unknown
  response: Response
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

function toApiError(status: number, payload: unknown): ApiError {
  const candidate = isRecord(payload) && isRecord(payload.error) ? payload.error : null
  const details = candidate?.details

  return new ApiError(
    status,
    typeof candidate?.code === 'string' ? candidate.code : 'request_failed',
    typeof candidate?.message === 'string' ? candidate.message : 'Permintaan tidak dapat diproses.',
    Array.isArray(details) ? (details as ErrorEnvelope['error']['details']) : undefined,
  )
}

function unwrap<T>(result: ApiResult<T>): T {
  if (!result.response.ok) throw toApiError(result.response.status, result.error)
  if (result.data === undefined) {
    throw new ApiError(result.response.status, 'empty_response', 'Respons server kosong.')
  }
  return result.data
}

export async function loginWithPassword(email: string, password: string): Promise<AccessToken> {
  const result = await apiClient.POST('/api/v1/auth/login', {
    body: { username: email.trim(), password, scope: '' },
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
  })
  return unwrap(result)
}

export async function getCurrentAccount(): Promise<AuthenticatedAccount> {
  const result = await apiClient.GET('/api/v1/auth/me')
  return unwrap(result)
}
