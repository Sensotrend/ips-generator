import { describe, expect, it } from 'vitest'
import { fact } from '../test-fixtures'
import { factRows, factTables } from './labels'

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
