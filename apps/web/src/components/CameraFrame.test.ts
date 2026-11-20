import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import CameraFrame from './CameraFrame.vue'
import FaceOverlay from './FaceOverlay.vue'

describe('CameraFrame', () => {
  it('mempertahankan rasio frame dan menolak landmark agent yang jarang', () => {
    const wrapper = mount(CameraFrame, {
      props: {
        imageWidth: 640,
        imageHeight: 480,
        fit: 'contain',
        faces: [
          {
            x: 0.3,
            y: 0.2,
            width: 0.4,
            height: 0.55,
            landmarks: [
              [0.4, 0.4],
              [0.6, 0.4],
              [0.5, 0.53],
              [0.42, 0.66],
              [0.58, 0.66],
            ],
          },
        ],
      },
    })

    const viewport = wrapper.get('[data-testid="camera-frame"]').element as HTMLElement
    expect(viewport.style.aspectRatio).toBe('640 / 480')
    expect(wrapper.findComponent(FaceOverlay).props('fit')).toBe('contain')
    expect(wrapper.findAll('.face-overlay__point')).toHaveLength(0)
    expect(wrapper.findAll('.face-overlay__skeleton')).toHaveLength(0)
    expect(wrapper.findAll('[data-testid^="face-mark-"]')).toHaveLength(0)
  })
})
