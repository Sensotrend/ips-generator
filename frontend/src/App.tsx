import { useEffect, useState } from 'react'
import { useJob, useJobEvents } from './api/hooks'
import type { ReviewerRole } from './api/types'
import { JobProgress } from './components/JobProgress'
import { PatientReview } from './components/PatientReview'
import { ReviewScreen } from './components/ReviewScreen'
import { RoleScreen } from './components/RoleScreen'
import { UploadScreen } from './components/UploadScreen'
import { LOCALE_NAMES, LOCALES, setLocale, useT, type Locale } from './lib/i18n'
import { useRole } from './lib/role'

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

function JobScreen({ jobId, role }: { jobId: string; role: ReviewerRole }) {
  const { t } = useT()
  const job = useJob(jobId)
  const running = job.data?.status === 'queued' || job.data?.status === 'running'
  const events = useJobEvents(jobId, running)
  if (job.isPending) return <p className="muted">{t('job.loading')}</p>
  if (job.isError) return <p className="note note-warning">{t('job.notFound')}</p>
  const data = job.data
  if (data.status === 'failed') {
    return (
      <div className="failed" role="alert">
        <h2>{t('job.failed')}</h2>
        <p>{data.error?.message}</p>
        <p className="muted">
          {t('job.failed.step', {
            step: data.error?.step ?? t('job.failed.unknownStep'),
            code: data.error?.code ?? '',
          })}
        </p>
        <a href="#/">{t('job.failed.another')}</a>
      </div>
    )
  }
  if (running) {
    return (
      <div>
        <h2>{t('job.processing')}</h2>
        <JobProgress events={events} />
      </div>
    )
  }
  return role === 'patient' ? (
    <PatientReview jobId={jobId} />
  ) : (
    <ReviewScreen jobId={jobId} role={role} />
  )
}

function App() {
  const { jobId } = useHashRoute()
  const [role, setRole] = useRole()
  const { t, locale } = useT()
  return (
    <div className={`app${role ? ` role-${role}` : ' role-none'}`}>
      <header className="app-header">
        <a href="#/" className="brand">
          IPS Generator
        </a>
        <span className="header-right">
          {role && (
            <>
              <span className="role-chip">
                {t(role === 'patient' ? 'role.patient' : 'role.clinician')}
              </span>
              <button type="button" className="link-button" onClick={() => setRole(null)}>
                {t('app.change')}
              </button>
            </>
          )}
          <select
            className="language-select"
            aria-label={t('language.switch')}
            value={locale}
            onChange={(event) => setLocale(event.target.value as Locale)}
          >
            {LOCALES.map((code) => (
              <option key={code} value={code} lang={code}>
                {LOCALE_NAMES[code]}
              </option>
            ))}
          </select>
          <span className="muted">{t('app.syntheticOnly')}</span>
        </span>
      </header>
      <main>
        <h1 className="visually-hidden">IPS Generator</h1>
        {!role ? (
          <RoleScreen onChoose={setRole} />
        ) : jobId ? (
          <JobScreen key={jobId} jobId={jobId} role={role} />
        ) : (
          <UploadScreen role={role} onJob={(id) => (window.location.hash = `#/jobs/${id}`)} />
        )}
      </main>
    </div>
  )
}

export default App
