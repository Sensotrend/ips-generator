import type { Fact, FactKind, FactValue } from '../api/types'
import type { TKey } from './i18n'

interface EditField {
  key: string
  label: TKey
  options?: string[]
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
    { key: 'onset', label: 'field.onset' },
  ],
  patient_name: [
    { key: 'text', label: 'field.fullName' },
    { key: 'family', label: 'field.familyName' },
  ],
  patient_identifier: [
    { key: 'value', label: 'field.identifier' },
    { key: 'type_text', label: 'field.label' },
  ],
  patient_birth_date: [{ key: 'value', label: 'field.birthDate' }],
  patient_gender: [
    { key: 'value', label: 'field.gender', options: ['male', 'female', 'other', 'unknown'] },
  ],
}

export function getIn(value: FactValue, path: string): string {
  let node: unknown = value
  for (const key of path.split('.')) {
    node = node !== null && typeof node === 'object' ? (node as FactValue)[key] : undefined
  }
  return typeof node === 'string' ? node : ''
}

export function setIn(value: FactValue, path: string, next: string): FactValue {
  const copy = structuredClone(value)
  const keys = path.split('.')
  let node = copy
  for (const key of keys.slice(0, -1)) node = node[key]
  node[keys[keys.length - 1]] = next
  return copy
}

export function editableFields(fact: Fact): EditField[] {
  // A derived-only value (D-10) can be confirmed or rejected, never edited.
  if (!('source_quote' in fact.value)) return []
  return EDIT_FIELDS[fact.kind] ?? []
}
