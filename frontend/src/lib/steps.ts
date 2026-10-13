import type { JobEvent } from '../api/types'

export const STEPS: { key: string; label: string }[] = [
  { key: 'ingest', label: 'Read document' },
  { key: 'extract', label: 'Extract facts' },
  { key: 'ground', label: 'Check quotes against the source' },
  { key: 'derive', label: 'Derive from identity code' },
  { key: 'terminology', label: 'Code terminology' },
  { key: 'assemble', label: 'Build FHIR IPS' },
  { key: 'validate', label: 'Validate against the IPS IG' },
]

export function stepStatus(events: JobEvent[], step: string): string {
  const last = [...events].reverse().find((e) => e.step === step)
  return last?.status ?? 'waiting'
}
