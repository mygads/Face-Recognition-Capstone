import { describe, expect, it } from 'vitest'
import { getFaceMeshInputSize } from './faceMeshPerformance'

describe('getFaceMeshInputSize', () => {
  it('reduces a 720p visual frame while keeping its aspect ratio', () => {
    expect(getFaceMeshInputSize(1280, 720)).toEqual({ width: 480, height: 270 })
  })

  it('keeps the same pixel budget for a 4:3 camera frame', () => {
    expect(getFaceMeshInputSize(640, 480)).toEqual({ width: 416, height: 312 })
  })

  it('keeps smaller camera frames at their native dimensions', () => {
    expect(getFaceMeshInputSize(320, 240)).toEqual({ width: 320, height: 240 })
  })

  it('rejects invalid dimensions', () => {
    expect(() => getFaceMeshInputSize(0, 480)).toThrow(RangeError)
  })
})
