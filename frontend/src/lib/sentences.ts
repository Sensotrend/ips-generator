import type { Draft, Fact } from '../api/types'
import { translate, translateEnum, type TKey } from './i18n'
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

export interface ReviewGroup {
  /** `patient` or the section key. */
  key: string
  heading: string
  /** Why the section exists, from the IPS standard (message key). */
  intro: TKey
  facts: Fact[]
  /** The document said nothing about this section. */
  silent: boolean
}

/** Facts about the patient, then one group per IPS section, in IPS order. */
export function reviewGroups(draft: Draft): ReviewGroup[] {
  const patient = draft.patient
  const about: ReviewGroup = {
    key: 'patient',
    heading: translate('patient.about'),
    intro: 'section.intro.patient',
    facts: [
      ...patient.names,
      ...(patient.birth_date ? [patient.birth_date] : []),
      ...(patient.gender ? [patient.gender] : []),
      ...patient.identifiers,
    ],
    silent: false,
  }
  const sections = draft.sections.map((section) => ({
    key: section.key,
    heading: sectionTitle(section),
    intro: `section.intro.${section.key}` as TKey,
    facts: [
      ...(section.statement ? [section.statement] : []),
      ...section.items,
      ...section.scoped_statements,
    ],
    silent: section.effective_kind === 'no_information' && section.items.length === 0,
  }))
  return [about, ...sections]
}
