import { useState } from 'react'
import { ApiError, downloadIps } from '../api/client'
import type { Blocker, ReviewerRole, ValidationSummary } from '../api/types'

interface Props {
  jobId: string
  approved: boolean
  blockers: Blocker[]
  busy: boolean
  error: unknown
  validation: ValidationSummary | null
  onApprove: (role: ReviewerRole) => void
}

function describe(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.code === 'validation_failed')
      return 'The IPS Bundle did not pass validation, so it was not approved.'
    if (error.code === 'version_conflict') return 'The draft changed meanwhile. Reload and retry.'
    return error.message
  }
  return 'Approval failed.'
}

export function ApprovePanel({
  jobId,
  approved,
  blockers,
  busy,
  error,
  validation,
  onApprove,
}: Props) {
  const [role, setRole] = useState<ReviewerRole | null>(null)
  const [downloadError, setDownloadError] = useState(false)

  if (approved) {
    return (
      <section className="approve approved" aria-label="Approval">
        <h2>Approved</h2>
        <p>The IPS is final and attested by the reviewer.</p>
        {validation && (
          <p className="muted">
            Validation: {validation.errors} errors, {validation.warnings} warnings.
          </p>
        )}
        <button
          type="button"
          className="primary"
          onClick={() => {
            setDownloadError(false)
            downloadIps(jobId).catch(() => setDownloadError(true))
          }}
        >
          Download IPS (FHIR JSON)
        </button>
        {downloadError && <p className="note note-warning">Download failed.</p>}
      </section>
    )
  }

  return (
    <section className="approve" aria-label="Approval">
      <h2>Approve</h2>
      {blockers.length > 0 && (
        <ul className="blockers" aria-label="Approval blocked">
          {blockers.map((blocker) => (
            <li key={`${blocker.code}-${blocker.path}`}>{blocker.message}</li>
          ))}
        </ul>
      )}
      <fieldset>
        <legend>I am reviewing as</legend>
        <label>
          <input
            type="radio"
            name="role"
            checked={role === 'patient'}
            onChange={() => setRole('patient')}
          />{' '}
          the patient
        </label>
        <label>
          <input
            type="radio"
            name="role"
            checked={role === 'clinician'}
            onChange={() => setRole('clinician')}
          />{' '}
          a clinician
        </label>
      </fieldset>
      <button
        type="button"
        className="primary"
        disabled={busy || blockers.length > 0 || role === null}
        onClick={() => role && onApprove(role)}
      >
        Approve IPS
      </button>
      {error !== null && error !== undefined && (
        <p className="note note-warning" role="alert">
          {describe(error)}
        </p>
      )}
    </section>
  )
}
