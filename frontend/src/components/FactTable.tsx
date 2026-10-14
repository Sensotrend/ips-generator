import { useState, type MouseEvent } from 'react'
import type { Fact, FactKind, FactValue, ReviewAction } from '../api/types'
import { editableFields, finalizeEdit, getIn, setIn } from '../lib/edit'
import { translateEnum, useT, type TKey } from '../lib/i18n'
import { factTitle } from '../lib/labels'
import { FlagChips } from './FlagChips'

interface Props {
  /** Facts of one kind (the columns differ per kind). */
  facts: Fact[]
  selected: string | null
  readOnly: boolean
  busy: boolean
  onSelect: (fact: Fact) => void
  onActions: (actions: ReviewAction[]) => void
}

/** Read-only columns that come after the editable ones. */
const EXTRA_COLUMNS: Partial<Record<FactKind, { label: TKey; get: (v: FactValue) => string }[]>> = {
  allergy: [
    { label: 'detail.category', get: (v) => enumText(v.category) },
    {
      label: 'detail.reactions',
      get: (v) =>
        (v.reactions ?? [])
          .flatMap((r: { manifestations: string[] }) => r.manifestations)
          .join(', '),
    },
  ],
  medication: [{ label: 'detail.reason', get: (v) => String(v.reason_text ?? '') }],
  condition: [{ label: 'detail.verification', get: (v) => enumText(v.verification_status) }],
  vital_sign: [{ label: 'detail.measurement', get: (v) => enumText(v.kind) }],
  social_history: [{ label: 'detail.topic', get: (v) => enumText(v.kind) }],
  pregnancy_fact: [{ label: 'detail.pregnancyFact', get: (v) => enumText(v.kind) }],
  result: [{ label: 'detail.testKind', get: (v) => enumText(v.category) }],
  no_known_allergy_statement: [{ label: 'detail.scope', get: (v) => enumText(v.scope) }],
  section_none_known: [{ label: 'detail.scope', get: (v) => enumText(v.scope) }],
}

/** Values the reviewer cannot edit but should see in the summary: the derived ones. */
const DERIVED_KINDS = new Set<FactKind>(['patient_birth_date', 'patient_gender'])

function enumText(value: unknown): string {
  return typeof value === 'string' && value !== 'not_stated' ? translateEnum(value) : ''
}

const INTERACTIVE = 'button, input, select, textarea, a, label'

function ConfirmControls({
  fact,
  busy,
  onActions,
}: {
  fact: Fact
  busy: boolean
  onActions: (actions: ReviewAction[]) => void
}) {
  const { t } = useT()
  const [status, setStatus] = useState<'active' | 'inactive' | 'resolved'>('active')
  const allergy = fact.kind === 'allergy'
  return (
    <div className="confirm-row" role="group" aria-label={t('fact.confirmationNeeded')}>
      {allergy ? (
        <label>
          {t('fact.clinicalStatus')}{' '}
          <select
            value={status}
            onChange={(event) => setStatus(event.target.value as typeof status)}
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
            allergy
              ? { action: 'confirm', path: fact.path, clinical_status: status }
              : { action: 'confirm', path: fact.path },
          ])
        }
      >
        {t('fact.confirm')}
      </button>
    </div>
  )
}

/**
 * One kind of fact as a table for the clinician: the labels are the column headings and each fact
 * is a group of rows (its own `<tbody>`): the values, then the decision and notes, then the source
 * quote when there is one. The checkbox and Actions cells span the group. Clicking a fact ticks
 * it; the buttons under the table accept, reject or undo the ticked facts in one go. A fact's Edit
 * button turns its value cells into inputs.
 */
export function FactTable({ facts, selected, readOnly, busy, onSelect, onActions }: Props) {
  const { t } = useT()
  const [ticked, setTicked] = useState<Set<string>>(new Set())
  const [editing, setEditing] = useState<{ path: string; value: FactValue } | null>(null)

  const kind = facts[0].kind
  const fields = editableFields(facts.find((f) => editableFields(f).length > 0) ?? facts[0])
  const extras = EXTRA_COLUMNS[kind] ?? []
  const showTitle = fields.length === 0
  /** Data columns between the checkbox and Actions; the detail rows span them. */
  const columns = (showTitle ? 1 : 0) + fields.length + extras.length
  const tickedHere = facts.filter((f) => ticked.has(f.path))
  const allTicked = tickedHere.length === facts.length

  const toggle = (path: string) =>
    setTicked((previous) => {
      const next = new Set(previous)
      if (!next.delete(path)) next.add(path)
      return next
    })
  const sendTicked = (action: 'accept' | 'reject' | 'reset') => {
    onActions(tickedHere.map((f) => ({ action, path: f.path })))
    setTicked(new Set())
  }

  const cell = (fact: Fact, field: (typeof fields)[number]) => {
    const isEditing = editing?.path === fact.path
    if (!isEditing) {
      if (DERIVED_KINDS.has(kind)) return factTitle(fact)
      const text = getIn(fact.value, field.key)
      return field.options ? enumText(text) : text
    }
    const label = t(field.label)
    return field.options ? (
      <select
        aria-label={label}
        value={getIn(editing.value, field.key)}
        onChange={(event) =>
          setEditing({
            path: fact.path,
            value: setIn(editing.value, field.key, event.target.value),
          })
        }
      >
        {field.options.map((option) => (
          <option key={option} value={option}>
            {translateEnum(option)}
          </option>
        ))}
      </select>
    ) : (
      <input
        aria-label={label}
        placeholder={field.format && t(field.format)}
        value={getIn(editing.value, field.key)}
        onChange={(event) =>
          setEditing({
            path: fact.path,
            value: setIn(editing.value, field.key, event.target.value),
          })
        }
      />
    )
  }

  return (
    <div className="review-table">
      <div className="table-scroll">
        <table className={`fact-grid fact-review-grid${readOnly ? ' read-only' : ''}`}>
          <thead>
            <tr>
              {!readOnly && (
                <th scope="col" className="col-check">
                  <input
                    type="checkbox"
                    aria-label={t('table.selectAll')}
                    checked={allTicked}
                    disabled={busy}
                    onChange={() =>
                      setTicked(allTicked ? new Set() : new Set(facts.map((f) => f.path)))
                    }
                  />
                </th>
              )}
              {showTitle && <th scope="col">{t('table.statement')}</th>}
              {fields.map((field) => (
                <th key={field.key} scope="col">
                  {t(field.label)}
                </th>
              ))}
              {extras.map((extra) => (
                <th key={extra.label} scope="col">
                  {t(extra.label)}
                </th>
              ))}
              {!readOnly && <th scope="col">{t('table.actions')}</th>}
            </tr>
          </thead>
          {facts.map((fact) => {
            const isEditing = editing?.path === fact.path
            const rowFields = editableFields(fact)
            const rejected = fact.decision === 'rejected'
            const name = factTitle(fact) || t('fact.empty')
            const hasNotes =
              fact.flags.length > 0 ||
              fact.notes.length > 0 ||
              (fact.needs_confirmation && !readOnly)
            const rowSpan = fact.source ? 3 : 2
            const onRowClick = (event: MouseEvent) => {
              if (readOnly || isEditing || (event.target as HTMLElement).closest(INTERACTIVE))
                return
              toggle(fact.path)
            }
            return (
              <tbody
                key={fact.path}
                className={[
                  ticked.has(fact.path) ? 'row-ticked' : '',
                  selected === fact.path ? 'row-selected' : '',
                  rejected ? 'row-rejected' : '',
                ]
                  .filter(Boolean)
                  .join(' ')}
                onClick={onRowClick}
              >
                <tr>
                  {!readOnly && (
                    <td className="col-check" rowSpan={rowSpan}>
                      <input
                        type="checkbox"
                        aria-label={t('table.selectRow', { name })}
                        checked={ticked.has(fact.path)}
                        disabled={busy || isEditing}
                        onChange={() => toggle(fact.path)}
                      />
                    </td>
                  )}
                  {showTitle && <td>{name}</td>}
                  {fields.map((field) => (
                    <td key={field.key}>
                      {rowFields.some((f) => f.key === field.key) || !isEditing
                        ? cell(fact, field)
                        : getIn(fact.value, field.key)}
                    </td>
                  ))}
                  {extras.map((extra) => (
                    <td key={extra.label}>{extra.get(fact.value)}</td>
                  ))}
                  {!readOnly && (
                    <td className="col-actions" rowSpan={rowSpan}>
                      {isEditing ? (
                        <>
                          <button
                            type="button"
                            className="primary"
                            disabled={busy}
                            onClick={() => {
                              onActions([
                                {
                                  action: 'edit',
                                  path: fact.path,
                                  value: finalizeEdit(fact, editing.value),
                                },
                              ])
                              setEditing(null)
                            }}
                          >
                            {t('fact.save')}
                          </button>
                          <button type="button" onClick={() => setEditing(null)}>
                            {t('fact.cancel')}
                          </button>
                        </>
                      ) : (
                        rowFields.length > 0 && (
                          <button
                            type="button"
                            disabled={busy}
                            aria-label={t('table.editRow', { name })}
                            onClick={() => setEditing({ path: fact.path, value: fact.value })}
                          >
                            {t('fact.edit')}
                          </button>
                        )
                      )}
                    </td>
                  )}
                </tr>
                <tr className="row-detail">
                  <td colSpan={columns}>
                    <div className="row-detail-items">
                      <span>
                        <span className="muted">{t('table.decision')}:</span>{' '}
                        <span className={`decision decision-${fact.decision}`}>
                          {t(`decision.${fact.decision}`)}
                        </span>
                        {fact.derived !== null && !('source_quote' in fact.value) && (
                          <>
                            {' '}
                            <span className="badge">{t('fact.derived')}</span>
                          </>
                        )}
                      </span>
                      {hasNotes && (
                        <div className="row-detail-notes">
                          <span className="muted">{t('table.notes')}:</span>{' '}
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
                            <ConfirmControls fact={fact} busy={busy} onActions={onActions} />
                          )}
                        </div>
                      )}
                    </div>
                  </td>
                </tr>
                {fact.source && (
                  <tr className="row-detail row-source">
                    <td colSpan={columns}>
                      <span className="muted">{t('table.source')}:</span>{' '}
                      <button
                        type="button"
                        className="fact-source-link"
                        title={t('fact.showInSource')}
                        onClick={() => onSelect(fact)}
                      >
                        <span className="muted">
                          {t('fact.page', { page: fact.source.page })}
                          {fact.source.locator ? `, ${fact.source.locator}` : ''}:
                        </span>{' '}
                        <q>{fact.source.quote}</q>
                      </button>
                    </td>
                  </tr>
                )}
              </tbody>
            )
          })}
        </table>
      </div>
      {!readOnly && (
        <div className="actions table-actions">
          <button
            type="button"
            className="primary"
            disabled={busy || tickedHere.length === 0}
            onClick={() => sendTicked('accept')}
          >
            {t('table.acceptSelected')}
          </button>
          <button
            type="button"
            className="danger"
            disabled={busy || tickedHere.length === 0}
            onClick={() => sendTicked('reject')}
          >
            {t('table.rejectSelected')}
          </button>
          <button
            type="button"
            disabled={busy || tickedHere.length === 0}
            onClick={() => sendTicked('reset')}
          >
            {t('table.undoSelected')}
          </button>
          <span className="muted">{t('table.selectedCount', { count: tickedHere.length })}</span>
        </div>
      )}
    </div>
  )
}
