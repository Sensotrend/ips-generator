import { afterEach, describe, expect, it } from 'vitest'
import { extraFact } from '../test-fixtures'
import { editableFields } from './edit'
import { setLocale } from './i18n'
import { factRows, factTitle } from './labels'
import { factSentence, sortByDate } from './sentences'

const hb = extraFact(
  'result',
  'results[0]',
  {
    category: 'laboratory',
    test_text: 'Hb',
    value: '112',
    comparator: 'not_stated',
    value_text: null,
    unit_text: 'g/l',
    effective: '2026-10-05',
    note: null,
  },
  'Hb 112 g/l',
)
const egfr = {
  ...hb,
  path: 'results[1]',
  value: {
    ...hb.value,
    test_text: 'eGFR',
    value: '90',
    comparator: 'gt',
    unit_text: 'ml/min',
    effective: null,
  },
}
const rubella = {
  ...hb,
  path: 'results[2]',
  value: {
    ...hb.value,
    test_text: 'rubella IgG',
    value: null,
    value_text: 'positive',
    unit_text: null,
  },
}
const appendectomy = extraFact(
  'procedure',
  'procedures[0]',
  { procedure_text: 'appendektomi', body_site_text: null, performed: '2008', note: null },
  'appendektomi 2008',
)
const spacer = extraFact(
  'device',
  'devices[0]',
  { device_text: 'Inhalaatiovälikammio', brand_text: 'Volumatic', note: null },
  'Inhalaatiovälikammio (Volumatic)',
)

describe('results, procedures and devices', () => {
  afterEach(() => setLocale('en'))

  it('titles a result with its bound, number and unit, or its text', () => {
    expect(factTitle(hb)).toBe('Hb 112 g/l')
    expect(factTitle(egfr)).toBe('eGFR >90 ml/min')
    expect(factTitle(rubella)).toBe('rubella IgG positive')
    expect(factTitle(appendectomy)).toBe('appendektomi 2008')
    expect(factTitle(spacer)).toBe('Inhalaatiovälikammio Volumatic')
  })

  it('tabulates the elements that end up in the resource', () => {
    expect(factRows(hb)).toEqual([
      ['Test', 'Hb'],
      ['Value', '112 g/l'],
      ['Date', '2026-10-05'],
    ])
    expect(factRows(appendectomy)).toEqual([
      ['Procedure', 'appendektomi'],
      ['Date', '2008'],
    ])
    expect(factRows(spacer)).toEqual([
      ['Device or aid', 'Inhalaatiovälikammio'],
      ['Brand or model', 'Volumatic'],
    ])
  })

  it('words each in plain language, in every language', () => {
    expect(factSentence(hb)).toBe(
      'The document gives this test result for you: Hb 112 g/l, tested 2026-10-05.',
    )
    expect(factSentence(egfr)).toBe('The document gives this test result for you: eGFR >90 ml/min.')
    expect(factSentence(appendectomy)).toBe(
      'The document lists this procedure: appendektomi, done 2008.',
    )
    expect(factSentence(spacer)).toBe(
      'The document says you use this device or aid: Inhalaatiovälikammio Volumatic.',
    )
    setLocale('fi')
    expect(factSentence(hb)).toContain('tutkimustuloksen')
    setLocale('sv')
    expect(factSentence(hb)).toContain('provsvaret')
  })

  it('offers the fields that can be corrected, never the category or the provenance', () => {
    expect(editableFields(hb).map((f) => f.key)).toEqual([
      'test_text',
      'value',
      'comparator',
      'value_text',
      'unit_text',
      'effective',
    ])
    expect(editableFields(hb)[2].options).toEqual(['lt', 'le', 'ge', 'gt', 'not_stated'])
    expect(editableFields(appendectomy).map((f) => f.key)).toEqual([
      'procedure_text',
      'body_site_text',
      'performed',
      'note',
    ])
    expect(editableFields(spacer).map((f) => f.key)).toEqual(['device_text', 'brand_text', 'note'])
  })

  it('sorts results and procedures by their date, newest first', () => {
    const older = {
      ...appendectomy,
      path: 'p-old',
      value: { ...appendectomy.value, performed: '1999' },
    }
    expect(sortByDate([older, appendectomy]).map((f) => f.path)).toEqual(['procedures[0]', 'p-old'])
    const undated = { ...hb, path: 'r-undated', value: { ...hb.value, effective: null } }
    expect(sortByDate([undated, hb]).map((f) => f.path)).toEqual(['results[0]', 'r-undated'])
  })
})
