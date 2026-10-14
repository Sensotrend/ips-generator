import type { Fact, FactKind, FactValue } from '../api/types'
import type { TKey } from './i18n'

interface EditField {
  key: string
  label: TKey
  options?: string[]
  /** A list of words in the data (e.g. given names), shown and typed as one space-separated string. */
  words?: boolean
  /** The expected input format, shown as the input's placeholder (the label stays short). */
  format?: TKey
}

const STATUS = ['active', 'inactive', 'resolved', 'not_stated']

const EDIT_FIELDS: Partial<Record<FactKind, EditField[]>> = {
  allergy: [
    { key: 'substance_text', label: 'field.substance' },
    { key: 'clinical_status', label: 'field.status', options: STATUS },
    {
      key: 'criticality',
      label: 'field.criticality',
      options: ['low', 'high', 'unable_to_assess', 'not_stated'],
    },
    { key: 'note', label: 'field.note' },
  ],
  medication: [
    { key: 'medication_text', label: 'field.medication' },
    { key: 'strength_text', label: 'field.strength' },
    { key: 'dosage.text', label: 'field.dosage' },
    {
      key: 'status',
      label: 'field.status',
      options: ['active', 'completed', 'stopped', 'on_hold', 'intended', 'not_taken', 'not_stated'],
    },
  ],
  condition: [
    { key: 'condition_text', label: 'field.condition' },
    { key: 'body_site_text', label: 'field.bodySite' },
    {
      key: 'clinical_status',
      label: 'field.status',
      options: [
        'active',
        'recurrence',
        'relapse',
        'inactive',
        'remission',
        'resolved',
        'not_stated',
      ],
    },
    { key: 'onset', label: 'field.onset', format: 'format.partialDate' },
  ],
  vital_sign: [
    { key: 'value', label: 'field.value' },
    { key: 'diastolic', label: 'field.diastolic' },
    { key: 'unit_text', label: 'field.unit' },
    { key: 'effective', label: 'field.date', format: 'format.partialDate' },
  ],
  social_history: [
    { key: 'use_text', label: 'field.wording' },
    {
      key: 'tobacco_status',
      label: 'field.smokingStatus',
      options: ['never', 'former', 'current', 'non_smoker', 'not_stated'],
    },
    { key: 'date', label: 'field.date', format: 'format.partialDate' },
  ],
  immunization: [
    { key: 'vaccine_text', label: 'field.vaccine' },
    { key: 'status', label: 'field.status', options: ['completed', 'not_done'] },
    { key: 'occurrence', label: 'field.date', format: 'format.partialDate' },
    { key: 'note', label: 'field.note' },
  ],
  pregnancy_fact: [
    {
      key: 'status',
      label: 'field.pregnancyStatus',
      options: ['pregnant', 'not_pregnant', 'not_stated'],
    },
    { key: 'date', label: 'field.date', format: 'format.partialDate' },
    { key: 'count', label: 'field.number' },
  ],
  patient_contact: [
    { key: 'name_text', label: 'field.contactName' },
    { key: 'relationship_text', label: 'field.relationship' },
    { key: 'phone', label: 'field.phone' },
  ],
  patient_name: [
    { key: 'given', label: 'field.givenName', words: true },
    { key: 'family', label: 'field.familyName' },
  ],
  patient_identifier: [
    { key: 'value', label: 'field.identifier' },
    { key: 'type_text', label: 'field.label' },
  ],
  patient_birth_date: [{ key: 'value', label: 'field.birthDate', format: 'format.date' }],
  patient_gender: [
    { key: 'value', label: 'field.gender', options: ['male', 'female', 'other', 'unknown'] },
  ],
}

export function getIn(value: FactValue, path: string): string {
  let node: unknown = value
  for (const key of path.split('.')) {
    node = node !== null && typeof node === 'object' ? (node as FactValue)[key] : undefined
  }
  if (Array.isArray(node)) return node.join(' ')
  if (typeof node === 'number') return String(node)
  return typeof node === 'string' ? node : ''
}

export function setIn(value: FactValue, path: string, next: string): FactValue {
  const copy = structuredClone(value)
  const keys = path.split('.')
  let node = copy
  for (const key of keys.slice(0, -1)) node = node[key]
  const last = keys[keys.length - 1]
  // A word list keeps empty entries while typing so that a trailing space survives;
  // `finalizeEdit` drops them on save.
  node[last] = Array.isArray(node[last]) ? next.split(' ') : next
  return copy
}

/** The value to send when an edit is saved: a changed name gets its full text rebuilt from the parts. */
export function finalizeEdit(fact: Fact, value: FactValue): FactValue {
  if (fact.kind !== 'patient_name') return value
  const given = ((value.given as string[] | undefined) ?? []).filter((word) => word.trim() !== '')
  const family = typeof value.family === 'string' ? value.family.trim() : ''
  const text = [...given, family].filter(Boolean).join(' ')
  const changed =
    given.join(' ') !== ((fact.value.given as string[] | undefined) ?? []).join(' ') ||
    family !== (typeof fact.value.family === 'string' ? fact.value.family : '')
  return { ...value, given, family, text: changed && text ? text : value.text }
}

export function editableFields(fact: Fact): EditField[] {
  // A derived-only value (D-10) can be confirmed or rejected, never edited.
  if (!('source_quote' in fact.value)) return []
  return EDIT_FIELDS[fact.kind] ?? []
}
