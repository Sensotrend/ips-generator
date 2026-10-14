import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { draft, draftWithExtraSections, source } from '../test-fixtures'
import { ReviewScreen } from './ReviewScreen'

function stubApi(onPut = vi.fn(), base = draft()) {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith('/draft') && init?.method === 'PUT') {
        onPut(JSON.parse(String(init.body)))
        return Promise.resolve(new Response(JSON.stringify({ ...base, version: 2 })))
      }
      if (url.endsWith('/draft')) return Promise.resolve(new Response(JSON.stringify(base)))
      if (url.endsWith('/source')) return Promise.resolve(new Response(JSON.stringify(source)))
      return Promise.resolve(new Response('{}', { status: 404 }))
    }),
  )
}

function renderReview() {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <ReviewScreen jobId="22222222-2222-2222-2222-222222222222" role="clinician" />
    </QueryClientProvider>,
  )
}

describe('ReviewScreen', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('lists the patient and sections with flags and blockers', async () => {
    stubApi()
    renderReview()
    expect(await screen.findByRole('heading', { name: 'Patient' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Allergies and intolerances' })).toBeInTheDocument()
    expect(screen.getByText('Section could not be verified against the source')).toBeInTheDocument()
    expect(screen.getByRole('list', { name: 'Approval blocked' })).toBeInTheDocument()
  })

  it('highlights the selected fact quote in the source', async () => {
    stubApi()
    renderReview()
    fireEvent.click(await screen.findByRole('button', { name: /line 3/ }))
    const sourcePane = await screen.findByRole('region', { name: 'Source document' })
    const mark = await within(sourcePane).findByText('Sulfa-antibiootit: ihottuma (2009)', {
      selector: 'mark',
    })
    expect(mark.closest('li')).toHaveTextContent('line 3')
  })

  it('sends reviewer actions with the draft version', async () => {
    const onPut = vi.fn()
    stubApi(onPut)
    renderReview()
    const allergies = within(
      await screen.findByRole('region', { name: 'Allergies and intolerances' }),
    )
    fireEvent.click(allergies.getByRole('checkbox', { name: 'Select Sulfa-antibiootit' }))
    fireEvent.click(allergies.getByRole('button', { name: 'Reject selected' }))
    await vi.waitFor(() =>
      expect(onPut).toHaveBeenCalledWith({
        version: 1,
        actions: [{ action: 'reject', path: 'allergies.items[0]' }],
      }),
    )
  })

  it('lists the optional sections and the contact person, and rejects one of their facts', async () => {
    const onPut = vi.fn()
    stubApi(onPut, draftWithExtraSections())
    renderReview()
    for (const name of ['Immunizations', 'History of pregnancy', 'Social history', 'Vital signs'])
      expect(await screen.findByRole('heading', { name })).toBeInTheDocument()
    expect(screen.getByText('Teemu Ahonen')).toBeInTheDocument()
    expect(screen.getByText('138')).toBeInTheDocument()
    expect(screen.getByText('mmHg')).toBeInTheDocument()
    expect(screen.getByText('non-smoker')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('checkbox', { name: /blood pressure 138\/84 mmHg/ }))
    fireEvent.click(
      within(screen.getByRole('region', { name: 'Vital signs' })).getByRole('button', {
        name: 'Reject selected',
      }),
    )
    await vi.waitFor(() => expect(onPut).toHaveBeenCalledTimes(1))
    expect(onPut).toHaveBeenCalledWith({
      version: 1,
      actions: [{ action: 'reject', path: 'vital_signs[0]' }],
    })
  })
})
