import { useState } from 'react'
import { ApiError, api } from '../api/client'
import { useJobs } from '../api/hooks'

/** Supported inputs (PLAN D-2). Camera capture comes with OCR in Phase 4, so no `capture`. */
export const ACCEPT =
  '.txt,.md,.markdown,.json,.csv,.tsv,.pdf,text/plain,text/markdown,application/json,text/csv,application/pdf'

export function UploadScreen({ onJob }: { onJob: (id: string) => void }) {
  const [file, setFile] = useState<File | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const jobs = useJobs()

  return (
    <div className="upload">
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
              setError(err instanceof ApiError ? err.message : 'Upload failed.'),
            )
            .finally(() => setBusy(false))
        }}
      >
        <label className="file-picker">
          <span>Healthcare document</span>
          <input
            type="file"
            accept={ACCEPT}
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
          />
        </label>
        <p className="muted">
          Plain text, Markdown, JSON, CSV or a PDF with a text layer. Scans and photos are not
          supported yet.
        </p>
        <button type="submit" className="primary" disabled={!file || busy}>
          {busy ? 'Uploading…' : 'Upload and extract'}
        </button>
        {error && (
          <p className="note note-warning" role="alert">
            {error}
          </p>
        )}
      </form>
      {jobs.data && jobs.data.length > 0 && (
        <section className="recent" aria-label="Recent jobs">
          <h2>Recent</h2>
          <ul>
            {jobs.data.map((job) => (
              <li key={job.id}>
                <a href={`#/jobs/${job.id}`}>
                  {new Date(job.created_at).toLocaleString()} · {job.media_type} · {job.status}
                </a>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}
