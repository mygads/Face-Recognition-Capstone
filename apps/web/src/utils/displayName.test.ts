import { describe, expect, it } from 'vitest'
import { shortDisplayName } from './displayName'

describe('shortDisplayName', () => {
  it('menyingkat nama belakang menjadi inisial', () => {
    expect(shortDisplayName('Raka Pratama')).toBe('Raka P.')
  })
  it('nama tunggal tetap utuh', () => {
    expect(shortDisplayName('Sinta')).toBe('Sinta')
  })
  it('kosong menjadi strip', () => {
    expect(shortDisplayName('')).toBe('-')
    expect(shortDisplayName(null)).toBe('-')
  })
})
