import { fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { fact } from '../test-fixtures'
import { FactCard } from './FactCard'

function renderCard(overrides = {}, readOnly = false) {
  const onActions = vi.fn()
  const onSelect = vi.fn()
  const f = fact(overrides)
  render(
    <FactCard
      fact={f}
      selected={false}
      readOnly={readOnly}
      busy={false}
      onSelect={onSelect}
      onActions={onActions}
    />,
  )
  return { onActions, onSelect, f }
}

describe('FactCard', () => {
  it('shows the quote, location and review flags', () => {
    renderCard()
    expect(screen.getByText('Sulfa-antibiootit')).toBeInTheDocument()
    expect(screen.getByText('p. 1, line 3:')).toBeInTheDocument()
    const flags = screen.getByRole('list', { name: 'Review flags' })
    expect(within(flags).getByText('Status not stated, assumed active')).toBeInTheDocument()
  })

  it('accepts, rejects and selects', () => {
    const { onActions, onSelect, f } = renderCard()
    fireEvent.click(screen.getByRole('button', { name: 'Accept' }))
    fireEvent.click(screen.getByRole('button', { name: 'Reject' }))
    expect(onActions.mock.calls).toEqual([
      [[{ action: 'accept', path: f.path }]],
      [[{ action: 'reject', path: f.path }]],
    ])
    fireEvent.click(screen.getByText('Sulfa-antibiootit'))
    expect(onSelect).toHaveBeenCalledWith(f)
  })

  it('selects the fact when its source quote is clicked', () => {
    const { onSelect, f } = renderCard()
    fireEvent.click(screen.getByRole('button', { name: /p\. 1, line 3/ }))
    expect(onSelect).toHaveBeenCalledWith(f)
  })

  it('confirms an assumed allergy status with the chosen value', () => {
    const { onActions, f } = renderCard()
    fireEvent.change(screen.getByLabelText('Clinical status'), { target: { value: 'resolved' } })
    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }))
    expect(onActions).toHaveBeenCalledWith([
      { action: 'confirm', path: f.path, clinical_status: 'resolved' },
    ])
  })

  it('edits text fields but keeps the provenance', () => {
    const { onActions, f } = renderCard()
    fireEvent.click(screen.getByRole('button', { name: 'Edit' }))
    fireEvent.change(screen.getByLabelText('Substance'), { target: { value: 'Sulfonamidit' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    const [[[action]]] = onActions.mock.calls
    expect(action.action).toBe('edit')
    expect(action.value.substance_text).toBe('Sulfonamidit')
    expect(action.value.source_quote).toBe(f.value.source_quote)
  })

  it('offers confirm but no edit for a derived value', () => {
    renderCard({
      path: 'patient.birth_date',
      kind: 'patient_birth_date',
      value: {},
      derived: { value: '1957-01-15', derivation: { method: 'fi-hetu' } },
      flags: ['derived_from_identity_code'],
    })
    expect(screen.getByText('1957-01-15')).toBeInTheDocument()
    expect(screen.getByText('derived')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Edit' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Confirm' })).toBeInTheDocument()
  })

  it('has no actions when read-only', () => {
    renderCard({}, true)
    expect(screen.queryByRole('button', { name: 'Accept' })).not.toBeInTheDocument()
  })
})
