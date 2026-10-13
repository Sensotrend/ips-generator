import { describe, expect, it } from 'vitest'
import { locateQuote } from './highlight'

describe('locateQuote', () => {
  const lines = ['Potilas: TESTINEN, Aino', 'Lääkitys:', 'Burana 600 mg 1x3', 'Burana 600 mg']

  it('finds an exact quote in its segment', () => {
    expect(locateQuote(lines, 'Burana 600 mg 1x3', { preferPart: 2 })).toEqual([
      { part: 2, start: 0, end: 17 },
    ])
  })

  it('prefers the stated segment when the quote occurs twice', () => {
    expect(locateQuote(lines, 'Burana 600 mg', { preferPart: 3 })).toEqual([
      { part: 3, start: 0, end: 13 },
    ])
  })

  it('spans segments joined by newlines', () => {
    expect(locateQuote(lines, 'Lääkitys:\nBurana', { preferPart: 1 })).toEqual([
      { part: 1, start: 0, end: 9 },
      { part: 2, start: 0, end: 6 },
    ])
  })

  it('falls back to whitespace and case insensitive matching', () => {
    expect(locateQuote(lines, 'burana  600mg 1X3')).toEqual([{ part: 2, start: 0, end: 17 }])
  })

  it('matches pdf.js text items joined without separator', () => {
    const items = ['Allergies: ', 'Penicil', 'lin (rash)']
    expect(locateQuote(items, 'Penicillin', { separator: '' })).toEqual([
      { part: 1, start: 0, end: 7 },
      { part: 2, start: 0, end: 3 },
    ])
  })

  it('returns null when the quote is absent', () => {
    expect(locateQuote(lines, 'Ibuprofen')).toBeNull()
    expect(locateQuote(lines, '   ')).toBeNull()
  })
})
