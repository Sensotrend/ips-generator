import { useState } from 'react'
import { ApiError, api } from '../api/client'
import { useJobs } from '../api/hooks'
import type { ReviewerRole } from '../api/types'
import { useT } from '../lib/i18n'

/** Supported inputs (PLAN D-2). Camera capture comes with OCR in Phase 4, so no `capture`. */
export const ACCEPT =
  '.txt,.md,.markdown,.json,.csv,.tsv,.pdf,text/plain,text/markdown,application/json,text/csv,application/pdf'

export function UploadScreen({ role, onJob }: { role: ReviewerRole; onJob: (id: string) => void }) {
  const [file, setFile] = useState<File | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const jobs = useJobs()
  const { t, locale } = useT()

  return (
    <div className="upload">
      <h2>{t(role === 'patient' ? 'upload.title.patient' : 'upload.title.clinician')}</h2>
      {role === 'patient' && <p>{t('upload.intro.patient')}</p>}
      <form
        onSubmit={(event) => {
          event.preventDefault()
          if (!file) return
          setBusy(true)
          setError(null)
          api
            .uploadJob(file)
            .then((job) => onJob(job.id))
            .catch((err: unknown) =>
              setError(err instanceof ApiError ? err.message : t('upload.failed')),
            )
            .finally(() => setBusy(false))
        }}
      >
        <label className="file-picker">
          <span>{t('upload.file')}</span>
          <input
            type="file"
            accept={ACCEPT}
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
          />
        </label>
        <p className="muted">{t('upload.formats')}</p>
        <button type="submit" className="primary" disabled={!file || busy}>
          {busy ? t('upload.busy') : t('upload.submit')}
        </button>
        {error && (
          <p className="note note-warning" role="alert">
            {error}
          </p>
        )}
      </form>
      {jobs.data && jobs.data.length > 0 && (
        <section className="recent" aria-label={t('upload.recent.label')}>
          <h2>{t('upload.recent')}</h2>
          <ul>
            {jobs.data.map((job) => (
              <li key={job.id}>
                <a href={`#/jobs/${job.id}`}>
                  {new Date(job.created_at).toLocaleString(locale)} · {job.media_type} ·{' '}
                  {t(`status.${job.status}`)}
                </a>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}
