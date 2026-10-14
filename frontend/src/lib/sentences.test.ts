import { describe, expect, it } from 'vitest'
import { draftWithExtraSections, extraFact, fact } from '../test-fixtures'
import { factSentence, isCompleted, reviewGroups, sortByDate } from './sentences'

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

describe('the optional sections', () => {
  it('words a vital sign, tobacco use, a vaccination and a contact person', () => {
    const [bp] = draftWithExtraSections().sections.find((x) => x.key === 'vital_signs')!.items
    expect(factSentence(bp)).toBe(
      'The document gives this measurement for you: blood pressure 138/84 mmHg, measured 2026-10-06.',
    )
    const tobacco = extraFact(
      'social_history',
      'social_history[0]',
      { kind: 'tobacco', tobacco_status: 'non_smoker', use_text: 'Ei tupakoi', date: null },
      'Ei tupakoi',
    )
    expect(factSentence(tobacco)).toBe(
      'The document says this about your tobacco use: “Ei tupakoi”.',
    )
    const alcohol = { ...tobacco, value: { ...tobacco.value, kind: 'alcohol' } }
    expect(factSentence(alcohol)).toContain('alcohol use')
    const vaccine = extraFact(
      'immunization',
      'immunizations[0]',
      { vaccine_text: 'MPR-rokote', status: 'completed', occurrence: '1996', note: null },
      'MPR-rokote 1996',
    )
    expect(factSentence(vaccine)).toBe('The document lists the vaccination MPR-rokote, given 1996.')
    const notGiven = {
      ...vaccine,
      value: { ...vaccine.value, status: 'not_done', occurrence: null },
    }
    expect(factSentence(notGiven)).toBe(
      'The document lists the vaccination MPR-rokote (not given).',
    )
  })

  it('puts the contact person with the patient facts and the sections in IPS order', () => {
    const groups = reviewGroups(draftWithExtraSections())
    expect(groups.map((g) => g.key)).toEqual([
      'patient',
      'allergies',
      'medications',
      'immunizations',
      'pregnancy',
      'social_history',
      'vital_signs',
    ])
    expect(groups[0].facts.map((f) => f.kind)).toContain('patient_contact')
    expect(groups[0].facts.map((f) => f.kind).indexOf('patient_contact')).toBeGreaterThan(0)
  })

  it('sorts vaccinations and measurements by their date, newest first', () => {
    const at = (path: string, occurrence: string) =>
      extraFact(
        'immunization',
        path,
        { vaccine_text: 'x', status: 'completed', occurrence, note: null },
        'x',
      )
    expect(sortByDate([at('a', '1996'), at('b', '2023'), at('c', '')]).map((f) => f.path)).toEqual([
      'b',
      'a',
      'c',
    ])
  })
})
