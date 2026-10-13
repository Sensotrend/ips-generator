import { useEffect, useState } from 'react'
import { useJob, useJobEvents } from './api/hooks'
import { JobProgress } from './components/JobProgress'
import { ReviewScreen } from './components/ReviewScreen'
import { UploadScreen } from './components/UploadScreen'

/** Hash routes: `#/` (upload) and `#/jobs/<id>`. The job id is not PHI. */
function parseRoute(hash: string): { jobId: string | null } {
  const match = /^#\/jobs\/([0-9a-f-]{36})$/i.exec(hash)
  return { jobId: match ? match[1] : null }
}

function useHashRoute() {
  const [hash, setHash] = useState(window.location.hash)
  useEffect(() => {
    const onChange = () => setHash(window.location.hash)
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])
  return parseRoute(hash)
}

function JobScreen({ jobId }: { jobId: string }) {
  const job = useJob(jobId)
  const running = job.data?.status === 'queued' || job.data?.status === 'running'
  const events = useJobEvents(jobId, running)
  if (job.isPending) return <p className="muted">Loading…</p>
  if (job.isError) return <p className="note note-warning">This job was not found.</p>
  const data = job.data
  if (data.status === 'failed') {
    return (
      <div className="failed" role="alert">
        <h2>Processing failed</h2>
        <p>{data.error?.message}</p>
        <p className="muted">
          Step: {data.error?.step ?? 'unknown'} · code: {data.error?.code}
        </p>
        <a href="#/">Upload another document</a>
      </div>
    )
  }
  if (running) {
    return (
      <div>
        <h2>Processing…</h2>
        <JobProgress events={events} />
      </div>
    )
  }
  return <ReviewScreen jobId={jobId} />
}

function App() {
  const { jobId } = useHashRoute()
  return (
    <div className="app">
      <header className="app-header">
        <a href="#/" className="brand">
          IPS Generator
        </a>
        <span className="muted">Synthetic data only</span>
      </header>
      <main>
        <h1 className="visually-hidden">IPS Generator</h1>
        {jobId ? (
          <JobScreen key={jobId} jobId={jobId} />
        ) : (
          <UploadScreen onJob={(id) => (window.location.hash = `#/jobs/${id}`)} />
        )}
      </main>
    </div>
  )
}

export default App
