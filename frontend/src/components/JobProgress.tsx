import type { JobEvent } from '../api/types'
import { STEPS, stepStatus } from '../lib/steps'

export function JobProgress({ events }: { events: JobEvent[] }) {
  return (
    <ol className="progress" aria-label="Progress">
      {STEPS.map((step) => {
        const status = stepStatus(events, step.key)
        return (
          <li key={step.key} className={`step step-${status}`}>
            <span className="step-label">{step.label}</span>
            <span className="step-status">{status}</span>
          </li>
        )
      })}
    </ol>
  )
}
