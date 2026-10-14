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
    patient: {
      names: [name],
      identifiers: [],
      contacts: [],
      birth_date: null,
      gender: null,
      flags: [],
    },
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

/** A fact of one of the optional sections (vital signs, social history, immunizations, ...). */
export function extraFact(
  kind: Fact['kind'],
  path: string,
  value: Fact['value'],
  quote: string,
): Fact {
  return fact({
    path,
    kind,
    item_id: kind === 'patient_contact' ? null : '33333333-3333-3333-3333-333333333333',
    value: { source_quote: quote, page: 1, locator: 'line 2', confidence: 'high', ...value },
    source: { quote, page: 1, locator: 'line 2' },
    needs_confirmation: false,
    flags: [],
  })
}

/** A draft with all the optional sections and a contact person, in IPS order. */
export function draftWithExtraSections(): Draft {
  const base = draft()
  const section = (key: Draft['sections'][number]['key'], title: string, items: Fact[]) => ({
    key,
    title,
    kind: 'items_found' as const,
    effective_kind: 'items_found' as const,
    statement: null,
    items,
    scoped_statements: [],
    flags: [],
  })
  const contact = extraFact(
    'patient_contact',
    'patient.contacts[0]',
    { name_text: 'Teemu Ahonen', relationship_text: 'puoliso', phone: '040 000 0005' },
    'Teemu Ahonen (puoliso), puh. 040 000 0005',
  )
  return {
    ...base,
    patient: { ...base.patient, contacts: [contact] },
    sections: [
      ...base.sections,
      section('immunizations', 'Immunizations', [
        extraFact(
          'immunization',
          'immunizations[0]',
          { vaccine_text: 'MPR-rokote', status: 'completed', occurrence: '1996', note: null },
          'MPR-rokote 1996',
        ),
      ]),
      section('pregnancy', 'History of pregnancy', [
        extraFact(
          'pregnancy_fact',
          'pregnancy[0]',
          { kind: 'expected_delivery_date', status: 'not_stated', date: '2027-01-31', count: null },
          'lasketun ajan arvio 31.01.2027',
        ),
        extraFact(
          'pregnancy_fact',
          'pregnancy[1]',
          { kind: 'deliveries', status: 'not_stated', date: null, count: 1 },
          'synnytyksiä 1',
        ),
      ]),
      section('social_history', 'Social history', [
        extraFact(
          'social_history',
          'social_history[0]',
          { kind: 'tobacco', tobacco_status: 'non_smoker', use_text: 'Ei tupakoi', date: null },
          'Ei tupakoi',
        ),
      ]),
      section('vital_signs', 'Vital signs', [
        extraFact(
          'vital_sign',
          'vital_signs[0]',
          {
            kind: 'blood_pressure',
            value: '138',
            diastolic: '84',
            unit_text: 'mmHg',
            effective: '2026-10-06',
            note: null,
          },
          'Verenpaine 138/84 mmHg',
        ),
      ]),
    ],
  }
}
