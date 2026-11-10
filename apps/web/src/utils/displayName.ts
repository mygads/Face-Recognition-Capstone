/** Nama singkat untuk layar publik (privasi minim). "Raka Pratama" -> "Raka P." */
export function shortDisplayName(fullName: string | null | undefined): string {
  const clean = (fullName ?? '').trim().replace(/\s+/g, ' ')
  if (!clean) return '-'
  const parts = clean.split(' ')
  if (parts.length === 1) return parts[0]
  const lastInitial = parts[parts.length - 1].charAt(0).toUpperCase()
  return lastInitial ? `${parts[0]} ${lastInitial}.` : parts[0]
}
