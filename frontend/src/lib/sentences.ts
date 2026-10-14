import type { Draft, Fact } from '../api/types'
import { translate, translateEnum, type TKey } from './i18n'
import { factTitle, sectionTitle } from './labels'

const str = (value: unknown): string => (typeof value === 'string' ? value : '')
const day = (value: unknown): string => (typeof value === 'string' ? value : '')
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
    case 'document_date':
      return translate('sentence.documentDate', { title })
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
    case 'vital_sign': {
      const date = day(v.effective)
      return translate('sentence.vitalSign', {
        title,
        date: date ? translate('sentence.vitalSign.date', { date }) : '',
      })
    }
    case 'social_history':
      return translate(
        v.kind === 'alcohol' ? 'sentence.social.alcohol' : 'sentence.social.tobacco',
        { text: str(v.use_text) },
      )
    case 'immunization': {
      const date = day(v.occurrence)
      return translate('sentence.immunization', {
        title: str(v.vaccine_text),
        date: date ? translate('sentence.immunization.date', { date }) : '',
        status:
          v.status === 'not_done' ? translate('sentence.status', { status: known(v.status) }) : '',
      })
    }
    case 'pregnancy_fact':
      return translate('sentence.pregnancy', { title })
    case 'patient_contact':
      return translate('sentence.contact', { title })
    case 'no_known_allergy_statement':
    case 'section_none_known':
      return translate('sentence.noneKnown', { quote: fact.source?.quote ?? title })
  }
}

const COMPLETED_STATUSES = new Set([
  'completed',
  'stopped',
  'not_taken',
  'inactive',
  'remission',
  'resolved',
])

/** Past item: an end date, or a status that says it no longer applies. */
export function isCompleted(fact: Fact): boolean {
  const v = fact.value
  switch (fact.kind) {
    case 'medication':
      return COMPLETED_STATUSES.has(str(v.status)) || str(v.effective_end) !== ''
    case 'condition':
      return COMPLETED_STATUSES.has(str(v.clinical_status)) || str(v.abatement) !== ''
    case 'allergy':
      return COMPLETED_STATUSES.has(str(v.clinical_status))
    default:
      return false
  }
}

/** The date an item started (partial dates `YYYY`, `YYYY-MM` sort correctly as text). */
const startDate = (fact: Fact): string =>
  str(
    fact.kind === 'medication'
      ? fact.value.effective_start
      : fact.kind === 'vital_sign'
        ? fact.value.effective
        : fact.kind === 'immunization'
          ? fact.value.occurrence
          : fact.value.onset,
  )

/**
 * Items with a date: current ones first, completed ones after; newest first within each; items
 * without a date keep their document order at the end of their group.
 */
export function sortByDate(facts: Fact[]): Fact[] {
  const rank = (fact: Fact) => (isCompleted(fact) ? 1 : 0)
  return facts
    .map((fact, order) => ({ fact, order }))
    .sort((a, b) => {
      const byState = rank(a.fact) - rank(b.fact)
      if (byState !== 0) return byState
      const [da, db] = [startDate(a.fact), startDate(b.fact)]
      if (da !== db) return da === '' ? 1 : db === '' ? -1 : da < db ? 1 : -1
      return a.order - b.order
    })
    .map(({ fact }) => fact)
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

/**
 * Facts about the patient (and the document date, which dates the undated facts), then one
 * group per IPS section, in IPS order.
 */
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
      ...patient.contacts,
      ...(draft.document_date ? [draft.document_date] : []),
    ],
    silent: false,
  }
  const sections = draft.sections.map((section) => ({
    key: section.key,
    heading: sectionTitle(section),
    intro: `section.intro.${section.key}` as TKey,
    facts: [
      ...(section.statement ? [section.statement] : []),
      ...sortByDate(section.items),
      ...section.scoped_statements,
    ],
    silent: section.effective_kind === 'no_information' && section.items.length === 0,
  }))
  return [about, ...sections]
}
