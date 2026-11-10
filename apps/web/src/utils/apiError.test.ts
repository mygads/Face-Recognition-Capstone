import { describe, expect, it } from 'vitest'
import { ApiError, type ErrorDetail } from '../api/client'
import { formatApiError } from './apiError'

function apiError(message: string, details?: ErrorDetail[]) {
  return new ApiError(422, 'validation_error', message, details ?? null)
}

describe('formatApiError', () => {
  it('membersihkan prefix Value error dan field body generik', () => {
    const err = apiError('Request validation failed.', [
      { field: 'body', message: 'Value error, Alasan penolakan wajib diisi.', code: 'value_error' },
    ])
    expect(formatApiError(err, 'Gagal.')).toBe('Alasan penolakan wajib diisi.')
  })
  it('menerjemahkan nama field teknis ke label Indonesia', () => {
    const err = apiError('Request validation failed.', [
      { field: 'body.class_id', message: 'Input should be a valid UUID, xyz', code: 'uuid_type' },
      {
        field: 'body.subject',
        message: 'String should have at least 1 character',
        code: 'string_too_short',
      },
    ])
    expect(formatApiError(err, 'Gagal.')).toBe(
      'Kelas: Wajib dipilih. · Nama pertemuan: Wajib diisi.',
    )
  })
  it('memakai pesan server bila tidak ada detail', () => {
    const err = apiError('Siswa sudah memiliki catatan presensi.')
    expect(formatApiError(err, 'Gagal.')).toBe('Siswa sudah memiliki catatan presensi.')
  })
  it('memakai fallback untuk error non-API', () => {
    expect(formatApiError(new Error('boom'), 'Jaringan bermasalah.')).toBe('Jaringan bermasalah.')
  })
})
