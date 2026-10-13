import { useState } from 'react'
import { ApiError, downloadIps } from '../api/client'
import type { Blocker, ReviewerRole, ValidationSummary } from '../api/types'
import { translate, useT } from '../lib/i18n'

interface Props {
  jobId: string
  approved: boolean
  blockers: Blocker[]
  busy: boolean
  error: unknown
  validation: ValidationSummary | null
  role: ReviewerRole
  onApprove: (role: ReviewerRole) => void
  /** Shows the page that can resolve the blocker; no link when omitted. */
  onShowBlocker?: (blocker: Blocker) => void
}

function describe(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.code === 'validation_failed') return translate('approve.error.validation')
    if (error.code === 'version_conflict') return translate('approve.error.conflict')
    return error.message
  }
  return translate('approve.error.generic')
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
  onShowBlocker,
}: Props) {
  const { t } = useT()
  const [downloadError, setDownloadError] = useState(false)

  if (approved) {
    return (
      <section className="approve approved" aria-label={t('approve.label')}>
        <h2>{t('approve.done')}</h2>
        <p>{t('approve.done.text')}</p>
        {validation && (
          <p className="muted">
            {t('approve.validation', { errors: validation.errors, warnings: validation.warnings })}
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
          {t('approve.download')}
        </button>
        {downloadError && <p className="note note-warning">{t('approve.downloadFailed')}</p>}
      </section>
    )
  }

  return (
    <section className="approve" aria-label={t('approve.label')}>
      <h2>{t('approve.title')}</h2>
      {blockers.length > 0 && (
        <ul className="blockers" aria-label={t('approve.blocked')}>
          {blockers.map((blocker) => (
            <li key={`${blocker.code}-${blocker.path}`}>
              {t(`blocker.${blocker.code}`)}
              {onShowBlocker && (
                <>
                  {' '}
                  <button
                    type="button"
                    className="link-button"
                    onClick={() => onShowBlocker(blocker)}
                  >
                    {t('approve.showBlocker')}
                  </button>
                </>
              )}
            </li>
          ))}
        </ul>
      )}
      <p className="muted">
        {t(role === 'patient' ? 'approve.note.patient' : 'approve.note.clinician')}
      </p>
      <button
        type="button"
        className="primary"
        disabled={busy || blockers.length > 0}
        onClick={() => onApprove(role)}
      >
        {t(role === 'patient' ? 'approve.button.patient' : 'approve.button.clinician')}
      </button>
      {error !== null && error !== undefined && (
        <p className="note note-warning" role="alert">
          {describe(error)}
        </p>
      )}
    </section>
  )
}
