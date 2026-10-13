import { useState } from 'react'
import { ApiError } from '../api/client'
import { useApprove, useDraft, useUpdateDraft } from '../api/hooks'
import type { FactValue, ReviewAction } from '../api/types'
import { editableFields, getIn, setIn } from '../lib/edit'
import { FLAG_LABELS, WARNING_FLAGS } from '../lib/labels'
import { factSentence, patientSteps, silentSections } from '../lib/sentences'
import { ApprovePanel } from './ApprovePanel'

const DECISION_TEXT = {
  pending: 'Not answered yet',
  accepted: 'You said this is right',
  edited: 'You changed this',
  rejected: 'You said this is not right',
} as const

/** Conversational review for patients: one fact at a time, then a summary to approve. */
export function PatientReview({ jobId }: { jobId: string }) {
  const draft = useDraft(jobId, true)
  const update = useUpdateDraft(jobId)
  const approve = useApprove(jobId)
  const [index, setIndex] = useState(0)
  const [editing, setEditing] = useState<FactValue | null>(null)
  const [allergyStatus, setAllergyStatus] = useState<'active' | 'inactive' | 'resolved'>('active')

  if (draft.isPending) return <p className="muted">Loading your summary…</p>
  if (draft.isError) return <p className="note note-warning">Your summary could not be loaded.</p>
  const data = draft.data
  const steps = patientSteps(data)
  const approved = data.status === 'approved'
  const busy = update.isPending || approve.isPending
  const onSummary = approved || index >= steps.length
  const updateError = update.error instanceof ApiError ? update.error : null

  const send = (actions: ReviewAction[]) =>
    update.mutate(
      { version: data.version, actions },
      {
        onSuccess: () => {
          setEditing(null)
          setIndex((i) => i + 1)
        },
        onError: (error) => {
          if (error instanceof ApiError && error.code === 'version_conflict') void draft.refetch()
        },
      },
    )

  const errorNote = updateError && (
    <p className="note note-warning" role="alert">
      {updateError.code === 'version_conflict'
        ? 'The summary changed meanwhile and has been reloaded. Please answer again.'
        : updateError.message}
    </p>
  )

  if (onSummary) {
    const silent = silentSections(data)
    const counts = { right: 0, changed: 0, wrong: 0, open: 0 }
    for (const { fact } of steps) {
      if (fact.decision === 'accepted') counts.right++
      else if (fact.decision === 'edited') counts.changed++
      else if (fact.decision === 'rejected') counts.wrong++
      else counts.open++
    }
    return (
      <div className="patient-review">
        <section className="chat-card" aria-label="Your summary">
          <h2>{approved ? 'Your summary is approved' : 'Your summary is ready'}</h2>
          {steps.length === 0 ? (
            <p>We did not find anything in the document to put in your summary.</p>
          ) : (
            <p>
              You went through {steps.length} item{steps.length === 1 ? '' : 's'}: {counts.right}{' '}
              confirmed, {counts.changed} changed, {counts.wrong} removed
              {counts.open > 0 ? `, ${counts.open} not answered` : ''}.
            </p>
          )}
          {silent.length > 0 && (
            <p className="muted">The document said nothing about: {silent.join(', ')}.</p>
          )}
          {!approved && (
            <button type="button" onClick={() => setIndex(Math.max(steps.length - 1, 0))}>
              ← Go back
            </button>
          )}
        </section>
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

  const { heading, fact } = steps[index]
  const fields = editableFields(fact)
  const warnings = fact.flags.filter((flag) => WARNING_FLAGS.has(flag))
  const confirm = (): ReviewAction[] => {
    const actions: ReviewAction[] = []
    if (fact.decision !== 'accepted') actions.push({ action: 'accept', path: fact.path })
    if (fact.needs_confirmation)
      actions.push(
        fact.kind === 'allergy'
          ? { action: 'confirm', path: fact.path, clinical_status: allergyStatus }
          : { action: 'confirm', path: fact.path },
      )
    return actions
  }

  return (
    <div className="patient-review">
      <p className="muted" aria-live="polite">
        Step {index + 1} of {steps.length} · {heading}
      </p>
      <section className="chat-card" aria-label={heading}>
        <p className="chat-sentence">{factSentence(fact)}</p>
        {fact.source && (
          <p className="fact-source">
            <span className="muted">The document says:</span> <q>{fact.source.quote}</q>
          </p>
        )}
        {warnings.length > 0 && (
          <ul className="notes">
            {warnings.map((flag) => (
              <li key={flag} className="note note-warning">
                {FLAG_LABELS[flag]}
              </li>
            ))}
          </ul>
        )}
        {fact.decision !== 'pending' && <p className="muted">{DECISION_TEXT[fact.decision]}.</p>}
        {fact.needs_confirmation && fact.kind === 'allergy' && (
          <label className="inline-field">
            The document does not say if this allergy is still current. Is it:{' '}
            <select
              value={allergyStatus}
              onChange={(event) =>
                setAllergyStatus(event.target.value as 'active' | 'inactive' | 'resolved')
              }
            >
              <option value="active">still active</option>
              <option value="inactive">not active</option>
              <option value="resolved">resolved</option>
            </select>
          </label>
        )}
        {editing ? (
          <form
            className="edit-form"
            onSubmit={(event) => {
              event.preventDefault()
              send([{ action: 'edit', path: fact.path, value: editing }])
            }}
          >
            {fields.map((field) => (
              <label key={field.key}>
                {field.label}
                {field.options ? (
                  <select
                    value={getIn(editing, field.key)}
                    onChange={(event) => setEditing(setIn(editing, field.key, event.target.value))}
                  >
                    {field.options.map((option) => (
                      <option key={option} value={option}>
                        {option.replace(/_/g, ' ')}
                      </option>
                    ))}
                  </select>
                ) : (
                  <input
                    value={getIn(editing, field.key)}
                    onChange={(event) => setEditing(setIn(editing, field.key, event.target.value))}
                  />
                )}
              </label>
            ))}
            <div className="actions">
              <button type="submit" className="primary" disabled={busy}>
                Save change
              </button>
              <button type="button" onClick={() => setEditing(null)}>
                Cancel
              </button>
            </div>
          </form>
        ) : (
          <div className="actions">
            <button
              type="button"
              className="primary"
              disabled={busy}
              onClick={() => send(confirm())}
            >
              Yes, that is right
            </button>
            {fields.length > 0 && (
              <button type="button" disabled={busy} onClick={() => setEditing(fact.value)}>
                Change it
              </button>
            )}
            <button
              type="button"
              className="danger"
              disabled={busy}
              onClick={() => send([{ action: 'reject', path: fact.path }])}
            >
              No, leave it out
            </button>
          </div>
        )}
        {errorNote}
      </section>
      <div className="actions">
        <button
          type="button"
          disabled={index === 0 || busy}
          onClick={() => {
            setEditing(null)
            setIndex(index - 1)
          }}
        >
          ← Back
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => {
            setEditing(null)
            setIndex(index + 1)
          }}
        >
          Skip for now
        </button>
      </div>
    </div>
  )
}
