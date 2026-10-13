import type { Fact, FlagCode } from '../api/types'

export const FLAG_LABELS: Record<FlagCode, string> = {
  relocated: 'Quote found elsewhere (location corrected)',
  fuzzy_match: 'Quote is not verbatim (fuzzy match)',
  section_unverified: 'Section could not be verified against the source',
  printed_code_not_in_quote: 'Printed code was not in the quote (removed)',
  derived_from_identity_code: 'Derived from the personal identity code',
  identity_code_conflict: 'Identity code disagrees with the stated value',
  identity_code_ambiguous: 'Several different identity codes',
  assumed_status: 'Status not stated, assumed active',
  low_confidence: 'Low extraction confidence',
  edited: 'Edited by reviewer',
  other: 'Needs attention',
}

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
      return str(fact.derived?.value) || str(v.value)
    case 'no_known_allergy_statement':
    case 'section_none_known':
      return fact.source?.quote ?? 'None known'
  }
}

export function factDetails(fact: Fact): [string, string][] {
  const v = fact.value
  const out: [string, string][] = []
  const add = (label: string, value: unknown) => {
    const text = str(value)
    if (text && text !== 'not_stated') out.push([label, text.replace(/_/g, ' ')])
  }
  switch (fact.kind) {
    case 'allergy':
      add('status', v.clinical_status)
      add('category', v.category)
      add('criticality', v.criticality)
      add(
        'reactions',
        (v.reactions ?? [])
          .flatMap((r: { manifestations: string[] }) => r.manifestations)
          .join(', '),
      )
      add('onset', v.onset)
      break
    case 'medication':
      add('dosage', v.dosage?.text)
      add('form', v.dose_form_text)
      add('status', v.status)
      add('reason', v.reason_text)
      break
    case 'condition':
      add('status', v.clinical_status)
      add('verification', v.verification_status)
      add('onset', v.onset)
      add('resolved', v.abatement)
      break
    case 'no_known_allergy_statement':
    case 'section_none_known':
      add('scope', v.scope)
      break
    default:
      break
  }
  return out
}
