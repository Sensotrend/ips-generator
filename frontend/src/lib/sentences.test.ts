import { describe, expect, it } from 'vitest'
import { fact } from '../test-fixtures'
import { isCompleted, sortByDate } from './sentences'

const medication = (name: string, value: Record<string, string>) =>
  fact({ path: name, kind: 'medication', value: { substance_text: name, ...value } })

describe('sortByDate', () => {
  it('puts current items first, newest start first, completed ones after, undated last', () => {
    const items = [
      medication('stopped-new', { status: 'stopped', effective_start: '2024-01-01' }),
      medication('undated', { status: 'active' }),
      medication('active-old', { status: 'active', effective_start: '2019' }),
      medication('active-new', { status: 'active', effective_start: '2023-05' }),
      medication('ended', { status: 'not_stated', effective_start: '2020', effective_end: '2021' }),
    ]
    expect(sortByDate(items).map((f) => f.path)).toEqual([
      'active-new',
      'active-old',
      'undated',
      'stopped-new',
      'ended',
    ])
  })

  it('keeps the document order when nothing has a date', () => {
    const items = ['a', 'b', 'c'].map((n) => medication(n, { status: 'active' }))
    expect(sortByDate(items).map((f) => f.path)).toEqual(['a', 'b', 'c'])
  })

  it('treats resolved conditions and inactive allergies as completed', () => {
    expect(isCompleted(fact({ kind: 'condition', value: { clinical_status: 'resolved' } }))).toBe(
      true,
    )
    expect(isCompleted(fact({ kind: 'condition', value: { clinical_status: 'active' } }))).toBe(
      false,
    )
    expect(isCompleted(fact({ value: { clinical_status: 'inactive' } }))).toBe(true)
  })
})
