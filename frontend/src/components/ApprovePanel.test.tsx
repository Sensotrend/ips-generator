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
}

describe('ApprovePanel', () => {
  it('is blocked while blockers remain', () => {
    render(<ApprovePanel {...base} blockers={draft().blockers} onApprove={vi.fn()} />)
    expect(screen.getByRole('list', { name: 'Approval blocked' })).toHaveTextContent(
      'birth date is missing',
    )
    fireEvent.click(screen.getByLabelText(/the patient/))
    expect(screen.getByRole('button', { name: 'Approve IPS' })).toBeDisabled()
  })

  it('needs a reviewer role and approves with it', () => {
    const onApprove = vi.fn()
    render(<ApprovePanel {...base} blockers={[]} onApprove={onApprove} />)
    const button = screen.getByRole('button', { name: 'Approve IPS' })
    expect(button).toBeDisabled()
    fireEvent.click(screen.getByLabelText(/a clinician/))
    fireEvent.click(button)
    expect(onApprove).toHaveBeenCalledWith('clinician')
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
