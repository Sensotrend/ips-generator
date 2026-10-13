import type { Fact, FlagCode, Section } from '../api/types'
import { en } from '../locales/en'
import { translate, translateEnum, type TKey } from './i18n'

export const flagLabel = (flag: FlagCode): string => translate(`flag.${flag}`)

/** Section heading in the interface language; the server's title if the key is unknown. */
export const sectionTitle = (section: Section): string =>
  `section.${section.key}` in en ? translate(`section.${section.key}` as TKey) : section.title

/** Flags that need the reviewer's attention (others are informational). */
export const WARNING_FLAGS = new Set<FlagCode>([
  'fuzzy_match',
  'section_unverified',
  'printed_code_not_in_quote',
  'derived_from_identity_code',
  'identity_code_conflict',
  'identity_code_ambiguous',
  'assumed_status',
  'low_confidence',
])

const str = (value: unknown): string => (typeof value === 'string' ? value : '')

export function factTitle(fact: Fact): string {
  const v = fact.value
  switch (fact.kind) {
    case 'allergy':
      return str(v.substance_text)
    case 'medication':
      return [str(v.medication_text), str(v.strength_text)].filter(Boolean).join(' ')
    case 'condition':
      return [str(v.condition_text), str(v.body_site_text)].filter(Boolean).join(', ')
    case 'patient_name':
      return str(v.text)
    case 'patient_identifier':
      return [str(v.type_text), str(v.value)].filter(Boolean).join(': ')
    case 'patient_birth_date':
      return str(fact.derived?.value) || str(v.value)
    case 'patient_gender':
      return translateEnum(str(fact.derived?.value) || str(v.value))
    case 'no_known_allergy_statement':
    case 'section_none_known':
      return fact.source?.quote ?? translate('fact.noneKnown')
  }
}

export function factDetails(fact: Fact): [string, string][] {
  const v = fact.value
  const out: [string, string][] = []
  // `free` values are document text; the others are backend enums, shown in the interface language.
  const add = (label: TKey, value: unknown, free = false) => {
    const text = str(value)
    if (text && text !== 'not_stated')
      out.push([translate(label), free ? text : translateEnum(text)])
  }
  switch (fact.kind) {
    case 'allergy':
      add('detail.status', v.clinical_status)
      add('detail.category', v.category)
      add('detail.criticality', v.criticality)
      add(
        'detail.reactions',
        (v.reactions ?? [])
          .flatMap((r: { manifestations: string[] }) => r.manifestations)
          .join(', '),
        true,
      )
      add('detail.onset', v.onset, true)
      break
    case 'medication':
      add('detail.dosage', v.dosage?.text, true)
      add('detail.form', v.dose_form_text, true)
      add('detail.status', v.status)
      add('detail.reason', v.reason_text, true)
      break
    case 'condition':
      add('detail.status', v.clinical_status)
      add('detail.verification', v.verification_status)
      add('detail.onset', v.onset, true)
      add('detail.resolved', v.abatement, true)
      break
    case 'no_known_allergy_statement':
    case 'section_none_known':
      add('detail.scope', v.scope)
      break
    default:
      break
  }
  return out
}
