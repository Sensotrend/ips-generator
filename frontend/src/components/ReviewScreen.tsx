import { useState } from 'react'
import { ApiError } from '../api/client'
import { useApprove, useDraft, useUpdateDraft } from '../api/hooks'
import type { Draft, Fact, ReviewAction, ReviewerRole, Section, SourceRef } from '../api/types'
import { ApprovePanel } from './ApprovePanel'
import { FactCard } from './FactCard'
import { FlagChips } from './FlagChips'
import { SourceViewer } from './SourceViewer'

const KIND_LABEL: Record<Section['kind'], string> = {
  items_found: 'entries',
  none_known: 'none known',
  no_information: 'no information',
}

interface ListProps {
  draft: Draft
  selected: string | null
  readOnly: boolean
  busy: boolean
  onSelect: (fact: Fact) => void
  onActions: (actions: ReviewAction[]) => void
}

function FactList({ facts, ...props }: ListProps & { facts: Fact[] }) {
  return (
    <>
      {facts.map((fact) => (
        <FactCard
          key={fact.path}
          fact={fact}
          selected={props.selected === fact.path}
          readOnly={props.readOnly}
          busy={props.busy}
          onSelect={props.onSelect}
          onActions={props.onActions}
        />
      ))}
    </>
  )
}

export function SectionsList(props: ListProps) {
  const { draft } = props
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
          <h2 id="sec-patient">Patient</h2>
        </header>
        <FlagChips flags={patient.flags} />
        {patientFacts.length === 0 && <p className="muted">No patient details found.</p>}
        <FactList facts={patientFacts} {...props} />
      </section>
      {draft.sections.map((section) => (
        <section key={section.key} className="section" aria-labelledby={`sec-${section.key}`}>
          <header>
            <h2 id={`sec-${section.key}`}>{section.title}</h2>
            <span className="badge">{KIND_LABEL[section.kind]}</span>
            {section.effective_kind !== section.kind && (
              <span className="badge badge-warn">→ {KIND_LABEL[section.effective_kind]}</span>
            )}
          </header>
          <FlagChips flags={section.flags} />
          {section.statement && <FactList facts={[section.statement]} {...props} />}
          <FactList facts={section.items} {...props} />
          {section.scoped_statements.length > 0 && (
            <>
              <h3>Statements</h3>
              <FactList facts={section.scoped_statements} {...props} />
            </>
          )}
          {section.kind === 'no_information' && section.items.length === 0 && (
            <p className="muted">The document says nothing about this section.</p>
          )}
        </section>
      ))}
    </div>
  )
}

export function ReviewScreen({ jobId, role }: { jobId: string; role: ReviewerRole }) {
  const draft = useDraft(jobId, true)
  const update = useUpdateDraft(jobId)
  const approve = useApprove(jobId)
  const [selected, setSelected] = useState<{ path: string; source: SourceRef | null } | null>(null)
  const [tab, setTab] = useState<'facts' | 'source'>('facts')

  if (draft.isPending) return <p className="muted">Loading draft…</p>
  if (draft.isError) return <p className="note note-warning">The draft could not be loaded.</p>
  const data = draft.data
  const readOnly = data.status === 'approved'
  const busy = update.isPending || approve.isPending
  const updateError = update.error instanceof ApiError ? update.error : null

  return (
    <div className="review" data-tab={tab}>
      <div className="review-head">
        <p className="muted">
          Language: {data.document_language} · draft v{data.version}
          {data.validation &&
            ` · pipeline validation: ${data.validation.passed ? 'passed' : 'failed'} (${data.validation.errors} errors)`}
          {data.validation_error && ' · validator unavailable'}
        </p>
        {data.dropped_paths.length > 0 && (
          <p className="note note-warning">
            {data.dropped_paths.length} extracted fact(s) were dropped: their quote was not found in
            the document.
          </p>
        )}
        {updateError && (
          <p className="note note-warning" role="alert">
            {updateError.code === 'version_conflict'
              ? 'The draft changed meanwhile; it has been reloaded.'
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
            Facts
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={tab === 'source'}
            onClick={() => setTab('source')}
          >
            Source
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
            ← Back to facts
          </button>
          <SourceViewer jobId={jobId} focus={selected?.source ?? null} />
        </div>
      </div>
    </div>
  )
}
