// Mirrors backend/app/schemas/api.py. Responses can contain PHI: keep them in memory only
// (TanStack Query cache), never in localStorage / IndexedDB / the service worker.

export type JobStatus = 'queued' | 'running' | 'review' | 'approved' | 'failed'

export interface JobError {
  step: string | null
  code: string
  message: string
}

export interface Job {
  id: string
  status: JobStatus
  created_at: string
  updated_at: string
  media_type: string
  size_bytes: number
  extractor: string
  current_step: string | null
  error: JobError | null
  draft_version: number | null
  approved_at: string | null
}

export interface JobEvent {
  seq: number
  step: string
  status: string
  detail: Record<string, number | string | boolean>
  at: string
}

export interface Segment {
  page: number
  locator: string | null
  text: string
}

export interface Source {
  media_type: string
  page_count: number
  pages_without_text: number[]
  segments: Segment[]
  original_url: string | null
  /** JSON documents: the document as compact JSON, for the raw-JSON view. */
  json_text?: string | null
}

export type Decision = 'pending' | 'accepted' | 'edited' | 'rejected'

export type FlagCode =
  | 'relocated'
  | 'fuzzy_match'
  | 'section_unverified'
  | 'printed_code_not_in_quote'
  | 'derived_from_identity_code'
  | 'identity_code_conflict'
  | 'identity_code_ambiguous'
  | 'assumed_status'
  | 'low_confidence'
  | 'edited'
  | 'other'

export interface SourceRef {
  quote: string
  page: number
  locator: string | null
}

export interface Note {
  code: string
  message: string
  severity: 'info' | 'warning'
}

export type FactKind =
  | 'patient_name'
  | 'patient_identifier'
  | 'patient_birth_date'
  | 'patient_gender'
  | 'allergy'
  | 'medication'
  | 'condition'
  | 'vital_sign'
  | 'social_history'
  | 'immunization'
  | 'pregnancy_fact'
  | 'patient_contact'
  | 'no_known_allergy_statement'
  | 'section_none_known'

/* eslint-disable @typescript-eslint/no-explicit-any -- fact values mirror the backend schema */
export type FactValue = Record<string, any>
/* eslint-enable @typescript-eslint/no-explicit-any */

export interface Fact {
  path: string
  item_id: string | null
  kind: FactKind
  value: FactValue
  pipeline_value: FactValue | null
  source: SourceRef | null
  derived: FactValue | null
  decision: Decision
  needs_confirmation: boolean
  confirmed: boolean
  flags: FlagCode[]
  notes: Note[]
  codings: FactValue[]
}

export type SectionKind = 'items_found' | 'none_known' | 'no_information'
export type SectionKey =
  | 'allergies'
  | 'medications'
  | 'problems'
  | 'past_illness'
  | 'immunizations'
  | 'pregnancy'
  | 'social_history'
  | 'vital_signs'

export interface Section {
  key: SectionKey
  title: string
  kind: SectionKind
  effective_kind: SectionKind
  statement: Fact | null
  items: Fact[]
  scoped_statements: Fact[]
  flags: FlagCode[]
}

export interface Patient {
  names: Fact[]
  identifiers: Fact[]
  contacts: Fact[]
  birth_date: Fact | null
  gender: Fact | null
  flags: FlagCode[]
}

export interface Blocker {
  code: 'patient_name_missing' | 'patient_birth_date_missing' | 'derived_value_unconfirmed'
  path: string | null
  message: string
}

export interface ValidationSummary {
  profile: string
  errors: number
  warnings: number
  unmatched_entries: number[]
  passed: boolean
  issues: { severity: string; message_id: string | null; path: string }[]
}

/** The summary as a document: who made it, when, and who attested it. */
export interface DocumentInfo {
  software: string
  software_version: string
  ai_assisted: boolean
  created_at: string
  approved_at: string | null
  attester_mode: 'personal' | 'professional' | null
}

export interface Draft {
  job_id: string
  version: number
  status: JobStatus
  document_language: string
  document: DocumentInfo
  patient: Patient
  sections: Section[]
  notes: Note[]
  dropped_paths: string[]
  blockers: Blocker[]
  validation: ValidationSummary | null
  validation_error: string | null
}

export type ReviewAction =
  | { action: 'accept' | 'reject' | 'reset'; path: string }
  | { action: 'edit'; path: string; value: FactValue }
  | { action: 'confirm'; path: string; clinical_status?: 'active' | 'inactive' | 'resolved' }

export type ReviewerRole = 'patient' | 'clinician'

export interface Approval {
  job_id: string
  approved_at: string
  approved_by: string
  attester_mode: 'personal' | 'professional'
  validation: ValidationSummary | null
  ips_url: string
}

export interface ApiErrorBody {
  error: { code: string; message: string; details: Record<string, unknown>[] }
}
