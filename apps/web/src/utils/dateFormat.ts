const dateTimeCache = new Map<string, Intl.DateTimeFormat>()
const timeCache = new Map<string, Intl.DateTimeFormat>()

function cachedFormatter(
  cache: Map<string, Intl.DateTimeFormat>,
  timezone: string,
  build: (timeZone: string | undefined) => Intl.DateTimeFormat,
): Intl.DateTimeFormat {
  const cached = cache.get(timezone)
  if (cached) return cached
  try {
    const formatter = build(timezone)
    cache.set(timezone, formatter)
    return formatter
  } catch {
    const fallback = build(undefined)
    cache.set(timezone, fallback)
    return fallback
  }
}

export function dateTimeFormatterFor(timezone: string): Intl.DateTimeFormat {
  return cachedFormatter(dateTimeCache, timezone, (timeZone) =>
    timeZone === undefined
      ? new Intl.DateTimeFormat('id-ID', { dateStyle: 'medium', timeStyle: 'short' })
      : new Intl.DateTimeFormat('id-ID', {
          dateStyle: 'medium',
          timeStyle: 'short',
          timeZone,
        }),
  )
}

export function timeFormatterFor(timezone: string): Intl.DateTimeFormat {
  return cachedFormatter(timeCache, timezone, (timeZone) =>
    timeZone === undefined
      ? new Intl.DateTimeFormat('id-ID', { hour: '2-digit', minute: '2-digit' })
      : new Intl.DateTimeFormat('id-ID', {
          hour: '2-digit',
          minute: '2-digit',
          timeZone,
        }),
  )
}

export function formatDateTime(value: string, timezone: string): string {
  return dateTimeFormatterFor(timezone).format(new Date(value))
}

export function formatTimeOfDay(value: string, timezone: string): string {
  return timeFormatterFor(timezone).format(new Date(value))
}
let localDateTimeFormatter: Intl.DateTimeFormat | null = null

export function formatDateTimeLocal(value: string | null): string {
  if (!value) return '—'
  localDateTimeFormatter ??= new Intl.DateTimeFormat('id-ID', {
    dateStyle: 'medium',
    timeStyle: 'short',
  })
  return localDateTimeFormatter.format(new Date(value))
}

export function todayLocalISO(dayOffset = 0): string {
  const value = new Date()
  value.setDate(value.getDate() + dayOffset)
  return new Date(value.getTime() - value.getTimezoneOffset() * 60_000).toISOString().slice(0, 10)
}
