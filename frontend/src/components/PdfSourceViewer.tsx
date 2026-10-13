import { getDocument, GlobalWorkerOptions, TextLayer, type PDFDocumentProxy } from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import { useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import type { SourceRef } from '../api/types'
import { locateQuote } from '../lib/highlight'
import { useT } from '../lib/i18n'

GlobalWorkerOptions.workerSrc = workerUrl

interface Props {
  url: string
  pageCount: number
  focus: SourceRef | null
}

/**
 * PDF source: the page rendered with pdf.js plus its text layer, where the quote's text items
 * are highlighted. The PDF is fetched into memory only (no caching; the API is NetworkOnly).
 */
export default function PdfSourceViewer({ url, pageCount, focus }: Props) {
  const { t } = useT()
  const [pdf, setPdf] = useState<PDFDocumentProxy | null>(null)
  const [error, setError] = useState<'pdf' | 'page' | null>(null)
  const [page, setPage] = useState(focus?.page ?? 1)
  const [lastFocus, setLastFocus] = useState(focus)
  const [found, setFound] = useState<boolean | null>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const layerRef = useRef<HTMLDivElement>(null)
  const wrapRef = useRef<HTMLDivElement>(null)

  if (focus !== lastFocus) {
    setLastFocus(focus)
    if (focus) setPage(focus.page)
  }

  useEffect(() => {
    let cancelled = false
    let task: ReturnType<typeof getDocument> | null = null
    api
      .getBinary(url)
      .then((data) => {
        task = getDocument({ data })
        return task.promise
      })
      .then((doc) => {
        if (!cancelled) setPdf(doc)
      })
      .catch(() => !cancelled && setError('pdf'))
    return () => {
      cancelled = true
      void (task as ReturnType<typeof getDocument> | null)?.destroy()
    }
  }, [url])

  useEffect(() => {
    if (!pdf || !canvasRef.current || !layerRef.current || !wrapRef.current) return
    let cancelled = false
    const canvas = canvasRef.current
    const layer = layerRef.current
    const width = wrapRef.current.clientWidth || 600
    let textLayer: TextLayer | null = null
    void (async () => {
      const pdfPage = await pdf.getPage(page)
      const base = pdfPage.getViewport({ scale: 1 })
      const viewport = pdfPage.getViewport({ scale: width / base.width })
      const ratio = window.devicePixelRatio || 1
      canvas.width = Math.floor(viewport.width * ratio)
      canvas.height = Math.floor(viewport.height * ratio)
      canvas.style.width = `${viewport.width}px`
      canvas.style.height = `${viewport.height}px`
      await pdfPage.render({
        canvas,
        viewport,
        transform: ratio !== 1 ? [ratio, 0, 0, ratio, 0, 0] : undefined,
      }).promise
      if (cancelled) return
      layer.replaceChildren()
      layer.style.setProperty('--scale-factor', String(viewport.scale))
      layer.style.setProperty('--total-scale-factor', String(viewport.scale))
      textLayer = new TextLayer({
        textContentSource: await pdfPage.getTextContent(),
        container: layer,
        viewport,
      })
      await textLayer.render()
      if (cancelled) return
      if (focus && focus.page === page) {
        const ranges = locateQuote(textLayer.textContentItemsStr, focus.quote, { separator: '' })
        setFound(ranges !== null)
        for (const range of ranges ?? []) textLayer.textDivs[range.part]?.classList.add('hl')
        layer.querySelector('.hl')?.scrollIntoView?.({ block: 'center', behavior: 'smooth' })
      } else {
        setFound(null)
      }
    })().catch(() => !cancelled && setError('page'))
    return () => {
      cancelled = true
      textLayer?.cancel()
    }
  }, [pdf, page, focus])

  if (error)
    return (
      <p className="note note-warning">
        {t(error === 'pdf' ? 'source.pdfFailed' : 'source.pageFailed')}
      </p>
    )
  return (
    <div className="source-pdf">
      <nav className="pager" aria-label={t('source.pages')}>
        <button type="button" disabled={page <= 1} onClick={() => setPage(page - 1)}>
          {t('source.previous')}
        </button>
        <span>{t('source.page', { page, total: pdf?.numPages ?? pageCount })}</span>
        <button
          type="button"
          disabled={page >= (pdf?.numPages ?? pageCount)}
          onClick={() => setPage(page + 1)}
        >
          {t('source.next')}
        </button>
      </nav>
      {found === false && <p className="note note-warning">{t('source.notHighlighted')}</p>}
      <div className="pdf-page" ref={wrapRef}>
        <canvas ref={canvasRef} />
        <div className="textLayer" ref={layerRef} />
      </div>
      {!pdf && <p className="muted">{t('source.loadingPdf')}</p>}
    </div>
  )
}
