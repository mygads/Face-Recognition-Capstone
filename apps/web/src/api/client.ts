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
export type StudentImportPreview = components['schemas']['StudentImportPreviewResponse']
export type StudentImportCommit = components['schemas']['StudentImportCommitResponse']
export type Schedule = components['schemas']['ScheduleResponse']
export type ScheduleCreate = components['schemas']['ScheduleCreateRequest']
export type ScheduleUpdate = components['schemas']['ScheduleUpdateRequest']
export type ScheduleTeacher = components['schemas']['ScheduleTeacherResponse']
export type AttendanceSession = components['schemas']['AttendanceSessionResponse']
export type OpenableSchedule = components['schemas']['OpenableScheduleResponse']
export type EnrollmentStudentStatus = components['schemas']['EnrollmentStudentStatusResponse']
export type EnrollmentCaptureResult = components['schemas']['EnrollmentCaptureResultResponse']
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

export async function listSchedules(query: {
  limit: number
  offset: number
  search?: string
  weekday?: number
  is_active?: boolean
}): Promise<Page<Schedule>> {
  const result = await apiClient.GET('/api/v1/schedules', { params: { query } })
  return unwrap(result)
}

export async function getSchedule(scheduleId: string): Promise<Schedule> {
  const result = await apiClient.GET('/api/v1/schedules/{schedule_id}', {
    params: { path: { schedule_id: scheduleId } },
  })
  return unwrap(result)
}

export async function createSchedule(body: ScheduleCreate): Promise<Schedule> {
  const result = await apiClient.POST('/api/v1/schedules', { body })
  return unwrap(result)
}

export async function updateSchedule(scheduleId: string, body: ScheduleUpdate): Promise<Schedule> {
  const result = await apiClient.PATCH('/api/v1/schedules/{schedule_id}', {
    params: { path: { schedule_id: scheduleId } },
    body,
  })
  return unwrap(result)
}

export async function listScheduleTeachers(): Promise<ScheduleTeacher[]> {
  const result = await apiClient.GET('/api/v1/schedules/teachers')
  return unwrap(result)
}

export async function listOpenableSchedules(): Promise<OpenableSchedule[]> {
  const result = await apiClient.GET('/api/v1/sessions/openable-schedules')
  return unwrap(result)
}

export async function listAttendanceSessions(query: {
  status?: 'active' | 'closed' | 'cancelled'
  limit: number
  offset: number
}): Promise<Page<AttendanceSession>> {
  const result = await apiClient.GET('/api/v1/sessions', { params: { query } })
  return unwrap(result)
}

export async function openAttendanceSession(
  practicumScheduleId: string,
  gracePeriodMinutes = 15,
): Promise<AttendanceSession> {
  const result = await apiClient.POST('/api/v1/sessions', {
    body: {
      practicum_schedule_id: practicumScheduleId,
      grace_period_minutes: gracePeriodMinutes,
    },
  })
  return unwrap(result)
}

export async function getAttendanceSessionStatus(sessionId: string): Promise<AttendanceSession> {
  const result = await apiClient.GET('/api/v1/sessions/{session_id}', {
    params: { path: { session_id: sessionId } },
  })
  return unwrap(result)
}

export async function closeAttendanceSession(sessionId: string): Promise<AttendanceSession> {
  const result = await apiClient.POST('/api/v1/sessions/{session_id}/close', {
    params: { path: { session_id: sessionId } },
  })
  return unwrap(result)
}

export async function listClassEnrollmentStatus(
  classId: string,
): Promise<EnrollmentStudentStatus[]> {
  const result = await apiClient.GET('/api/v1/enrollments/class-status', {
    params: { query: { class_id: classId } },
  })
  return unwrap(result)
}

export async function submitEnrollmentCaptures(
  studentId: string,
  captures: Blob[],
): Promise<EnrollmentCaptureResult> {
  const body = new FormData()
  body.append('student_id', studentId)
  captures.forEach((capture, index) => {
    body.append('captures', capture, `capture-${index + 1}.jpg`)
  })
  const result = await apiClient.POST('/api/v1/enrollments/captures', {
    body: body as unknown as components['schemas']['Body_submit_enrollment_captures_api_v1_enrollments_captures_post'],
  })
  return unwrap(result)
}

export type StudentImportMapping = {
  student_number_column: string
  full_name_column: string
  class_code_column: string
}

function studentImportForm(file: File, mapping: StudentImportMapping): FormData {
  const body = new FormData()
  body.append('upload', file, file.name)
  body.append('student_number_column', mapping.student_number_column)
  body.append('full_name_column', mapping.full_name_column)
  body.append('class_code_column', mapping.class_code_column)
  return body
}

export async function previewStudentImport(
  file: File,
  mapping: StudentImportMapping,
): Promise<StudentImportPreview> {
  const result = await apiClient.POST('/api/v1/students/import/preview', {
    body: studentImportForm(
      file,
      mapping,
    ) as unknown as components['schemas']['Body_preview_student_import_api_v1_students_import_preview_post'],
  })
  return unwrap(result)
}

export async function commitStudentImport(
  file: File,
  mapping: StudentImportMapping,
): Promise<StudentImportCommit> {
  const result = await apiClient.POST('/api/v1/students/import/commit', {
    body: studentImportForm(
      file,
      mapping,
    ) as unknown as components['schemas']['Body_commit_student_import_api_v1_students_import_commit_post'],
  })
  return unwrap(result)
}
