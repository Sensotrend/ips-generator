import { useState } from 'react'
import { ApiError } from '../api/client'
import { useApprove, useDraft, useSource, useUpdateDraft } from '../api/hooks'
import type { ReviewAction } from '../api/types'
import { useT } from '../lib/i18n'
import { reviewGroups } from '../lib/sentences'
import { ApprovePanel } from './ApprovePanel'
import { FactContent, PatientFactBox } from './PatientFactBox'

/** Review for patients: one IPS section at a time, then the whole summary to approve. */
export function PatientReview({ jobId }: { jobId: string }) {
  const { t } = useT()
  const draft = useDraft(jobId, true)
  const update = useUpdateDraft(jobId)
  const approve = useApprove(jobId)
  const source = useSource(jobId, true)
  const [index, setIndex] = useState(0)

  if (draft.isPending) return <p className="muted">{t('patient.loading')}</p>
  if (draft.isError) return <p className="note note-warning">{t('patient.loadFailed')}</p>
  const data = draft.data
  const groups = reviewGroups(data)
  const steps = groups.filter((group) => group.facts.length > 0)
  const approved = data.status === 'approved'
  const busy = update.isPending || approve.isPending
  const onSummary = approved || index >= steps.length
  const updateError = update.error instanceof ApiError ? update.error : null

  const send = (actions: ReviewAction[], done: () => void) => {
    if (actions.length === 0) return done()
    update.mutate(
      { version: data.version, actions },
      {
        onSuccess: done,
        onError: (error) => {
          if (error instanceof ApiError && error.code === 'version_conflict') void draft.refetch()
        },
      },
    )
  }

  const errorNote = updateError && (
    <p className="note note-warning" role="alert">
      {updateError.code === 'version_conflict' ? t('patient.versionConflict') : updateError.message}
    </p>
  )

  if (onSummary) {
    const hasFacts = steps.length > 0
    return (
      <div className="patient-review">
        <section className="chat-card" aria-label={t('patient.summary.label')}>
          <h2>{t(approved ? 'patient.summary.approved' : 'patient.summary.ready')}</h2>
          {!hasFacts && <p>{t('patient.summary.empty')}</p>}
          {!approved && (
            <button type="button" onClick={() => setIndex(Math.max(steps.length - 1, 0))}>
              {t('patient.goBack')}
            </button>
          )}
        </section>
        {groups.map((group) => {
          const facts = group.facts.filter((fact) => fact.decision !== 'rejected')
          return (
            <section key={group.key} className="chat-card" aria-label={group.heading}>
              <h3>{group.heading}</h3>
              {facts.length === 0 ? (
                <p className="muted">
                  {t(group.key === 'patient' ? 'section.noPatientDetails' : 'section.silent')}
                </p>
              ) : (
                <ul className="summary-facts">
                  {facts.map((fact) => (
                    <li key={fact.path}>
                      <FactContent fact={fact} />
                    </li>
                  ))}
                </ul>
              )}
            </section>
          )
        })}
        {errorNote}
        <ApprovePanel
          jobId={jobId}
          approved={approved}
          blockers={data.blockers}
          busy={busy}
          error={approve.error}
          validation={approve.data?.validation ?? null}
          role="patient"
          onApprove={(role) => approve.mutate({ version: data.version, role })}
        />
      </div>
    )
  }

  const group = steps[index]
  return (
    <div className="patient-review">
      <p className="muted" aria-live="polite">
        {t('patient.step', { step: index + 1, total: steps.length, heading: group.heading })}
      </p>
      <h2>{group.heading}</h2>
      <p className="section-intro">{t(group.intro)}</p>
      {group.facts.map((fact) => (
        <PatientFactBox
          key={fact.path}
          fact={fact}
          source={source.data}
          busy={busy}
          onSend={send}
        />
      ))}
      {errorNote}
      <div className="actions">
        <button type="button" disabled={index === 0 || busy} onClick={() => setIndex(index - 1)}>
          {t('patient.back')}
        </button>
        <button
          type="button"
          className="primary"
          disabled={busy}
          onClick={() => setIndex(index + 1)}
        >
          {t('patient.next')}
        </button>
      </div>
    </div>
  )
}
