import { fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { Fact } from '../api/types'
import { fact } from '../test-fixtures'
import { FactTable } from './FactTable'

const medication = (n: number, text: string): Fact =>
  fact({
    path: `medications.items[${n}]`,
    kind: 'medication',
    value: {
      source_quote: text,
      page: 1,
      locator: `line ${n}`,
      medication_text: text,
      strength_text: '',
      dosage: { text: '1 x 1' },
      status: 'active',
      reason_text: '',
    },
    source: { quote: text, page: 1, locator: `line ${n}` },
    needs_confirmation: false,
    flags: [],
  })

function renderTable(facts: Fact[], readOnly = false) {
  const onActions = vi.fn()
  const onSelect = vi.fn()
  render(
    <FactTable
      facts={facts}
      selected={null}
      readOnly={readOnly}
      busy={false}
      onSelect={onSelect}
      onActions={onActions}
    />,
  )
  return { onActions, onSelect }
}

describe('FactTable', () => {
  const facts = [medication(0, 'Metformiini'), medication(1, 'Simvastatiini')]

  it('labels the columns and shows each fact as values, decision and source rows', () => {
    renderTable(facts)
    for (const label of ['Medication', 'Strength', 'Dosage', 'Status', 'Actions']) {
      expect(screen.getByRole('columnheader', { name: label })).toBeInTheDocument()
    }
    expect(screen.queryByRole('columnheader', { name: 'Decision' })).not.toBeInTheDocument()
    const [values, detail, source] = within(screen.getAllByRole('rowgroup')[1]).getAllByRole('row')
    expect(within(values).getByRole('cell', { name: 'active' })).toBeInTheDocument()
    expect(within(values).getByRole('cell', { name: '1 x 1' })).toBeInTheDocument()
    expect(detail).toHaveTextContent('Decision: pending')
    expect(source).toHaveTextContent('Source: p. 1, line 0: Metformiini')
  })

  it('leaves out the source row when a fact has no source, and ticks from any row', () => {
    renderTable([{ ...facts[0], source: null }, facts[1]])
    const group = screen.getAllByRole('rowgroup')[1]
    const rows = within(group).getAllByRole('row')
    expect(rows).toHaveLength(2)
    expect(within(rows[0]).getByRole('checkbox').closest('td')).toHaveAttribute('rowspan', '2')
    fireEvent.click(within(rows[1]).getByText(/Decision/))
    expect(screen.getByRole('checkbox', { name: 'Select Metformiini' })).toBeChecked()
  })

  it('ticks a row by clicking anywhere in it and acts on the ticked rows only', () => {
    const { onActions } = renderTable(facts)
    const accept = screen.getByRole('button', { name: 'Accept selected' })
    expect(accept).toBeDisabled()
    fireEvent.click(screen.getAllByRole('cell', { name: '1 x 1' })[1])
    expect(screen.getByRole('checkbox', { name: 'Select Simvastatiini' })).toBeChecked()
    expect(screen.getByRole('checkbox', { name: 'Select Metformiini' })).not.toBeChecked()
    fireEvent.click(accept)
    expect(onActions).toHaveBeenCalledWith([{ action: 'accept', path: 'medications.items[1]' }])
    expect(screen.getByRole('checkbox', { name: 'Select Simvastatiini' })).not.toBeChecked()
  })

  it('rejects, undoes and selects all', () => {
    const { onActions } = renderTable(facts)
    fireEvent.click(screen.getByRole('checkbox', { name: 'Select all rows' }))
    fireEvent.click(screen.getByRole('button', { name: 'Reject selected' }))
    expect(onActions).toHaveBeenCalledWith([
      { action: 'reject', path: 'medications.items[0]' },
      { action: 'reject', path: 'medications.items[1]' },
    ])
    fireEvent.click(screen.getByRole('checkbox', { name: 'Select Metformiini' }))
    fireEvent.click(screen.getByRole('button', { name: 'Undo selected' }))
    expect(onActions).toHaveBeenLastCalledWith([{ action: 'reset', path: 'medications.items[0]' }])
  })

  it('edits one row in place and keeps the other cells', () => {
    const { onActions } = renderTable(facts)
    fireEvent.click(screen.getByRole('button', { name: 'Edit Metformiini' }))
    // The row being edited is not ticked by clicking in it.
    fireEvent.click(screen.getByLabelText('Dosage'))
    expect(screen.getByRole('checkbox', { name: 'Select Metformiini' })).not.toBeChecked()
    fireEvent.change(screen.getByLabelText('Dosage'), { target: { value: '2 x 1' } })
    fireEvent.change(screen.getByLabelText('Status'), { target: { value: 'stopped' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(onActions).toHaveBeenCalledWith([
      {
        action: 'edit',
        path: 'medications.items[0]',
        value: expect.objectContaining({
          medication_text: 'Metformiini',
          source_quote: 'Metformiini',
          dosage: { text: '2 x 1' },
          status: 'stopped',
        }),
      },
    ])
    expect(screen.queryByLabelText('Dosage')).not.toBeInTheDocument()
  })

  it('selects the fact in the source from the row', () => {
    const { onSelect } = renderTable(facts)
    fireEvent.click(screen.getByRole('button', { name: /line 1/ }))
    expect(onSelect).toHaveBeenCalledWith(facts[1])
    expect(screen.getByRole('checkbox', { name: 'Select Simvastatiini' })).not.toBeChecked()
  })

  it('confirms an assumed allergy status with the chosen value', () => {
    const allergy = fact()
    const { onActions } = renderTable([allergy])
    fireEvent.change(screen.getByLabelText('Clinical status'), { target: { value: 'resolved' } })
    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }))
    expect(onActions).toHaveBeenCalledWith([
      { action: 'confirm', path: allergy.path, clinical_status: 'resolved' },
    ])
  })

  it('has no checkboxes or buttons when read only', () => {
    renderTable(facts, true)
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Accept selected' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Edit/ })).not.toBeInTheDocument()
  })

  it('offers no edit for a derived-only value and shows it as a statement column', () => {
    const derived = fact({
      path: 'patient.birth_date',
      kind: 'patient_birth_date',
      value: {},
      source: null,
      derived: { value: '1990-01-02' },
      needs_confirmation: true,
      flags: [],
    })
    renderTable([derived])
    expect(screen.getByRole('cell', { name: '1990-01-02' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Edit/ })).not.toBeInTheDocument()
  })
})
