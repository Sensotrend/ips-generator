import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { JobEvent } from '../api/types'
import { JobProgress } from './JobProgress'

const at = '2026-10-13T10:00:00Z'

describe('JobProgress', () => {
  it('shows the latest status of each step', () => {
    const events: JobEvent[] = [
      { seq: 1, step: 'job', status: 'queued', detail: {}, at },
      { seq: 2, step: 'ingest', status: 'started', detail: {}, at },
      { seq: 3, step: 'ingest', status: 'completed', detail: { pages: 1 }, at },
      { seq: 4, step: 'extract', status: 'started', detail: {}, at },
      { seq: 5, step: 'derive', status: 'skipped', detail: {}, at },
    ]
    render(<JobProgress events={events} />)
    const items = screen.getAllByRole('listitem').map((li) => li.textContent)
    expect(items[0]).toBe('Read documentcompleted')
    expect(items[1]).toBe('Extract factsstarted')
    expect(items[3]).toBe('Derive from identity codeskipped')
    expect(items[6]).toBe('Validate against the IPS IGwaiting')
  })
})
