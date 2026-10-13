import { useEffect, useRef, useState } from 'react'
import { ApiError } from '../api/client'
import { useApprove, useDraft, useSource, useUpdateDraft } from '../api/hooks'
import type { ReviewAction } from '../api/types'
import { DocumentInfo } from './DocumentInfo'
import { useT } from '../lib/i18n'
import { reviewGroups } from '../lib/sentences'
import { ApprovePanel } from './ApprovePanel'
import { FactContent, PatientFactBox, SectionTables } from './PatientFactBox'

/** Review for patients: one IPS section at a time, then the whole summary to approve. */
export function PatientReview({ jobId }: { jobId: string }) {
  const { t, locale } = useT()
  const draft = useDraft(jobId, true)
  const update = useUpdateDraft(jobId)
  const approve = useApprove(jobId)
  const source = useSource(jobId, true)
  const [index, setIndex] = useState(0)
  // Once the summary was seen, a "Summary →" shortcut spares the walk through the later sections.
  const [seenSummary, setSeenSummary] = useState(false)
  // Moving to another section scrolls back up to its first item.
  const sectionTop = useRef<HTMLElement | null>(null)
  const firstRender = useRef(true)
  useEffect(() => {
    if (firstRender.current) {
      firstRender.current = false
      return
    }
    sectionTop.current?.scrollIntoView?.({ block: 'start' })
  }, [index])

  if (draft.isPending) return <p className="muted">{t('patient.loading')}</p>
  if (draft.isError) return <p className="note note-warning">{t('patient.loadFailed')}</p>
  const data = draft.data
  const groups = reviewGroups(data)
  const steps = groups.filter((group) => group.facts.length > 0)
  const approved = data.status === 'approved'
  const busy = update.isPending || approve.isPending
  const onSummary = approved || index >= steps.length
  const backToStep = (stepIndex: number) => {
    setSeenSummary(true)
    setIndex(stepIndex)
  }
  /** The page whose facts the path belongs to (`patient.birth_date`, `allergies.items[0]`). */
  const stepOfPath = (path: string | null) =>
    steps.findIndex((s) => s.key === (path ?? '').split(/[.[]/)[0])
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
        <section
          className="chat-card no-print"
          aria-label={t('patient.summary.label')}
          ref={(el) => {
            sectionTop.current = el
          }}
        >
          <h2>{t(approved ? 'patient.summary.approved' : 'patient.summary.ready')}</h2>
          {!hasFacts && <p>{t('patient.summary.empty')}</p>}
          {!approved && (
            <button type="button" onClick={() => backToStep(Math.max(steps.length - 1, 0))}>
              {t('patient.goBack')}
            </button>
          )}
        </section>
        <h1 className="doc-title">
          {t('doc.title')}
          {locale !== 'en' && <span className="doc-title-english">{t('doc.titleEnglish')}</span>}
        </h1>
        <DocumentInfo info={data.document} locale={locale} />
        {groups.map((group) => {
          // Only facts the patient has answered "yes" to (or changed) go into the summary.
          const facts = group.facts.filter(
            (fact) => fact.decision === 'accepted' || fact.decision === 'edited',
          )
          const unreviewed = group.facts.filter((fact) => fact.decision === 'pending').length
          const stepIndex = steps.indexOf(group)
          return (
            <section key={group.key} className="chat-card" aria-label={group.heading}>
              <h3>{group.heading}</h3>
              {unreviewed > 0 && (
                <p className="note note-warning" role="alert">
                  {t('patient.summary.unreviewed', { count: unreviewed })}{' '}
                  {!approved && stepIndex >= 0 && (
                    <button
                      type="button"
                      className="link-button"
                      onClick={() => backToStep(stepIndex)}
                    >
                      {t('patient.summary.reviewSection')}
                    </button>
                  )}
                </p>
              )}
              {facts.length === 0 ? (
                <p className="muted">
                  {t(
                    group.facts.length > 0
                      ? 'patient.summary.noneApproved'
                      : group.key === 'patient'
                        ? 'section.noPatientDetails'
                        : 'section.silent',
                  )}
                </p>
              ) : (
                // The patient's facts are different fields of one record; the rest are lists.
                <div className="summary-facts">
                  {group.key === 'patient' ? (
                    <FactContent facts={facts} />
                  ) : (
                    <SectionTables facts={facts} />
                  )}
                </div>
              )}
            </section>
          )
        })}
        {errorNote}
        <ApprovePanel
          jobId={jobId}
          approved={approved}
          onPrint={() => window.print()}
          blockers={data.blockers}
          busy={busy}
          error={approve.error}
          validation={approve.data?.validation ?? null}
          role="patient"
          onApprove={(role) => approve.mutate({ version: data.version, role })}
          onShowBlocker={(blocker) => {
            const step = stepOfPath(blocker.path)
            if (step >= 0) backToStep(step)
          }}
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
      <h2
        ref={(el) => {
          sectionTop.current = el
        }}
      >
        {group.heading}
      </h2>
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
        {seenSummary && (
          <button type="button" disabled={busy} onClick={() => setIndex(steps.length)}>
            {t('patient.toSummary')}
          </button>
        )}
      </div>
    </div>
  )
}
