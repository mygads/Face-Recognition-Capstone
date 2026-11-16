import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import FaceOverlay from './FaceOverlay.vue'

describe('FaceOverlay', () => {
  it('menyorot wajah terbesar dan menggambar lima titik landmark', () => {
    const wrapper = mount(FaceOverlay, {
      props: {
        label: 'Wajah utama',
        faces: [
          {
            x: 0.05,
            y: 0.05,
            width: 0.1,
            height: 0.1,
            landmarks: [
              [0.07, 0.08],
              [0.1, 0.08],
              [0.085, 0.11],
              [0.07, 0.13],
              [0.1, 0.13],
            ],
          },
          {
            x: 0.4,
            y: 0.2,
            width: 0.3,
            height: 0.4,
            landmarks: [
              [0.45, 0.3],
              [0.6, 0.3],
              [0.52, 0.4],
              [0.47, 0.5],
              [0.58, 0.5],
            ],
          },
        ],
      },
    })
    const marks = wrapper.findAll('[data-testid^="face-box-"]')
    expect(marks).toHaveLength(2)
    expect(marks[1].classes()).toContain('is-primary')
    expect(marks[0].classes()).toContain('is-secondary')
    expect(wrapper.findAll('.face-overlay__point')).toHaveLength(10)
    expect(wrapper.text()).toContain('Wajah utama')
  })

  it('aman tanpa wajah', () => {
    const wrapper = mount(FaceOverlay, { props: { faces: [] } })
    expect(wrapper.find('[data-testid="face-overlay"]').exists()).toBe(true)
    expect(wrapper.findAll('[data-testid^="face-box-"]')).toHaveLength(0)
  })
})
