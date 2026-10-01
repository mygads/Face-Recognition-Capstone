import createClient, { type Middleware } from 'openapi-fetch'
import type { components, paths } from './generated/schema'

export type AuthenticatedAccount = components['schemas']['CurrentUserResponse']
export type AccessToken = components['schemas']['TokenResponse']
export type Student = components['schemas']['StudentResponse']
export type StudentDetails = components['schemas']['StudentDetailResponse']
export type StudentCreate = components['schemas']['StudentCreateRequest']
export type StudentUpdate = components['schemas']['StudentUpdateRequest']
export type SchoolClass = components['schemas']['ClassResponse']
export type ClassDetails = components['schemas']['ClassDetailResponse']
export type ClassStudent = components['schemas']['ClassStudentResponse']
export type ClassCreate = components['schemas']['ClassCreateRequest']
export type ClassUpdate = components['schemas']['ClassUpdateRequest']
export type Laboratory = components['schemas']['LaboratoryResponse']
export type LaboratoryCreate = components['schemas']['LaboratoryCreateRequest']
export type LaboratoryUpdate = components['schemas']['LaboratoryUpdateRequest']
type ErrorDetail = components['schemas']['ErrorDetail']
type ErrorEnvelope = components['schemas']['ErrorEnvelope']
type Page<T> = {
  items: T[]
  pagination: components['schemas']['Pagination']
}

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

type ListQuery = { limit: number; offset: number; search?: string; is_active?: boolean }

export async function listStudents(query: ListQuery): Promise<Page<Student>> {
  const result = await apiClient.GET('/api/v1/students', { params: { query } })
  return unwrap(result)
}

export async function getStudent(studentId: string): Promise<StudentDetails> {
  const result = await apiClient.GET('/api/v1/students/{student_id}', {
    params: { path: { student_id: studentId } },
  })
  return unwrap(result)
}

export async function createStudent(body: StudentCreate): Promise<Student> {
  const result = await apiClient.POST('/api/v1/students', { body })
  return unwrap(result)
}

export async function updateStudent(studentId: string, body: StudentUpdate): Promise<Student> {
  const result = await apiClient.PATCH('/api/v1/students/{student_id}', {
    params: { path: { student_id: studentId } },
    body,
  })
  return unwrap(result)
}

export async function listClasses(query: ListQuery): Promise<Page<SchoolClass>> {
  const result = await apiClient.GET('/api/v1/classes', { params: { query } })
  return unwrap(result)
}

export async function getClass(classId: string): Promise<ClassDetails> {
  const result = await apiClient.GET('/api/v1/classes/{class_id}', {
    params: { path: { class_id: classId } },
  })
  return unwrap(result)
}

export async function createClass(body: ClassCreate): Promise<SchoolClass> {
  const result = await apiClient.POST('/api/v1/classes', { body })
  return unwrap(result)
}

export async function updateClass(classId: string, body: ClassUpdate): Promise<SchoolClass> {
  const result = await apiClient.PATCH('/api/v1/classes/{class_id}', {
    params: { path: { class_id: classId } },
    body,
  })
  return unwrap(result)
}

export async function enrollStudent(classId: string, studentId: string): Promise<ClassStudent> {
  const result = await apiClient.POST('/api/v1/classes/{class_id}/students', {
    params: { path: { class_id: classId } },
    body: { student_id: studentId },
  })
  return unwrap(result)
}

export async function removeStudentFromClass(classId: string, studentId: string): Promise<void> {
  const result = await apiClient.DELETE('/api/v1/classes/{class_id}/students/{student_id}', {
    params: { path: { class_id: classId, student_id: studentId } },
  })
  if (!result.response.ok) throw toApiError(result.response.status, result.error)
}

export async function listLaboratories(query: ListQuery): Promise<Page<Laboratory>> {
  const result = await apiClient.GET('/api/v1/laboratories', { params: { query } })
  return unwrap(result)
}

export async function getLaboratory(laboratoryId: string): Promise<Laboratory> {
  const result = await apiClient.GET('/api/v1/laboratories/{laboratory_id}', {
    params: { path: { laboratory_id: laboratoryId } },
  })
  return unwrap(result)
}

export async function createLaboratory(body: LaboratoryCreate): Promise<Laboratory> {
  const result = await apiClient.POST('/api/v1/laboratories', { body })
  return unwrap(result)
}

export async function updateLaboratory(
  laboratoryId: string,
  body: LaboratoryUpdate,
): Promise<Laboratory> {
  const result = await apiClient.PATCH('/api/v1/laboratories/{laboratory_id}', {
    params: { path: { laboratory_id: laboratoryId } },
    body,
  })
  return unwrap(result)
}
