import { useEffect, useMemo, useRef, useState } from 'react'
import type { Segment, Source, SourceRef } from '../api/types'
import { locateQuote, type PartRange } from '../lib/highlight'

function renderText(text: string, range: PartRange | undefined) {
  if (!range) return text
  return (
    <>
      {text.slice(0, range.start)}
      <mark>{text.slice(range.start, range.end)}</mark>
      {text.slice(range.end)}
    </>
  )
}

/** Plaintext / CSV / JSON source: one row per segment, the quote highlighted. */
export function TextSourceViewer({ source, focus }: { source: Source; focus: SourceRef | null }) {
  const pages = useMemo(() => {
    const byPage = new Map<number, Segment[]>()
    for (const segment of source.segments) {
      byPage.set(segment.page, [...(byPage.get(segment.page) ?? []), segment])
    }
    return byPage
  }, [source])
  const pageNumbers = [...pages.keys()].sort((a, b) => a - b)
  const [page, setPage] = useState(focus?.page ?? pageNumbers[0] ?? 1)
  const [lastFocus, setLastFocus] = useState(focus)
  if (focus !== lastFocus) {
    // Follow the selected fact to its page (state derived from props, no effect needed).
    setLastFocus(focus)
    if (focus) setPage(focus.page)
  }
  const segments = pages.get(page) ?? []
  const preferPart = focus ? segments.findIndex((s) => s.locator === focus.locator) : -1
  const ranges =
    focus && focus.page === page
      ? locateQuote(
          segments.map((s) => s.text),
          focus.quote,
          { preferPart: Math.max(preferPart, 0) },
        )
      : null
  const container = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const mark = container.current?.querySelector('mark, .seg-focus')
    if (mark && 'scrollIntoView' in mark)
      mark.scrollIntoView({ block: 'center', behavior: 'smooth' })
  }, [focus, page])

  return (
    <div className="source-text" ref={container}>
      {pageNumbers.length > 1 && (
        <nav className="pager" aria-label="Pages">
          <button type="button" disabled={page <= pageNumbers[0]} onClick={() => setPage(page - 1)}>
            Previous
          </button>
          <span>
            Page {page} / {pageNumbers[pageNumbers.length - 1]}
          </span>
          <button
            type="button"
            disabled={page >= pageNumbers[pageNumbers.length - 1]}
            onClick={() => setPage(page + 1)}
          >
            Next
          </button>
        </nav>
      )}
      {focus && focus.page === page && !ranges && (
        <p className="note note-warning">The quote was not found verbatim on this page.</p>
      )}
      <ol className="segments">
        {segments.map((segment, index) => {
          const range = ranges?.find((r) => r.part === index)
          const isFocus = !ranges && focus?.page === page && index === preferPart
          return (
            <li key={`${segment.locator}-${index}`} className={isFocus ? 'seg-focus' : undefined}>
              <span className="seg-loc">{segment.locator ?? `page ${segment.page}`}</span>
              <span className="seg-text">{renderText(segment.text, range)}</span>
            </li>
          )
        })}
      </ol>
    </div>
  )
}
