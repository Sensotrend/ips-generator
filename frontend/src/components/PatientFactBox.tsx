import { useState } from 'react'
import type { Fact, FactValue, ReviewAction, Source } from '../api/types'
import { editableFields, finalizeEdit, getIn, setIn } from '../lib/edit'
import { translateEnum, useT } from '../lib/i18n'
import { factRows, factTables, factTitle, flagLabel, WARNING_FLAGS } from '../lib/labels'
import { factSentence, isCompleted } from '../lib/sentences'
import { sourceExcerpt } from '../lib/sourceExcerpt'

/**
 * What a fact adds to the IPS, as a table with one row per element, labelled after the IPS
 * profile. Shared with the final summary.
 */
export function FactContent({ facts }: { facts: Fact[] }) {
  return (
    <table className="fact-table">
      <tbody>
        {facts.flatMap(factRows).map(([label, value], index) => (
          <tr key={index}>
            <th scope="row">{label}</th>
            <td>{value}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

/**
 * A section's facts for the final summary: the labels are the column headings and each fact is
 * a row (one table per kind of fact, as kinds have different columns).
 */
export function SectionTables({ facts }: { facts: Fact[] }) {
  return (
    <>
      {factTables(facts).map((table) => (
        <div key={table.columns.join('|')} className="table-scroll">
          <table className="fact-grid">
            <thead>
              <tr>
                {table.columns.map((column) => (
                  <th key={column} scope="col">
                    {column}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {table.rows.map((row) => (
                <tr key={row.path}>
                  {row.cells.map((cell, index) => (
                    <td key={index}>{cell}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
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
  const [showSource, setShowSource] = useState(false)
  const [allergyStatus, setAllergyStatus] = useState<'active' | 'inactive' | 'resolved'>('active')
  const fields = editableFields(fact)
  const accepted = fact.decision === 'accepted' || fact.decision === 'edited'
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
      className={[
        'chat-card',
        fact.decision === 'rejected' ? 'fact-rejected' : '',
        isCompleted(fact) ? 'fact-completed' : '',
      ]
        .filter(Boolean)
        .join(' ')}
      aria-label={factTitle(fact)}
    >
      <FactContent facts={[fact]} />
      <p className="box-note">{t('patient.box.fact')}</p>
      <h3 className="box-label">{t('patient.box.meaning')}</h3>
      <p className="chat-sentence">{factSentence(fact)}</p>
      {excerpt && fact.source && (
        <>
          <h3 className="box-label">
            <button
              type="button"
              className="source-toggle"
              aria-expanded={showSource}
              onClick={() => setShowSource(!showSource)}
            >
              {showSource ? '▾' : '▸'} {t('patient.box.source')} · {excerpt.location}
            </button>
          </h3>
          {showSource &&
            (excerpt.record ? (
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
            ))}
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
            onSend([{ action: 'edit', path: fact.path, value: finalizeEdit(fact, editing) }], () =>
              setEditing(null),
            )
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
            className={`primary${accepted ? ' chosen' : ''}`}
            aria-pressed={accepted}
            disabled={busy}
            onClick={() => onSend(confirm(), () => undefined)}
          >
            {accepted && '✓ '}
            {t('patient.yes')}
          </button>
          {fields.length > 0 && (
            <button type="button" disabled={busy} onClick={() => setEditing(fact.value)}>
              {t('patient.change')}
            </button>
          )}
          <button
            type="button"
            className={`danger${fact.decision === 'rejected' ? ' chosen' : ''}`}
            aria-pressed={fact.decision === 'rejected'}
            disabled={busy}
            onClick={() => onSend([{ action: 'reject', path: fact.path }], () => undefined)}
          >
            {fact.decision === 'rejected' && '✓ '}
            {t('patient.no')}
          </button>
        </div>
      )}
    </section>
  )
}
