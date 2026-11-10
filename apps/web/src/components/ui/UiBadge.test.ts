import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import UiBadge from './UiBadge.vue'

describe('UiBadge', () => {
  it('menerapkan tone late', () => {
    const w = mount(UiBadge, { props: { tone: 'late' }, slots: { default: 'Terlambat' } })
    expect(w.classes()).toContain('ui-badge--late')
    expect(w.text()).toBe('Terlambat')
  })
})
