import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { UploadScreen } from './UploadScreen'

function renderUpload(onJob = vi.fn()) {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <UploadScreen onJob={onJob} />
    </QueryClientProvider>,
  )
  return onJob
}

describe('UploadScreen', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('accepts only the supported types and has no camera capture yet', () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.resolve(new Response('[]'))),
    )
    renderUpload()
    const input = screen.getByLabelText('Healthcare document')
    const accept = input.getAttribute('accept') ?? ''
    for (const ext of ['.txt', '.md', '.json', '.csv', '.pdf']) expect(accept).toContain(ext)
    expect(accept).not.toContain('image/')
    expect(input).not.toHaveAttribute('capture')
  })

  it('uploads the file and opens the job', async () => {
    const fetch = vi.fn((url: string, init?: RequestInit) => {
      if (url === '/api/jobs' && init?.method === 'POST')
        return Promise.resolve(new Response(JSON.stringify({ id: 'job-1', status: 'queued' })))
      return Promise.resolve(new Response('[]'))
    })
    vi.stubGlobal('fetch', fetch)
    const onJob = renderUpload()
    const file = new File(['Potilas: Testi'], 'note.txt', { type: 'text/plain' })
    fireEvent.change(screen.getByLabelText('Healthcare document'), { target: { files: [file] } })
    fireEvent.click(screen.getByRole('button', { name: 'Upload and extract' }))
    await waitFor(() => expect(onJob).toHaveBeenCalledWith('job-1'))
    const [, init] = fetch.mock.calls.find(([url]) => url === '/api/jobs' && true)!
    expect(init?.cache).toBe('no-store')
  })

  it('shows a typed API error', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((_url: string, init?: RequestInit) =>
        Promise.resolve(
          init?.method === 'POST'
            ? new Response(
                JSON.stringify({
                  error: { code: 'unsupported_media_type', message: 'Not supported.', details: [] },
                }),
                { status: 415 },
              )
            : new Response('[]'),
        ),
      ),
    )
    renderUpload()
    const file = new File(['x'], 'x.docx')
    fireEvent.change(screen.getByLabelText('Healthcare document'), { target: { files: [file] } })
    fireEvent.click(screen.getByRole('button', { name: 'Upload and extract' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Not supported.')
  })
})
