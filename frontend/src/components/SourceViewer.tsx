import { lazy, Suspense } from 'react'
import { useSource } from '../api/hooks'
import type { SourceRef } from '../api/types'
import { TextSourceViewer } from './TextSourceViewer'

// pdf.js is large: load it only when a PDF is reviewed.
const PdfSourceViewer = lazy(() => import('./PdfSourceViewer'))

export function SourceViewer({ jobId, focus }: { jobId: string; focus: SourceRef | null }) {
  const source = useSource(jobId, true)
  if (source.isPending) return <p className="muted">Loading source…</p>
  if (source.isError) return <p className="note note-warning">The source could not be loaded.</p>
  const data = source.data
  return (
    <section className="source" aria-label="Source document">
      <header className="source-head">
        <h2>Source</h2>
        {focus ? (
          <span className="muted">
            p. {focus.page}
            {focus.locator ? `, ${focus.locator}` : ''}
          </span>
        ) : (
          <span className="muted">Select a fact to see its quote</span>
        )}
      </header>
      {data.pages_without_text.length > 0 && (
        <p className="note note-warning">
          Pages without a text layer (not extracted): {data.pages_without_text.join(', ')}
        </p>
      )}
      {data.original_url ? (
        <Suspense fallback={<p className="muted">Loading PDF viewer…</p>}>
          <PdfSourceViewer url={data.original_url} pageCount={data.page_count} focus={focus} />
        </Suspense>
      ) : (
        <TextSourceViewer source={data} focus={focus} />
      )}
    </section>
  )
}
