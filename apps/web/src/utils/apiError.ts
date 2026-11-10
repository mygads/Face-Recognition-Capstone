import { ApiError } from '../api/client'

const FIELD_LABELS: Record<string, string> = {
  class_id: 'Kelas',
  laboratory_id: 'Laboratorium',
  teacher_user_id: 'Guru',
  subject: 'Nama pertemuan',
  weekday: 'Hari',
  start_time: 'Jam mulai',
  end_time: 'Jam selesai',
  timezone_name: 'Zona waktu',
  effective_from: 'Tanggal berlaku',
  student_id: 'Siswa',
  session_id: 'Sesi',
  decision: 'Keputusan',
  decision_note: 'Catatan keputusan',
  reason: 'Alasan',
  status: 'Status',
  pin: 'PIN',
  name: 'Nama',
  code: 'Kode',
}

export function cleanDetailMessage(message: string): string {
  return message
    .replace(/^Value error, /, '')
    .replace(/^Input should be a valid UUID.*$/, 'Wajib dipilih.')
    .replace(/^String should have at least 1 character.*$/, 'Wajib diisi.')
    .replace(/^Request validation failed\.?$/, 'Data belum valid.')
}

export function cleanFieldName(field: string): string {
  const short = field.includes('.') ? (field.split('.').pop() ?? field) : field
  if (short === 'body' || short === '') return ''
  return FIELD_LABELS[short] ?? short
}

/** Pesan error API yang aman dibaca pengguna: tanpa "body:"/"Value error" mentah. */
export function formatApiError(error: unknown, fallback: string): string {
  if (error instanceof ApiError) {
    const details = error.details?.map((item) => {
      const message = cleanDetailMessage(item.message)
      const label = cleanFieldName(item.field)
      return label ? label + ': ' + message : message
    })
    if (details?.length) return details.join(' · ')
    return cleanDetailMessage(error.message.replace(/^body: Value error, /, ''))
  }
  return fallback
}
