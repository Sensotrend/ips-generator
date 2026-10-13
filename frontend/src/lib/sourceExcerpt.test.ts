import { describe, expect, it } from 'vitest'
import type { Source } from '../api/types'
import { sourceExcerpt } from './sourceExcerpt'

const base: Source = {
  media_type: 'application/json',
  page_count: 1,
  pages_without_text: [],
  original_url: null,
  segments: [],
}

describe('sourceExcerpt', () => {
  it('names the line of a text document', () => {
    const excerpt = sourceExcerpt(undefined, { quote: 'x', page: 1, locator: 'line 3' })
    expect(excerpt).toEqual({ location: 'line 3', record: null })
  })

  it('shows the whole JSON object that holds the value', () => {
    const source = {
      ...base,
      segments: [
        { page: 1, locator: '$.meds[0].name', text: 'name: A' },
        { page: 1, locator: '$.meds[1].name', text: 'name: Burana' },
        { page: 1, locator: '$.meds[1].dose', text: 'dose: 600 mg' },
      ],
    }
    const excerpt = sourceExcerpt(source, { quote: 'Burana', page: 1, locator: '$.meds[1].name' })
    expect(excerpt.location).toBe('$.meds[1]')
    expect(excerpt.record).toEqual([
      { text: 'name: Burana', focus: true },
      { text: 'dose: 600 mg', focus: false },
    ])
  })

  it('shows a CSV row as column: value lines', () => {
    const source = {
      ...base,
      segments: [{ page: 1, locator: 'row 2', text: 'drug: Burana | dose: 600 mg' }],
    }
    const excerpt = sourceExcerpt(source, { quote: 'drug: Burana', page: 1, locator: 'row 2' })
    expect(excerpt.location).toBe('row 2')
    expect(excerpt.record).toEqual([
      { text: 'drug: Burana', focus: true },
      { text: 'dose: 600 mg', focus: false },
    ])
  })

  it('falls back to the page for PDFs', () => {
    expect(sourceExcerpt(undefined, { quote: 'x', page: 2, locator: null }).location).toBe('p. 2')
  })
})
