import type { JobEvent } from '../api/types'
import type { TKey } from './i18n'

export const STEPS: { key: string; label: TKey }[] = [
  { key: 'ingest', label: 'step.ingest' },
  { key: 'extract', label: 'step.extract' },
  { key: 'ground', label: 'step.ground' },
  { key: 'derive', label: 'step.derive' },
  { key: 'terminology', label: 'step.terminology' },
  { key: 'assemble', label: 'step.assemble' },
  { key: 'validate', label: 'step.validate' },
]

export function stepStatus(events: JobEvent[], step: string): string {
  const last = [...events].reverse().find((e) => e.step === step)
  return last?.status ?? 'waiting'
}
