import { describe, expect, it } from 'vitest'
import { getSourceFrame } from './useFaceLandmarks'

describe('getSourceFrame', () => {
  it('accepts decoded MJPEG image frames while the stream request is still open', () => {
    const image = {
      complete: false,
      naturalWidth: 640,
      naturalHeight: 480,
    } as HTMLImageElement

    expect(getSourceFrame(image)).toEqual({ ready: true, width: 640, height: 480 })
  })

  it('waits until an image has usable intrinsic dimensions', () => {
    const image = {
      complete: false,
      naturalWidth: 0,
      naturalHeight: 0,
    } as HTMLImageElement

    expect(getSourceFrame(image)).toEqual({ ready: false, width: 0, height: 0 })
  })
})
