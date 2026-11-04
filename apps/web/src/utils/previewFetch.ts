/**
 * Fetch ke agent preview (LAN/localhost) dengan pagu waktu.
 *
 * Tanpa pagu, polling frame 15fps/status 500ms akan menggantung berlapis
 * bila agent macet. AbortError dipetakan ke pesan Indonesia agar operator
 * lab langsung tahu yang perlu diperiksa.
 */
export const PREVIEW_TIMEOUT_MS = 10_000

export async function fetchWithPreviewTimeout(
  url: string,
  init: Parameters<typeof fetch>[1] = {},
  timeoutMs = PREVIEW_TIMEOUT_MS,
): Promise<Response> {
  const { signal, ...rest } = init
  const timeoutSignal = AbortSignal.timeout(timeoutMs)
  // Pagu harus tetap berlaku walau penelepon menitipkan signal sendiri
  // (mis. unmount komponen): gabungkan keduanya agar permintaan gantung
  // tetap dibatalkan tepat waktu.
  const combinedSignal =
    signal === undefined || signal === null
      ? timeoutSignal
      : typeof AbortSignal.any === 'function'
        ? AbortSignal.any([signal, timeoutSignal])
        : signal.aborted
          ? signal
          : timeoutSignal
  try {
    return await fetch(url, {
      ...rest,
      signal: combinedSignal,
    })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new Error(
        'Agent preview tidak merespons tepat waktu. Periksa koneksi ke komputer AI_EDGE.',
        { cause: error },
      )
    }
    throw error
  }
}
