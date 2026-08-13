import { afterEach, describe, expect, it } from 'vitest'
import { divergingHeatColor } from './heatColor'

afterEach(() => {
  document.documentElement.style.removeProperty('--critical')
  document.documentElement.style.removeProperty('--good')
  document.documentElement.style.removeProperty('--border-strong')
})

describe('divergingHeatColor', () => {
  it('returns the neutral color for null/zero percent', () => {
    document.documentElement.style.setProperty('--border-strong', '#8b8f99')
    expect(divergingHeatColor(null)).toBe('rgb(139, 143, 153)')
    expect(divergingHeatColor(0)).toBe('rgb(139, 143, 153)')
  })

  it('moves toward --good for positive percent', () => {
    document.documentElement.style.setProperty('--good', '#147a4a')
    document.documentElement.style.setProperty('--border-strong', '#8b8f99')
    expect(divergingHeatColor(4, 4)).toBe('rgb(20, 122, 74)')
  })

  it('moves toward --critical for negative percent', () => {
    document.documentElement.style.setProperty('--critical', '#c0392b')
    document.documentElement.style.setProperty('--border-strong', '#8b8f99')
    expect(divergingHeatColor(-4, 4)).toBe('rgb(192, 57, 43)')
  })

  it('clamps beyond the cap instead of overshooting the target color', () => {
    document.documentElement.style.setProperty('--good', '#147a4a')
    document.documentElement.style.setProperty('--border-strong', '#8b8f99')
    expect(divergingHeatColor(100, 4)).toBe(divergingHeatColor(4, 4))
  })
})
