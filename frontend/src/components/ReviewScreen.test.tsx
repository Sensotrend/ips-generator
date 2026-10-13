import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { draft, source } from '../test-fixtures'
import { ReviewScreen } from './ReviewScreen'

function stubApi(onPut = vi.fn()) {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith('/draft') && init?.method === 'PUT') {
        onPut(JSON.parse(String(init.body)))
        return Promise.resolve(new Response(JSON.stringify(draft({ version: 2 }))))
      }
      if (url.endsWith('/draft')) return Promise.resolve(new Response(JSON.stringify(draft())))
      if (url.endsWith('/source')) return Promise.resolve(new Response(JSON.stringify(source)))
      return Promise.resolve(new Response('{}', { status: 404 }))
    }),
  )
}

function renderReview() {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <ReviewScreen jobId="22222222-2222-2222-2222-222222222222" />
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
    fireEvent.click(await screen.findByRole('button', { name: /Sulfa-antibiootit/ }))
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
    const card = await screen.findByRole('article', { name: 'Sulfa-antibiootit' })
    fireEvent.click(within(card).getByRole('button', { name: 'Reject' }))
    await vi.waitFor(() =>
      expect(onPut).toHaveBeenCalledWith({
        version: 1,
        actions: [{ action: 'reject', path: 'allergies.items[0]' }],
      }),
    )
  })
})
