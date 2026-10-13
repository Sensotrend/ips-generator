import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Draft } from '../api/types'
import { draft } from '../test-fixtures'
import { PatientReview } from './PatientReview'

function stubApi(onPut = vi.fn(), base: Draft = draft()) {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith('/draft') && init?.method === 'PUT') {
        const body = JSON.parse(String(init.body)) as { version: number }
        onPut(body)
        return Promise.resolve(new Response(JSON.stringify({ ...base, version: body.version + 1 })))
      }
      if (url.endsWith('/draft')) return Promise.resolve(new Response(JSON.stringify(base)))
      return Promise.resolve(new Response('{}', { status: 404 }))
    }),
  )
}

function renderReview() {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <PatientReview jobId="22222222-2222-2222-2222-222222222222" />
    </QueryClientProvider>,
  )
}

describe('PatientReview', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('shows one section at a time with its explainer and three-part boxes', async () => {
    stubApi()
    renderReview()
    expect(await screen.findByRole('heading', { name: 'About you' })).toBeInTheDocument()
    expect(screen.getByText(/Who the summary is about/)).toBeInTheDocument()
    expect(screen.getByText(/Step 1 of 2/)).toBeInTheDocument()
    expect(screen.getByText('Goes into your summary')).toBeInTheDocument()
    expect(screen.getByText('Your name is TESTINEN, Aino.')).toBeInTheDocument()
    expect(screen.getByText('Source in the document · line 1')).toBeInTheDocument()
    expect(screen.getByText('TESTINEN, Aino', { selector: 'q' })).toBeInTheDocument()
  })

  it('sends the answer, stays on the section, and moves on with Next', async () => {
    const onPut = vi.fn()
    stubApi(onPut)
    renderReview()
    fireEvent.click(await screen.findByRole('button', { name: 'Yes, that is right' }))
    await vi.waitFor(() => expect(onPut).toHaveBeenCalledTimes(1))
    expect(onPut).toHaveBeenCalledWith({
      version: 1,
      actions: [{ action: 'accept', path: 'patient.names[0]' }],
    })
    expect(screen.getByRole('heading', { name: 'About you' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Next section →' }))
    expect(
      await screen.findByText(/allergy or intolerance to Sulfa-antibiootit/),
    ).toBeInTheDocument()
  })

  it('confirms an assumed allergy status together with accepting it', async () => {
    const onPut = vi.fn()
    stubApi(onPut)
    renderReview()
    fireEvent.click(await screen.findByRole('button', { name: 'Next section →' }))
    await screen.findByText(/allergy or intolerance/)
    fireEvent.click(screen.getByRole('button', { name: 'Yes, that is right' }))
    await vi.waitFor(() => expect(onPut).toHaveBeenCalledTimes(1))
    expect(onPut).toHaveBeenLastCalledWith({
      version: 1,
      actions: [
        { action: 'accept', path: 'allergies.items[0]' },
        { action: 'confirm', path: 'allergies.items[0]', clinical_status: 'active' },
      ],
    })
  })

  it('ends on the whole summary with only approved facts and a notice for unreviewed ones', async () => {
    const base = draft()
    base.patient.names[0] = { ...base.patient.names[0], decision: 'accepted' }
    stubApi(vi.fn(), base)
    renderReview()
    fireEvent.click(await screen.findByRole('button', { name: 'Next section →' }))
    fireEvent.click(screen.getByRole('button', { name: 'Next section →' }))
    expect(
      await screen.findByRole('heading', { name: 'Your summary is ready' }),
    ).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'About you' })).toBeInTheDocument()
    expect(screen.getByText('Name')).toBeInTheDocument()
    expect(screen.getByText('TESTINEN, Aino')).toBeInTheDocument()
    // The allergy was never answered: it is left out, and the section says so.
    expect(screen.queryByText('Sulfa-antibiootit')).not.toBeInTheDocument()
    expect(screen.getAllByRole('alert')).toHaveLength(1)
    expect(screen.getByText(/1 item in this section has not been reviewed/)).toBeInTheDocument()
    expect(screen.queryByText('What it means')).not.toBeInTheDocument()
    // A section the document says nothing about is still listed.
    expect(screen.getByRole('heading', { name: 'Medication summary' })).toBeInTheDocument()
    expect(screen.getByText('The document says nothing about this section.')).toBeInTheDocument()
    expect(screen.getByRole('list', { name: 'Approval blocked' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Approve my summary' })).toBeDisabled()

    // The notice links back to that section's page.
    fireEvent.click(screen.getByRole('button', { name: 'Review this section' }))
    expect(await screen.findByText('Goes into your summary')).toBeInTheDocument()
    expect(screen.getByText(/Step 2 of 2/)).toBeInTheDocument()

    // Having seen the summary, a shortcut leads straight back to it.
    fireEvent.click(screen.getByRole('button', { name: '← Back' }))
    fireEvent.click(screen.getByRole('button', { name: 'Summary →' }))
    expect(
      await screen.findByRole('heading', { name: 'Your summary is ready' }),
    ).toBeInTheDocument()

    // A blocker links to the page that can resolve it.
    fireEvent.click(screen.getByRole('button', { name: 'Go to the page' }))
    expect(await screen.findByText(/Step 1 of 2/)).toBeInTheDocument()
  })
})
