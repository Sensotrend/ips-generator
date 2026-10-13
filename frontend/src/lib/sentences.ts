import type { Draft, Fact } from '../api/types'
import { factTitle } from './labels'

const str = (value: unknown): string => (typeof value === 'string' ? value : '')
const known = (value: unknown): string => {
  const text = str(value)
  return text && text !== 'not_stated' ? text.replace(/_/g, ' ') : ''
}

const DERIVED = 'It was worked out from your personal identity code, not stated in the document.'

/**
 * Plain-language sentence for a fact, built deterministically from its fields (no LLM, so it can
 * only say what the extraction says).
 */
export function factSentence(fact: Fact): string {
  const v = fact.value
  const title = factTitle(fact)
  switch (fact.kind) {
    case 'patient_name':
      return `Your name is ${title}.`
    case 'patient_birth_date':
      return `Your date of birth is ${title}.${fact.derived ? ` ${DERIVED}` : ''}`
    case 'patient_gender':
      return `Your sex is recorded as ${title}.${fact.derived ? ` ${DERIVED}` : ''}`
    case 'patient_identifier':
      return `The document gives this identifier for you: ${title}.`
    case 'allergy': {
      const reactions = (v.reactions ?? [])
        .flatMap((r: { manifestations: string[] }) => r.manifestations)
        .join(', ')
      const status = known(v.clinical_status)
      return (
        `The document says you have an allergy or intolerance to ${title}` +
        (reactions ? `, with the reaction: ${reactions}` : '') +
        (status ? ` (${status})` : '') +
        '.'
      )
    }
    case 'medication': {
      const dosage = known(v.dosage?.text)
      const status = known(v.status)
      return (
        `The document lists the medication ${title}` +
        (dosage ? `, taken as: ${dosage}` : '') +
        (status ? ` (${status})` : '') +
        '.'
      )
    }
    case 'condition': {
      const status = known(v.clinical_status)
      const onset = known(v.onset)
      return (
        `The document lists the health condition ${title}` +
        (onset ? `, starting ${onset}` : '') +
        (status ? ` (${status})` : '') +
        '.'
      )
    }
    case 'no_known_allergy_statement':
    case 'section_none_known':
      return `The document states that nothing is known here: “${fact.source?.quote ?? title}”.`
  }
}

export interface Step {
  /** Section heading shown above the sentence. */
  heading: string
  fact: Fact
}

/** The facts a patient walks through, in order: about you, then each section. */
export function patientSteps(draft: Draft): Step[] {
  const patient = draft.patient
  const about = [
    ...patient.names,
    ...(patient.birth_date ? [patient.birth_date] : []),
    ...(patient.gender ? [patient.gender] : []),
    ...patient.identifiers,
  ].map((fact) => ({ heading: 'About you', fact }))
  const sections = draft.sections.flatMap((section) =>
    [
      ...(section.statement ? [section.statement] : []),
      ...section.items,
      ...section.scoped_statements,
    ].map((fact) => ({ heading: section.title, fact })),
  )
  return [...about, ...sections]
}

/** Sections the document said nothing about: shown on the summary page, not as steps. */
export function silentSections(draft: Draft): string[] {
  return draft.sections
    .filter((s) => s.effective_kind === 'no_information' && s.items.length === 0)
    .map((s) => s.title)
}
