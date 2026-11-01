import { describe, expect, it } from 'vitest'
import { createRefreshEpoch } from './refresh'

describe('createRefreshEpoch', () => {
  it('keeps only the latest generation current', () => {
    const guard = createRefreshEpoch()
    const first = guard.next()
    const second = guard.next()
    expect(guard.isCurrent(first)).toBe(false)
    expect(guard.isCurrent(second)).toBe(true)
  })

  it('starts with no current generation', () => {
    const guard = createRefreshEpoch()
    expect(guard.isCurrent(0)).toBe(false)
    expect(guard.isCurrent(1)).toBe(false)
  })
})
