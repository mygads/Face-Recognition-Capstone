import { afterEach, describe, expect, it, vi } from 'vitest'
import { triggerDownload } from './download'

describe('triggerDownload', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('downloads via a detached anchor and revokes the object URL', async () => {
    const blob = new Blob(['a,b'], { type: 'text/csv' })
    const objectUrl = 'blob:unit-test'
    const createObjectURL = vi.spyOn(URL, 'createObjectURL').mockReturnValue(objectUrl)
    const revokeObjectURL = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})

    triggerDownload(blob, 'laporan.csv')

    expect(createObjectURL).toHaveBeenCalledWith(blob)
    expect(click).toHaveBeenCalledOnce()
    expect(document.querySelector('a[download="laporan.csv"]')).toBeNull()
    await new Promise((resolve) => window.setTimeout(resolve, 5))
    expect(revokeObjectURL).toHaveBeenCalledWith(objectUrl)
  })
})
