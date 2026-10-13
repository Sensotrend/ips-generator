/**
 * Locating a fact's `source_quote` in the source text for highlighting.
 *
 * The text is given as parts (segments of a page, or pdf.js text items) joined by `separator`.
 * Matching ladder, like the backend grounding: exact (starting at the preferred part, then
 * anywhere), then whitespace- and case-insensitive. Returns the character ranges per part.
 */

export interface PartRange {
  part: number
  start: number
  end: number
}

interface Options {
  /** Joiner between parts: '\n' for segments (as the backend joins page text), '' for pdf.js. */
  separator?: string
  /** Index of the part where the quote is expected to start (its segment). */
  preferPart?: number
}

function starts(parts: string[], separator: string): number[] {
  const offsets: number[] = []
  let position = 0
  for (const part of parts) {
    offsets.push(position)
    position += part.length + separator.length
  }
  return offsets
}

function toRanges(parts: string[], offsets: number[], start: number, end: number): PartRange[] {
  const ranges: PartRange[] = []
  parts.forEach((part, index) => {
    const partStart = offsets[index]
    const partEnd = partStart + part.length
    const s = Math.max(start, partStart)
    const e = Math.min(end, partEnd)
    if (s < e) ranges.push({ part: index, start: s - partStart, end: e - partStart })
  })
  return ranges
}

function compact(text: string): { chars: string; map: number[] } {
  let chars = ''
  const map: number[] = []
  for (let i = 0; i < text.length; i++) {
    const c = text[i]
    if (/\s/.test(c)) continue
    chars += c.toLowerCase()[0]
    map.push(i)
  }
  return { chars, map }
}

export function locateQuote(
  parts: string[],
  quote: string,
  { separator = '\n', preferPart = 0 }: Options = {},
): PartRange[] | null {
  const needle = quote.trim()
  if (!needle || parts.length === 0) return null
  const joined = parts.join(separator)
  const offsets = starts(parts, separator)
  const from = offsets[Math.min(Math.max(preferPart, 0), parts.length - 1)] ?? 0

  let index = joined.indexOf(needle, from)
  if (index < 0) index = joined.indexOf(needle)
  if (index >= 0) return toRanges(parts, offsets, index, index + needle.length)

  const hay = compact(joined)
  const want = compact(needle).chars
  if (!want) return null
  const compactFrom = hay.map.findIndex((position) => position >= from)
  let hit = compactFrom >= 0 ? hay.chars.indexOf(want, compactFrom) : -1
  if (hit < 0) hit = hay.chars.indexOf(want)
  if (hit < 0) return null
  const start = hay.map[hit]
  const end = hay.map[hit + want.length - 1] + 1
  return toRanges(parts, offsets, start, end)
}
