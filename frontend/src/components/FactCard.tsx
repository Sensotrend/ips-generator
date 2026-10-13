import { useState } from 'react'
import type { Fact, FactValue, ReviewAction } from '../api/types'
import { editableFields, getIn, setIn } from '../lib/edit'
import { translateEnum, useT } from '../lib/i18n'
import { factDetails, factTitle } from '../lib/labels'
import { FlagChips } from './FlagChips'

interface Props {
  fact: Fact
  selected: boolean
  readOnly: boolean
  busy: boolean
  onSelect: (fact: Fact) => void
  onActions: (actions: ReviewAction[]) => void
}

export function FactCard({ fact, selected, readOnly, busy, onSelect, onActions }: Props) {
  const { t } = useT()
  const [draft, setDraft] = useState<FactValue | null>(null)
  const [allergyStatus, setAllergyStatus] = useState<'active' | 'inactive' | 'resolved'>('active')
  const fields = editableFields(fact)
  const rejected = fact.decision === 'rejected'
  const derivedOnly = fact.derived !== null && !('source_quote' in fact.value)

  return (
    <article
      className={`fact${selected ? ' fact-selected' : ''}${rejected ? ' fact-rejected' : ''}`}
      aria-label={factTitle(fact)}
    >
      <button type="button" className="fact-main" onClick={() => onSelect(fact)}>
        <span className="fact-title">{factTitle(fact) || t('fact.empty')}</span>
        <span className={`decision decision-${fact.decision}`}>
          {t(`decision.${fact.decision}`)}
        </span>
        {derivedOnly && <span className="badge">{t('fact.derived')}</span>}
      </button>
      {factDetails(fact).length > 0 && (
        <dl className="fact-details">
          {factDetails(fact).map(([label, value]) => (
            <div key={label}>
              <dt>{label}</dt>
              <dd>{value}</dd>
            </div>
          ))}
        </dl>
      )}
      {fact.source && (
        <p className="fact-source">
          <span className="muted">
            {t('fact.page', { page: fact.source.page })}
            {fact.source.locator ? `, ${fact.source.locator}` : ''}:
          </span>{' '}
          <q>{fact.source.quote}</q>
        </p>
      )}
      <FlagChips flags={fact.flags} />
      {fact.notes.length > 0 && (
        <ul className="notes">
          {fact.notes.map((note, index) => (
            <li key={index} className={`note note-${note.severity}`}>
              {note.message}
            </li>
          ))}
        </ul>
      )}
      {fact.needs_confirmation && !readOnly && (
        <div className="confirm-row" role="group" aria-label={t('fact.confirmationNeeded')}>
          {fact.kind === 'allergy' ? (
            <label>
              {t('fact.clinicalStatus')}{' '}
              <select
                value={allergyStatus}
                onChange={(event) =>
                  setAllergyStatus(event.target.value as 'active' | 'inactive' | 'resolved')
                }
              >
                <option value="active">{translateEnum('active')}</option>
                <option value="inactive">{translateEnum('inactive')}</option>
                <option value="resolved">{translateEnum('resolved')}</option>
              </select>
            </label>
          ) : (
            <span>{t('fact.confirmDerived')}</span>
          )}
          <button
            type="button"
            className="primary"
            disabled={busy}
            onClick={() =>
              onActions([
                fact.kind === 'allergy'
                  ? { action: 'confirm', path: fact.path, clinical_status: allergyStatus }
                  : { action: 'confirm', path: fact.path },
              ])
            }
          >
            {t('fact.confirm')}
          </button>
        </div>
      )}
      {draft && (
        <form
          className="edit-form"
          onSubmit={(event) => {
            event.preventDefault()
            onActions([{ action: 'edit', path: fact.path, value: draft }])
            setDraft(null)
          }}
        >
          {fields.map((field) => (
            <label key={field.key}>
              {t(field.label)}
              {field.options ? (
                <select
                  value={getIn(draft, field.key)}
                  onChange={(event) => setDraft(setIn(draft, field.key, event.target.value))}
                >
                  {field.options.map((option) => (
                    <option key={option} value={option}>
                      {translateEnum(option)}
                    </option>
                  ))}
                </select>
              ) : (
                <input
                  value={getIn(draft, field.key)}
                  onChange={(event) => setDraft(setIn(draft, field.key, event.target.value))}
                />
              )}
            </label>
          ))}
          <div className="actions">
            <button type="submit" className="primary" disabled={busy}>
              {t('fact.save')}
            </button>
            <button type="button" onClick={() => setDraft(null)}>
              {t('fact.cancel')}
            </button>
          </div>
        </form>
      )}
      {!readOnly && !draft && (
        <div className="actions">
          <button
            type="button"
            disabled={busy || fact.decision === 'accepted'}
            onClick={() => onActions([{ action: 'accept', path: fact.path }])}
          >
            {t('fact.accept')}
          </button>
          {fields.length > 0 && (
            <button type="button" disabled={busy} onClick={() => setDraft(fact.value)}>
              {t('fact.edit')}
            </button>
          )}
          <button
            type="button"
            className="danger"
            disabled={busy || rejected}
            onClick={() => onActions([{ action: 'reject', path: fact.path }])}
          >
            {t('fact.reject')}
          </button>
          {fact.decision !== 'pending' && (
            <button
              type="button"
              disabled={busy}
              onClick={() => onActions([{ action: 'reset', path: fact.path }])}
            >
              {t('fact.undo')}
            </button>
          )}
        </div>
      )}
    </article>
  )
}
