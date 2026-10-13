import { useState } from 'react'
import type { Fact, FactValue, ReviewAction, Source } from '../api/types'
import { editableFields, getIn, setIn } from '../lib/edit'
import { translateEnum, useT } from '../lib/i18n'
import { factDetails, factTitle, flagLabel, WARNING_FLAGS } from '../lib/labels'
import { factSentence } from '../lib/sentences'
import { sourceExcerpt } from '../lib/sourceExcerpt'

/** What a fact adds to the IPS: its title and detail rows. Shared with the final summary. */
export function FactContent({ fact }: { fact: Fact }) {
  const details = factDetails(fact)
  return (
    <>
      <p className="fact-title">{factTitle(fact)}</p>
      {details.length > 0 && (
        <dl className="fact-details">
          {details.map(([label, value]) => (
            <div key={label}>
              <dt>{label}</dt>
              <dd>{value}</dd>
            </div>
          ))}
        </dl>
      )}
    </>
  )
}

/**
 * One fact in the patient review: what goes into the summary, what it means in plain language,
 * and where in the document it came from, followed by the answer buttons.
 */
export function PatientFactBox({
  fact,
  source,
  busy,
  onSend,
}: {
  fact: Fact
  source: Source | undefined
  busy: boolean
  /** Sends the actions; `done` runs once they were saved. */
  onSend: (actions: ReviewAction[], done: () => void) => void
}) {
  const { t } = useT()
  const [editing, setEditing] = useState<FactValue | null>(null)
  const [allergyStatus, setAllergyStatus] = useState<'active' | 'inactive' | 'resolved'>('active')
  const fields = editableFields(fact)
  const warnings = fact.flags.filter((flag) => WARNING_FLAGS.has(flag))
  const excerpt = fact.source ? sourceExcerpt(source, fact.source) : null

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
    <section
      className={`chat-card${fact.decision === 'rejected' ? ' fact-rejected' : ''}`}
      aria-label={factTitle(fact)}
    >
      <h3 className="box-label">{t('patient.box.fact')}</h3>
      <FactContent fact={fact} />
      <h3 className="box-label">{t('patient.box.meaning')}</h3>
      <p className="chat-sentence">{factSentence(fact)}</p>
      {excerpt && fact.source && (
        <>
          <h3 className="box-label">
            {t('patient.box.source')} · {excerpt.location}
          </h3>
          {excerpt.record ? (
            <ul className="source-record">
              {excerpt.record.map((line, index) => (
                <li key={index} className={line.focus ? 'seg-focus' : undefined}>
                  {line.text}
                </li>
              ))}
            </ul>
          ) : (
            <p className="fact-source">
              <q>{fact.source.quote}</q>
            </p>
          )}
        </>
      )}
      {warnings.length > 0 && (
        <ul className="notes">
          {warnings.map((flag) => (
            <li key={flag} className="note note-warning">
              {flagLabel(flag)}
            </li>
          ))}
        </ul>
      )}
      {fact.decision !== 'pending' && (
        <p className="muted">{t(`patient.decision.${fact.decision}`)}.</p>
      )}
      {fact.needs_confirmation && fact.kind === 'allergy' && (
        <label className="inline-field">
          {t('patient.allergyStatus')}{' '}
          <select
            value={allergyStatus}
            onChange={(event) =>
              setAllergyStatus(event.target.value as 'active' | 'inactive' | 'resolved')
            }
          >
            <option value="active">{t('patient.status.active')}</option>
            <option value="inactive">{t('patient.status.inactive')}</option>
            <option value="resolved">{t('patient.status.resolved')}</option>
          </select>
        </label>
      )}
      {editing ? (
        <form
          className="edit-form"
          onSubmit={(event) => {
            event.preventDefault()
            onSend([{ action: 'edit', path: fact.path, value: editing }], () => setEditing(null))
          }}
        >
          {fields.map((field) => (
            <label key={field.key}>
              {t(field.label)}
              {field.options ? (
                <select
                  value={getIn(editing, field.key)}
                  onChange={(event) => setEditing(setIn(editing, field.key, event.target.value))}
                >
                  {field.options.map((option) => (
                    <option key={option} value={option}>
                      {translateEnum(option)}
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
              {t('patient.save')}
            </button>
            <button type="button" onClick={() => setEditing(null)}>
              {t('fact.cancel')}
            </button>
          </div>
        </form>
      ) : (
        <div className="actions">
          <button
            type="button"
            className="primary"
            disabled={busy}
            onClick={() => onSend(confirm(), () => undefined)}
          >
            {t('patient.yes')}
          </button>
          {fields.length > 0 && (
            <button type="button" disabled={busy} onClick={() => setEditing(fact.value)}>
              {t('patient.change')}
            </button>
          )}
          <button
            type="button"
            className="danger"
            disabled={busy}
            onClick={() => onSend([{ action: 'reject', path: fact.path }], () => undefined)}
          >
            {t('patient.no')}
          </button>
        </div>
      )}
    </section>
  )
}
