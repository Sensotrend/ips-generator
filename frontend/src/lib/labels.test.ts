import { describe, expect, it } from 'vitest'
import { documentDateFact, extraFact, fact } from '../test-fixtures'
import { factRows, factTables, factTitle } from './labels'

describe('factRows', () => {
  it('labels a medication after the IPS elements and includes the reason when stated', () => {
    const rows = factRows(
      fact({
        kind: 'medication',
        value: {
          medication_text: 'Allopurinol',
          strength_text: '300 mg',
          dose_form_text: null,
          dosage: { text: '1x1' },
          status: 'active',
          effective_start: '',
          effective_end: '',
          reason_text: 'Kihti',
          note: null,
        },
      }),
    )
    expect(rows).toEqual([
      ['Medication', 'Allopurinol 300 mg'],
      ['Dosage', '1x1'],
      ['Status', 'active'],
      ['Reason', 'Kihti'],
    ])
  })

  it('labels a "none known" entry like the IPS element it is coded in, without a scope row', () => {
    const rows = factRows(
      fact({
        kind: 'section_none_known',
        path: 'allergies.statement',
        value: { scope: 'all' },
        source: { quote: 'Allergiat: ei tiedossa', page: 1, locator: 'line 4' },
      }),
    )
    expect(rows).toEqual([['Allergy or intolerance', 'Allergiat: ei tiedossa']])
  })

  it('shows the active status FHIR will use when an allergy does not state one', () => {
    const rows = factRows(fact())
    expect(rows).toContainEqual(['Clinical status', 'active'])
    expect(rows).toContainEqual(['Reaction', 'ihottuma'])
    expect(rows[0]).toEqual(['Allergy or intolerance', 'Sulfa-antibiootit'])
  })
})

describe('factTables', () => {
  it('makes the labels the columns and each fact a row', () => {
    const second = fact({
      path: 'allergies.items[1]',
      value: { ...fact().value, substance_text: 'Pähkinä', category: 'food', reactions: [] },
    })
    const [table] = factTables([fact(), second])
    expect(table.columns.slice(0, 2)).toEqual(['Allergy or intolerance', 'Category'])
    expect(table.rows.map((row) => row.cells[0])).toEqual(['Sulfa-antibiootit', 'Pähkinä'])
    // A fact without a value for a column gets a dash.
    expect(table.rows[1].cells[table.columns.indexOf('Reaction')]).toBe('–')
  })
})

describe('the optional sections', () => {
  const bp = extraFact(
    'vital_sign',
    'vital_signs[0]',
    {
      kind: 'blood_pressure',
      value: '138',
      diastolic: '84',
      unit_text: 'mmHg',
      effective: '2026-10-06',
      note: null,
    },
    'Verenpaine 138/84 mmHg',
  )

  it('titles and tabulates a vital sign with its number, unit and date', () => {
    expect(factTitle(bp)).toBe('blood pressure 138/84 mmHg')
    expect(factRows(bp)).toEqual([
      ['Measurement', 'blood pressure'],
      ['Value', '138/84 mmHg'],
      ['Date', '2026-10-06'],
    ])
  })

  it('shows a pregnancy count (a number in the JSON) and a date', () => {
    const deliveries = extraFact(
      'pregnancy_fact',
      'pregnancy[1]',
      { kind: 'deliveries', status: 'not_stated', date: null, count: 1 },
      'synnytyksiä 1',
    )
    const due = extraFact(
      'pregnancy_fact',
      'pregnancy[0]',
      { kind: 'expected_delivery_date', status: 'not_stated', date: '2027-01-31', count: null },
      'lasketun ajan arvio 31.01.2027',
    )
    expect(factTitle(deliveries)).toBe('number of deliveries: 1')
    expect(factTitle(due)).toBe('expected delivery date: 2027-01-31')
    const status = extraFact(
      'pregnancy_fact',
      'pregnancy[2]',
      { kind: 'status', status: 'pregnant', date: null, count: null },
      'Raskaus todettu',
    )
    expect(factRows(status)).toContainEqual(['Value', 'pregnant'])
  })

  it('describes tobacco, vaccines and a contact person', () => {
    const tobacco = extraFact(
      'social_history',
      'social_history[0]',
      { kind: 'tobacco', tobacco_status: 'former', use_text: 'Lopetettu 2019', date: '2019' },
      'Lopetettu 2019',
    )
    expect(factRows(tobacco)).toEqual([
      ['Topic', 'tobacco'],
      ['Smoking status', 'former smoker'],
      ['As written in the document', 'Lopetettu 2019'],
      ['Date', '2019'],
    ])
    const vaccine = extraFact(
      'immunization',
      'immunizations[0]',
      { vaccine_text: 'MPR-rokote', status: 'not_done', occurrence: null, note: null },
      'MPR-rokote',
    )
    expect(factRows(vaccine)).toEqual([
      ['Vaccine', 'MPR-rokote'],
      ['Status', 'not given'],
    ])
    const contact = extraFact(
      'patient_contact',
      'patient.contacts[0]',
      { name_text: 'Teemu Ahonen', relationship_text: 'puoliso', phone: '040 000 0005' },
      'Teemu',
    )
    expect(factTitle(contact)).toBe('Teemu Ahonen (puoliso)')
    expect(factRows(contact)).toEqual([
      ['Contact person', 'Teemu Ahonen'],
      ['Relationship', 'puoliso'],
      ['Telephone', '040 000 0005'],
    ])
  })

  it('shows the document date and the active status a Problem List condition gets', () => {
    expect(factTitle(documentDateFact())).toBe('2026-10-12')
    expect(factRows(documentDateFact())).toEqual([['Document date', '2026-10-12']])
    const condition = fact({
      path: 'problems.items[0]',
      kind: 'condition',
      value: { condition_text: 'Astma', clinical_status: 'not_stated' },
    })
    expect(factRows(condition)).toContainEqual(['Clinical status', 'active'])
  })
})
