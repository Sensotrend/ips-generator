import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'

function renderApp() {
  vi.stubGlobal(
    'fetch',
    vi.fn(() => Promise.resolve(new Response('[]'))),
  )
  render(
    <QueryClientProvider client={new QueryClient()}>
      <App />
    </QueryClientProvider>,
  )
}

describe('App', () => {
  beforeEach(() => window.sessionStorage.clear())
  afterEach(() => {
    vi.unstubAllGlobals()
    window.location.hash = ''
  })

  it('asks who is using the service before anything else', () => {
    renderApp()
    expect(screen.getByRole('heading', { name: 'Who is using this service?' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Upload and extract' })).not.toBeInTheDocument()
  })

  it('shows the upload screen after a role is chosen, and remembers it for the session', () => {
    renderApp()
    fireEvent.click(screen.getByRole('button', { name: /I am a patient/ }))
    expect(screen.getByRole('button', { name: 'Upload and extract' })).toBeDisabled()
    expect(screen.getByText('Patient')).toBeInTheDocument()
    expect(window.sessionStorage.getItem('ips.role')).toBe('patient')
    fireEvent.click(screen.getByRole('button', { name: 'Change' }))
    expect(screen.getByRole('heading', { name: 'Who is using this service?' })).toBeInTheDocument()
  })
})
