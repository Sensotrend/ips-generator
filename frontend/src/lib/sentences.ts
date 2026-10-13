import type { Draft, Fact } from '../api/types'
import { translate, translateEnum } from './i18n'
import { factTitle, sectionTitle } from './labels'

const str = (value: unknown): string => (typeof value === 'string' ? value : '')
const free = (value: unknown): string => {
  const text = str(value)
  return text === 'not_stated' ? '' : text
}
const known = (value: unknown): string => {
  const text = str(value)
  return text && text !== 'not_stated' ? translateEnum(text) : ''
}

/**
 * Plain-language sentence for a fact, built deterministically from its fields (no LLM, so it can
 * only say what the extraction says). Optional parts are separate messages so every language can
 * word them its own way.
 */
export function factSentence(fact: Fact): string {
  const v = fact.value
  const title = factTitle(fact)
  const derived = fact.derived ? ` ${translate('sentence.derived')}` : ''
  const status = (value: unknown) => {
    const text = known(value)
    return text ? translate('sentence.status', { status: text }) : ''
  }
  switch (fact.kind) {
    case 'patient_name':
      return translate('sentence.name', { title })
    case 'patient_birth_date':
      return translate('sentence.birthDate', { title }) + derived
    case 'patient_gender':
      return translate('sentence.gender', { title }) + derived
    case 'patient_identifier':
      return translate('sentence.identifier', { title })
    case 'allergy': {
      const reactions = (v.reactions ?? [])
        .flatMap((r: { manifestations: string[] }) => r.manifestations)
        .join(', ')
      return translate('sentence.allergy', {
        title,
        reactions: reactions ? translate('sentence.allergy.reactions', { reactions }) : '',
        status: status(v.clinical_status),
      })
    }
    case 'medication': {
      const dosage = free(v.dosage?.text)
      return translate('sentence.medication', {
        title,
        dosage: dosage ? translate('sentence.medication.dosage', { dosage }) : '',
        status: status(v.status),
      })
    }
    case 'condition': {
      const onset = free(v.onset)
      return translate('sentence.condition', {
        title,
        onset: onset ? translate('sentence.condition.onset', { onset }) : '',
        status: status(v.clinical_status),
      })
    }
    case 'no_known_allergy_statement':
    case 'section_none_known':
      return translate('sentence.noneKnown', { quote: fact.source?.quote ?? title })
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
  ].map((fact) => ({ heading: translate('patient.about'), fact }))
  const sections = draft.sections.flatMap((section) =>
    [
      ...(section.statement ? [section.statement] : []),
      ...section.items,
      ...section.scoped_statements,
    ].map((fact) => ({ heading: sectionTitle(section), fact })),
  )
  return [...about, ...sections]
}

/** Sections the document said nothing about: shown on the summary page, not as steps. */
export function silentSections(draft: Draft): string[] {
  return draft.sections
    .filter((s) => s.effective_kind === 'no_information' && s.items.length === 0)
    .map(sectionTitle)
}
