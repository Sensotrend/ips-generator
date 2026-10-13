import type { Source, SourceRef } from '../api/types'
import { translate } from './i18n'

export interface Excerpt {
  /** Where in the document: "line 3", "row 2", a JSON path or "p. 1". */
  location: string
  /** Surrounding record (a JSON object or a CSV row), one entry per line; null for plain text/PDF. */
  record: { text: string; focus: boolean }[] | null
}

const MAX_RECORD_LINES = 30

/** JSON path of the object that holds the leaf: `$.a.b[2].c` → `$.a.b[2]`. */
const parentPath = (locator: string): string => locator.replace(/(\.[^.[\]]+|\[\d+\])$/, '')

/**
 * Describes where a fact came from. Plain text: the line number. JSON: the whole object holding
 * the value (the source has one segment per leaf). CSV: the whole row as `column: value` lines.
 * PDF: the page.
 */
export function sourceExcerpt(source: Source | undefined, ref: SourceRef): Excerpt {
  const locator = ref.locator
  if (!locator) return { location: translate('fact.page', { page: ref.page }), record: null }
  const line = /^line (\d+)$/.exec(locator)
  if (line) return { location: translate('source.line', { n: line[1] }), record: null }
  const row = /^row (\d+)$/.exec(locator)
  if (row) {
    const segment = source?.segments.find((s) => s.page === ref.page && s.locator === locator)
    return {
      location: translate('source.row', { n: row[1] }),
      record: segment
        ? segment.text.split(' | ').map((text) => ({ text, focus: ref.quote.includes(text) }))
        : null,
    }
  }
  if (locator.startsWith('$') && source) {
    const parent = parentPath(locator)
    const members = source.segments.filter(
      (s) =>
        s.page === ref.page &&
        s.locator !== null &&
        (s.locator === locator ||
          s.locator.startsWith(`${parent}.`) ||
          s.locator.startsWith(`${parent}[`)),
    )
    return {
      location: parent,
      record: members
        .slice(0, MAX_RECORD_LINES)
        .map((s) => ({ text: s.text, focus: s.locator === locator })),
    }
  }
  return { location: locator, record: null }
}
