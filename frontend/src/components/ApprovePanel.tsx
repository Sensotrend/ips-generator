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
  role: ReviewerRole
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
  role,
  onApprove,
}: Props) {
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
      <p className="muted">
        {role === 'patient'
          ? 'By approving, you confirm as the patient that this summary is correct.'
          : 'By approving, you attest this summary as a clinician.'}
      </p>
      <button
        type="button"
        className="primary"
        disabled={busy || blockers.length > 0}
        onClick={() => onApprove(role)}
      >
        {role === 'patient' ? 'Approve my summary' : 'Approve IPS'}
      </button>
      {error !== null && error !== undefined && (
        <p className="note note-warning" role="alert">
          {describe(error)}
        </p>
      )}
    </section>
  )
}
