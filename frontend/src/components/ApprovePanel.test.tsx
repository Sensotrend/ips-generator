import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ApiError } from '../api/client'
import { draft } from '../test-fixtures'
import { ApprovePanel } from './ApprovePanel'

const base = {
  jobId: 'j',
  approved: false,
  busy: false,
  error: null,
  validation: null,
  role: 'clinician' as const,
}

describe('ApprovePanel', () => {
  it('is blocked while blockers remain', () => {
    render(<ApprovePanel {...base} blockers={draft().blockers} onApprove={vi.fn()} />)
    expect(screen.getByRole('list', { name: 'Approval blocked' })).toHaveTextContent(
      'birth date is missing',
    )
    expect(screen.getByRole('button', { name: 'Approve IPS' })).toBeDisabled()
  })

  it('approves with the role chosen at the start', () => {
    const onApprove = vi.fn()
    render(<ApprovePanel {...base} role="patient" blockers={[]} onApprove={onApprove} />)
    fireEvent.click(screen.getByRole('button', { name: 'Approve my summary' }))
    expect(onApprove).toHaveBeenCalledWith('patient')
  })

  it('explains a validation failure', () => {
    const error = new ApiError(422, 'validation_failed', 'x', [])
    render(<ApprovePanel {...base} blockers={[]} error={error} onApprove={vi.fn()} />)
    expect(screen.getByRole('alert')).toHaveTextContent('did not pass validation')
  })

  it('offers the download once approved', () => {
    render(<ApprovePanel {...base} approved blockers={[]} onApprove={vi.fn()} />)
    expect(screen.getByRole('button', { name: 'Download IPS (FHIR JSON)' })).toBeInTheDocument()
  })
})
