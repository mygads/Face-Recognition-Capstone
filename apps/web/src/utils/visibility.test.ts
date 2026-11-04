import { describe, expect, it, vi } from 'vitest'
import { shouldPausePolling } from './visibility'

describe('shouldPausePolling', () => {
  it('pauses when the tab is hidden', () => {
    vi.stubGlobal('document', { hidden: true } as unknown as Document)
    expect(shouldPausePolling()).toBe(true)
    vi.unstubAllGlobals()
  })

  it('polls when the tab is visible', () => {
    vi.stubGlobal('document', { hidden: false } as unknown as Document)
    expect(shouldPausePolling()).toBe(false)
    vi.unstubAllGlobals()
  })

  it('polls during SSR where document is undefined', () => {
    vi.stubGlobal('document', undefined)
    expect(shouldPausePolling()).toBe(false)
    vi.unstubAllGlobals()
  })
})
