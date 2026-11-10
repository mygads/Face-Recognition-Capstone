import { describe, expect, it } from 'vitest'
import {
  dateTimeFormatterFor,
  formatDateTime,
  formatTimeOfDay,
  timeFormatterFor,
  todayLocalISO,
} from './dateFormat'

describe('dateFormat utils', () => {
  it('caches formatters per timezone', () => {
    expect(dateTimeFormatterFor('Asia/Jakarta')).toBe(dateTimeFormatterFor('Asia/Jakarta'))
    expect(timeFormatterFor('Asia/Jakarta')).toBe(timeFormatterFor('Asia/Jakarta'))
  })

  it('falls back for an invalid timezone instead of throwing', () => {
    expect(() => formatDateTime('2026-01-01T00:00:00Z', 'Invalid/Zone')).not.toThrow()
    expect(() => formatTimeOfDay('2026-01-01T00:00:00Z', 'Invalid/Zone')).not.toThrow()
  })

  it('formats the same instant differently across timezones', () => {
    const instant = '2026-01-01T00:00:00Z'
    const jakarta = formatTimeOfDay(instant, 'Asia/Jakarta')
    const makassar = formatTimeOfDay(instant, 'Asia/Makassar')
    expect(jakarta).not.toBe(makassar)
  })
  it('builds local ISO dates with day offsets', () => {
    expect(todayLocalISO()).toMatch(/^\d{4}-\d{2}-\d{2}$/)
    expect(todayLocalISO(1)).not.toBe(todayLocalISO(-1))
  })
})

describe('formatDateTimeLocal', () => {
  it('renders in the browser local zone instead of hardcoded Jakarta', async () => {
    const { formatDateTimeLocal } = await import('./dateFormat')
    const instant = '2026-01-05T10:00:00Z'
    const expected = new Intl.DateTimeFormat('id-ID', {
      dateStyle: 'medium',
      timeStyle: 'short',
    }).format(new Date(instant))
    expect(formatDateTimeLocal(instant)).toBe(expected)
    expect(formatDateTimeLocal(null)).toBe('-')
  })
})
