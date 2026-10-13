// Synthetic test data only (no real patients).
import type { Draft, Fact, Source } from './api/types'

export function fact(overrides: Partial<Fact> = {}): Fact {
  return {
    path: 'allergies.items[0]',
    item_id: '11111111-1111-1111-1111-111111111111',
    kind: 'allergy',
    value: {
      source_quote: 'Sulfa-antibiootit: ihottuma (2009)',
      page: 1,
      locator: 'line 3',
      substance_text: 'Sulfa-antibiootit',
      clinical_status: 'not_stated',
      criticality: 'not_stated',
      category: 'medication',
      reactions: [{ manifestations: ['ihottuma'], severity: 'not_stated' }],
      note: null,
    },
    pipeline_value: null,
    source: { quote: 'Sulfa-antibiootit: ihottuma (2009)', page: 1, locator: 'line 3' },
    derived: null,
    decision: 'pending',
    needs_confirmation: true,
    confirmed: false,
    flags: ['assumed_status'],
    notes: [],
    codings: [],
    ...overrides,
  }
}

export const source: Source = {
  media_type: 'text/plain',
  page_count: 1,
  pages_without_text: [],
  original_url: null,
  segments: [
    { page: 1, locator: 'line 1', text: 'Potilas: TESTINEN, Aino' },
    { page: 1, locator: 'line 2', text: 'ALLERGIAT' },
    { page: 1, locator: 'line 3', text: 'Sulfa-antibiootit: ihottuma (2009)' },
  ],
}

export function draft(overrides: Partial<Draft> = {}): Draft {
  const name = fact({
    path: 'patient.names[0]',
    item_id: null,
    kind: 'patient_name',
    value: { source_quote: 'TESTINEN, Aino', page: 1, locator: 'line 1', text: 'TESTINEN, Aino' },
    source: { quote: 'TESTINEN, Aino', page: 1, locator: 'line 1' },
    needs_confirmation: false,
    flags: [],
  })
  return {
    job_id: '22222222-2222-2222-2222-222222222222',
    version: 1,
    status: 'review',
    document_language: 'fi',
    document: {
      software: 'IPS Generator extraction pipeline',
      software_version: '0.1.0',
      ai_assisted: true,
      created_at: '2026-10-13T09:30:00Z',
      approved_at: null,
      attester_mode: null,
    },
    patient: { names: [name], identifiers: [], birth_date: null, gender: null, flags: [] },
    sections: [
      {
        key: 'allergies',
        title: 'Allergies and intolerances',
        kind: 'items_found',
        effective_kind: 'items_found',
        statement: null,
        items: [fact()],
        scoped_statements: [],
        flags: [],
      },
      {
        key: 'medications',
        title: 'Medication summary',
        kind: 'no_information',
        effective_kind: 'no_information',
        statement: null,
        items: [],
        scoped_statements: [],
        flags: ['section_unverified'],
      },
    ],
    notes: [],
    dropped_paths: [],
    blockers: [
      {
        code: 'patient_birth_date_missing',
        path: 'patient.birth_date',
        message: "The patient's birth date is missing.",
      },
    ],
    validation: null,
    validation_error: null,
    ...overrides,
  }
}
