import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import UiButton from './UiButton.vue'
import UiBadge from './UiBadge.vue'
import UiCard from './UiCard.vue'
import UiInput from './UiInput.vue'
import UiEmptyState from './UiEmptyState.vue'

describe('stitch ui kit', () => {
  it('tombol primer memakai token stitch', () => {
    const w = mount(UiButton, { props: { variant: 'primary' }, slots: { default: 'Masuk' } })
    expect(w.classes()).toContain('st-btn--primary')
  })

  it('badge terlambat memakai tone stitch', () => {
    const w = mount(UiBadge, { props: { tone: 'late' }, slots: { default: 'Terlambat' } })
    expect(w.classes()).toContain('st-badge--late')
  })

  it('kartu menampilkan judul portal staf', () => {
    const w = mount(UiCard, { props: { title: 'Portal Khusus Staf' } })
    expect(w.text()).toContain('Portal Khusus Staf')
  })

  it('input v-model memancarkan nilai', async () => {
    const w = mount(UiInput, { props: { modelValue: '' } })
    await w.setValue('nama@sekolah.edu')
    expect(w.emitted('update:modelValue')?.[0]).toEqual(['nama@sekolah.edu'])
  })

  it('empty state tanpa penugasan memakai pesan ramah', () => {
    const w = mount(UiEmptyState, { props: { title: 'Belum ada penugasan laboratorium' } })
    expect(w.text()).toContain('Belum ada penugasan')
  })
})
