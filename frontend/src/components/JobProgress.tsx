import type { JobEvent } from '../api/types'
import { translateStatus, useT } from '../lib/i18n'
import { STEPS, stepStatus } from '../lib/steps'

export function JobProgress({ events }: { events: JobEvent[] }) {
  const { t } = useT()
  return (
    <ol className="progress" aria-label={t('job.progress')}>
      {STEPS.map((step) => {
        const status = stepStatus(events, step.key)
        return (
          <li key={step.key} className={`step step-${status}`}>
            <span className="step-label">{t(step.label)}</span>
            <span className="step-status">{translateStatus(status)}</span>
          </li>
        )
      })}
    </ol>
  )
}
