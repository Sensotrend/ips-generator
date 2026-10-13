import { useState } from 'react'
import { ApiError } from '../api/client'
import { useApprove, useDraft, useUpdateDraft } from '../api/hooks'
import type { Draft, Fact, FactKind, ReviewAction, ReviewerRole, SourceRef } from '../api/types'
import { languageName, useT, type TKey } from '../lib/i18n'
import { sectionTitle } from '../lib/labels'
import { ApprovePanel } from './ApprovePanel'
import { FactTable } from './FactTable'
import { FlagChips } from './FlagChips'
import { SourceViewer } from './SourceViewer'

interface ListProps {
  draft: Draft
  selected: string | null
  readOnly: boolean
  busy: boolean
  onSelect: (fact: Fact) => void
  onActions: (actions: ReviewAction[]) => void
}

const KIND_HEADING: Record<FactKind, TKey> = {
  patient_name: 'row.name',
  patient_identifier: 'row.identifier',
  patient_birth_date: 'row.birthDate',
  patient_gender: 'row.sex',
  allergy: 'row.allergy',
  medication: 'row.medication',
  condition: 'row.problem',
  no_known_allergy_statement: 'section.statements',
  section_none_known: 'section.statements',
}

/** The facts as one table per kind (kinds have different columns), in order of appearance. */
function FactList({ facts, ...props }: ListProps & { facts: Fact[] }) {
  const { t } = useT()
  const byKind = new Map<TKey, Fact[]>()
  for (const fact of facts) {
    const heading = KIND_HEADING[fact.kind]
    byKind.set(heading, [...(byKind.get(heading) ?? []), fact])
  }
  return (
    <>
      {[...byKind].map(([heading, group]) => (
        <div key={heading}>
          <h3>{t(heading)}</h3>
          <FactTable
            facts={group}
            selected={props.selected}
            readOnly={props.readOnly}
            busy={props.busy}
            onSelect={props.onSelect}
            onActions={props.onActions}
          />
        </div>
      ))}
    </>
  )
}

export function SectionsList(props: ListProps) {
  const { draft } = props
  const { t } = useT()
  const patient = draft.patient
  const patientFacts = [
    ...patient.names,
    ...(patient.birth_date ? [patient.birth_date] : []),
    ...(patient.gender ? [patient.gender] : []),
    ...patient.identifiers,
  ]
  return (
    <div className="sections">
      <section className="section" aria-labelledby="sec-patient">
        <header>
          <h2 id="sec-patient">{t('section.patient')}</h2>
        </header>
        <FlagChips flags={patient.flags} />
        {patientFacts.length === 0 && <p className="muted">{t('section.noPatientDetails')}</p>}
        <FactList facts={patientFacts} {...props} />
      </section>
      {draft.sections.map((section) => (
        <section key={section.key} className="section" aria-labelledby={`sec-${section.key}`}>
          <header>
            <h2 id={`sec-${section.key}`}>{sectionTitle(section)}</h2>
            <span className="badge">{t(`section.kind.${section.kind}`)}</span>
            {section.effective_kind !== section.kind && (
              <span className="badge badge-warn">
                → {t(`section.kind.${section.effective_kind}`)}
              </span>
            )}
          </header>
          <FlagChips flags={section.flags} />
          <FactList
            facts={[
              ...(section.statement ? [section.statement] : []),
              ...section.items,
              ...section.scoped_statements,
            ]}
            {...props}
          />
          {section.kind === 'no_information' && section.items.length === 0 && (
            <p className="muted">{t('section.silent')}</p>
          )}
        </section>
      ))}
    </div>
  )
}

export function ReviewScreen({ jobId, role }: { jobId: string; role: ReviewerRole }) {
  const { t } = useT()
  const draft = useDraft(jobId, true)
  const update = useUpdateDraft(jobId)
  const approve = useApprove(jobId)
  const [selected, setSelected] = useState<{ path: string; source: SourceRef | null } | null>(null)
  const [tab, setTab] = useState<'facts' | 'source'>('facts')

  if (draft.isPending) return <p className="muted">{t('review.loading')}</p>
  if (draft.isError) return <p className="note note-warning">{t('review.loadFailed')}</p>
  const data = draft.data
  const readOnly = data.status === 'approved'
  const busy = update.isPending || approve.isPending
  const updateError = update.error instanceof ApiError ? update.error : null

  return (
    <div className="review" data-tab={tab}>
      <div className="review-head">
        <p className="muted">
          {t('review.meta', {
            language: languageName(data.document_language),
            version: data.version,
          })}
          {data.validation &&
            t('review.validation', {
              result: t(
                data.validation.passed ? 'review.validation.passed' : 'review.validation.failed',
              ),
              errors: data.validation.errors,
            })}
          {data.validation_error && t('review.validatorUnavailable')}
        </p>
        {data.dropped_paths.length > 0 && (
          <p className="note note-warning">
            {t('review.dropped', { count: data.dropped_paths.length })}
          </p>
        )}
        {updateError && (
          <p className="note note-warning" role="alert">
            {updateError.code === 'version_conflict'
              ? t('review.versionConflict')
              : updateError.message}
          </p>
        )}
        <div className="tabs" role="tablist">
          <button
            type="button"
            role="tab"
            aria-selected={tab === 'facts'}
            onClick={() => setTab('facts')}
          >
            {t('review.tab.facts')}
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={tab === 'source'}
            onClick={() => setTab('source')}
          >
            {t('review.tab.source')}
          </button>
        </div>
      </div>
      <div className="review-body">
        <div className="pane pane-facts">
          <SectionsList
            draft={data}
            selected={selected?.path ?? null}
            readOnly={readOnly}
            busy={busy}
            onSelect={(fact) => {
              setSelected({ path: fact.path, source: fact.source })
              setTab('source')
            }}
            onActions={(actions) =>
              update.mutate(
                { version: data.version, actions },
                {
                  onError: (error) => {
                    if (error instanceof ApiError && error.code === 'version_conflict')
                      void draft.refetch()
                  },
                },
              )
            }
          />
          <ApprovePanel
            jobId={jobId}
            approved={readOnly}
            blockers={data.blockers}
            busy={busy}
            error={approve.error}
            validation={approve.data?.validation ?? null}
            role={role}
            onApprove={(role) => approve.mutate({ version: data.version, role })}
          />
        </div>
        <div className="pane pane-source">
          <button type="button" className="back" onClick={() => setTab('facts')}>
            {t('review.backToFacts')}
          </button>
          <SourceViewer jobId={jobId} focus={selected?.source ?? null} />
        </div>
      </div>
    </div>
  )
}
