import type { Fact, FactKind, FactValue } from '../api/types'

interface EditField {
  key: string
  label: string
  options?: string[]
}

const STATUS = ['active', 'inactive', 'resolved', 'not_stated']

const EDIT_FIELDS: Partial<Record<FactKind, EditField[]>> = {
  allergy: [
    { key: 'substance_text', label: 'Substance' },
    { key: 'clinical_status', label: 'Status', options: STATUS },
    {
      key: 'criticality',
      label: 'Criticality',
      options: ['low', 'high', 'unable_to_assess', 'not_stated'],
    },
    { key: 'note', label: 'Note' },
  ],
  medication: [
    { key: 'medication_text', label: 'Medication' },
    { key: 'strength_text', label: 'Strength' },
    { key: 'dosage.text', label: 'Dosage' },
    {
      key: 'status',
      label: 'Status',
      options: ['active', 'completed', 'stopped', 'on_hold', 'intended', 'not_taken', 'not_stated'],
    },
  ],
  condition: [
    { key: 'condition_text', label: 'Condition' },
    { key: 'body_site_text', label: 'Body site' },
    {
      key: 'clinical_status',
      label: 'Status',
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
    { key: 'onset', label: 'Onset (YYYY[-MM[-DD]])' },
  ],
  patient_name: [
    { key: 'text', label: 'Full name' },
    { key: 'family', label: 'Family name' },
  ],
  patient_identifier: [
    { key: 'value', label: 'Identifier' },
    { key: 'type_text', label: 'Label' },
  ],
  patient_birth_date: [{ key: 'value', label: 'Birth date (YYYY-MM-DD)' }],
  patient_gender: [
    { key: 'value', label: 'Gender', options: ['male', 'female', 'other', 'unknown'] },
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
