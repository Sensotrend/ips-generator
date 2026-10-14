import type { Fact, FactValue, FlagCode, Section } from '../api/types'
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
/** Decimals arrive as strings and counts as numbers. */
const num = (value: unknown): string =>
  typeof value === 'string' || typeof value === 'number' ? String(value) : ''

/** `138/84 mmHg`, `178 cm`: the number(s) and the unit as written. */
function vitalValue(v: FactValue): string {
  const value = num(v.value) + (num(v.diastolic) ? `/${num(v.diastolic)}` : '')
  return [value, str(v.unit_text)].filter(Boolean).join(' ')
}

/** `112 g/l`, `>90 ml/min`, `positive`: the result as the document gives it. */
function resultValue(v: FactValue): string {
  const bound = { lt: '<', le: '≤', ge: '≥', gt: '>' }[str(v.comparator)] ?? ''
  const number = num(v.value) ? `${bound}${num(v.value)}` : str(v.value_text)
  return [number, num(v.value) ? str(v.unit_text) : ''].filter(Boolean).join(' ')
}

/** The value a pregnancy fact carries, whichever kind it is. */
function pregnancyValue(v: FactValue): string {
  if (str(v.status) && str(v.status) !== 'not_stated') return translateEnum(str(v.status))
  return str(v.date) || num(v.count)
}

export function factTitle(fact: Fact): string {
  const v = fact.value
  switch (fact.kind) {
    case 'allergy':
      return str(v.substance_text)
    case 'medication':
      return [str(v.medication_text), str(v.strength_text)].filter(Boolean).join(' ')
    case 'condition':
      return [str(v.condition_text), str(v.body_site_text)].filter(Boolean).join(', ')
    case 'vital_sign':
      return `${translateEnum(str(v.kind))} ${vitalValue(v)}`.trim()
    case 'social_history':
      return `${translateEnum(str(v.kind))}: ${str(v.use_text)}`
    case 'immunization':
      return [str(v.vaccine_text), str(v.occurrence)].filter(Boolean).join(' ')
    case 'pregnancy_fact':
      return `${translateEnum(str(v.kind))}: ${pregnancyValue(v)}`
    case 'result':
      return [str(v.test_text), resultValue(v)].filter(Boolean).join(' ')
    case 'procedure':
      return [str(v.procedure_text), str(v.body_site_text), str(v.performed)]
        .filter(Boolean)
        .join(' ')
    case 'device':
      return [str(v.device_text), str(v.brand_text)].filter(Boolean).join(' ')
    case 'patient_contact':
      return [str(v.name_text), str(v.relationship_text) && `(${str(v.relationship_text)})`]
        .filter(Boolean)
        .join(' ')
    case 'patient_name':
      return str(v.text)
    case 'patient_identifier':
      return [str(v.type_text), str(v.value)].filter(Boolean).join(': ')
    case 'patient_birth_date':
      return str(fact.derived?.value) || str(v.value)
    case 'patient_gender':
      return translateEnum(str(fact.derived?.value) || str(v.value))
    case 'document_date':
      return str(v.value)
    case 'no_known_allergy_statement':
    case 'section_none_known':
      return fact.source?.quote ?? translate('fact.noneKnown')
  }
}

/**
 * The rows of a fact's table in the patient view: the elements that end up in the IPS resource,
 * labelled after the IPS profile elements (`[label, value]`). The first row is the main value.
 */
export function factRows(fact: Fact): [string, string][] {
  const v = fact.value
  const out: [string, string][] = []
  const add = (label: TKey, value: unknown, free = false) => {
    const text = str(value)
    if (text && text !== 'not_stated')
      out.push([translate(label), free ? text : translateEnum(text)])
  }
  switch (fact.kind) {
    case 'vital_sign':
      add('row.measurement', v.kind)
      add('row.value', vitalValue(v), true)
      add('row.date', v.effective, true)
      add('row.note', v.note, true)
      break
    case 'social_history':
      add('row.socialTopic', v.kind)
      add('row.smokingStatus', v.tobacco_status)
      add('row.asWritten', v.use_text, true)
      add('row.date', v.date, true)
      break
    case 'immunization':
      add('row.vaccine', v.vaccine_text, true)
      add('row.status', v.status)
      add('row.date', v.occurrence, true)
      add('row.note', v.note, true)
      break
    case 'pregnancy_fact':
      add('row.pregnancyFact', v.kind)
      add('row.value', pregnancyValue(v), true)
      add('row.note', v.note, true)
      break
    case 'result':
      add('row.test', v.test_text, true)
      add('row.value', resultValue(v), true)
      add('row.date', v.effective, true)
      add('row.note', v.note, true)
      break
    case 'procedure':
      add('row.procedure', v.procedure_text, true)
      add('row.bodySite', v.body_site_text, true)
      add('row.date', v.performed, true)
      add('row.note', v.note, true)
      break
    case 'device':
      add('row.device', v.device_text, true)
      add('row.brand', v.brand_text, true)
      add('row.note', v.note, true)
      break
    case 'patient_contact':
      add('row.contactName', v.name_text, true)
      add('row.relationship', v.relationship_text, true)
      add('row.phone', v.phone, true)
      break
    case 'patient_name':
      add('row.name', v.text, true)
      break
    case 'patient_identifier':
      out.push([str(v.type_text) || translate('row.identifier'), str(v.value)])
      break
    case 'patient_birth_date':
      add('row.birthDate', fact.derived?.value ?? v.value, true)
      break
    case 'patient_gender':
      add('row.sex', fact.derived?.value ?? v.value)
      break
    case 'document_date':
      add('row.documentDate', v.value, true)
      break
    case 'allergy':
      add('row.allergy', v.substance_text, true)
      add('row.type', v.type)
      add('row.category', v.category)
      add('row.criticality', v.criticality)
      // FHIR requires a clinical status; the mapper uses "active" when the document is silent.
      add(
        'row.clinicalStatus',
        str(v.clinical_status) === 'not_stated' ? 'active' : v.clinical_status,
      )
      add('row.verificationStatus', v.verification_status)
      for (const r of v.reactions ?? []) {
        const severity =
          str(r.severity) && str(r.severity) !== 'not_stated'
            ? ` (${translateEnum(str(r.severity))})`
            : ''
        add('row.reaction', `${(r.manifestations ?? []).join(', ')}${severity}`, true)
      }
      add('row.onset', v.onset, true)
      add('row.note', v.note, true)
      break
    case 'medication':
      add('row.medication', factTitle(fact), true)
      add('row.doseForm', v.dose_form_text, true)
      add('row.dosage', v.dosage?.text, true)
      add('row.status', v.status)
      if (str(v.effective_start) || str(v.effective_end))
        add('row.period', `${str(v.effective_start)} – ${str(v.effective_end)}`.trim(), true)
      add('row.reason', v.reason_text, true)
      add('row.note', v.note, true)
      break
    case 'condition':
      add('row.problem', v.condition_text, true)
      add('row.bodySite', v.body_site_text, true)
      // A condition without a stated status is on the Problem List, where the mapper
      // assumes "active" (D-15).
      add(
        'row.clinicalStatus',
        str(v.clinical_status) === 'not_stated' ? 'active' : v.clinical_status,
      )
      add('row.verificationStatus', v.verification_status)
      add('row.severity', v.severity)
      add('row.onset', v.onset, true)
      add('row.abatement', v.abatement, true)
      add('row.note', v.note, true)
      break
    case 'no_known_allergy_statement':
    case 'section_none_known':
      // IPS has no "statement" element: "no known …" is an entry whose code says so, in the
      // same element as a real entry (AllergyIntolerance.code, MedicationStatement.medication[x],
      // Condition.code). The scope only selects which fixed code is used.
      add(NONE_KNOWN_LABEL[fact.path.split(/[.[]/)[0]] ?? 'row.allergy', factTitle(fact), true)
      break
  }
  return out
}

const NONE_KNOWN_LABEL: Record<string, TKey> = {
  allergies: 'row.allergy',
  medications: 'row.medication',
  problems: 'row.problem',
}

/**
 * Facts of one section as a table: the row labels are the columns, each fact is a row. Facts of
 * different kinds have different columns, so each kind gets its own table.
 */
export function factTables(
  facts: Fact[],
): { columns: string[]; rows: { path: string; cells: string[] }[] }[] {
  const byKind = new Map<string, Fact[]>()
  for (const fact of facts) byKind.set(fact.kind, [...(byKind.get(fact.kind) ?? []), fact])
  return [...byKind.values()].map((group) => {
    const columns: string[] = []
    const parsed = group.map((fact) => {
      const cells = new Map<string, string>()
      for (const [label, value] of factRows(fact)) {
        if (!columns.includes(label)) columns.push(label)
        // A label can repeat (one reaction row per reaction): join the values.
        cells.set(label, cells.has(label) ? `${cells.get(label)}; ${value}` : value)
      }
      return { path: fact.path, cells }
    })
    return {
      columns,
      rows: parsed.map(({ path, cells }) => ({
        path,
        cells: columns.map((column) => cells.get(column) ?? '–'),
      })),
    }
  })
}
