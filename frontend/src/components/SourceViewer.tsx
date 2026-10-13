import { lazy, Suspense } from 'react'
import { useSource } from '../api/hooks'
import type { SourceRef } from '../api/types'
import { useT } from '../lib/i18n'
import { TextSourceViewer } from './TextSourceViewer'

// pdf.js is large: load it only when a PDF is reviewed.
const PdfSourceViewer = lazy(() => import('./PdfSourceViewer'))

export function SourceViewer({ jobId, focus }: { jobId: string; focus: SourceRef | null }) {
  const source = useSource(jobId, true)
  const { t } = useT()
  if (source.isPending) return <p className="muted">{t('source.loading')}</p>
  if (source.isError) return <p className="note note-warning">{t('source.loadFailed')}</p>
  const data = source.data
  return (
    <section className="source" aria-label={t('source.label')}>
      <header className="source-head">
        <h2>{t('source.title')}</h2>
        {focus ? (
          <span className="muted">
            {t('fact.page', { page: focus.page })}
            {focus.locator ? `, ${focus.locator}` : ''}
          </span>
        ) : (
          <span className="muted">{t('source.select')}</span>
        )}
      </header>
      {data.pages_without_text.length > 0 && (
        <p className="note note-warning">
          {t('source.noTextLayer', { pages: data.pages_without_text.join(', ') })}
        </p>
      )}
      {data.original_url ? (
        <Suspense fallback={<p className="muted">{t('source.loadingPdfViewer')}</p>}>
          <PdfSourceViewer url={data.original_url} pageCount={data.page_count} focus={focus} />
        </Suspense>
      ) : (
        <TextSourceViewer source={data} focus={focus} />
      )}
    </section>
  )
}
