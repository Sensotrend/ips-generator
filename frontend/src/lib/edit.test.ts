import { describe, expect, it } from 'vitest'
import { extraFact } from '../test-fixtures'
import { editableFields, getIn, setIn } from './edit'

describe('editing the optional sections', () => {
  const vital = extraFact(
    'vital_sign',
    'vital_signs[0]',
    { kind: 'weight', value: '88.5', diastolic: null, unit_text: 'kg', effective: '' },
    'paino 88,5 kg',
  )

  it('offers the fields that can be corrected, never the kind or the provenance', () => {
    expect(editableFields(vital).map((f) => f.key)).toEqual([
      'value',
      'diastolic',
      'unit_text',
      'effective',
    ])
    const pregnancy = extraFact(
      'pregnancy_fact',
      'pregnancy[0]',
      { kind: 'deliveries', status: 'not_stated', date: null, count: 2 },
      'synnytyksiä 2',
    )
    expect(editableFields(pregnancy).map((f) => f.key)).toEqual(['status', 'date', 'count'])
    expect(editableFields(pregnancy)[0].options).toEqual(['pregnant', 'not_pregnant', 'not_stated'])
    const tobacco = extraFact(
      'social_history',
      'social_history[0]',
      { kind: 'tobacco', tobacco_status: 'never', use_text: 'x', date: null },
      'x',
    )
    expect(editableFields(tobacco)[1].options).toContain('non_smoker')
  })

  it('reads a numeric value (a count) as text and writes the edit back as text', () => {
    const pregnancy = extraFact(
      'pregnancy_fact',
      'pregnancy[0]',
      { kind: 'deliveries', status: 'not_stated', date: null, count: 2 },
      'synnytyksiä 2',
    )
    expect(getIn(pregnancy.value, 'count')).toBe('2')
    expect(setIn(pregnancy.value, 'count', '3').count).toBe('3')
    expect(getIn(vital.value, 'value')).toBe('88.5')
    expect(getIn(vital.value, 'diastolic')).toBe('')
  })
})
