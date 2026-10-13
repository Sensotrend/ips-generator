import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { setLocale } from './lib/i18n'

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
    setLocale('en')
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

  it('switches the interface language and sets the document language', () => {
    renderApp()
    fireEvent.change(screen.getByRole('combobox', { name: 'Interface language' }), {
      target: { value: 'fi' },
    })
    expect(screen.getByRole('heading', { name: 'Kuka käyttää palvelua?' })).toBeInTheDocument()
    expect(document.documentElement.lang).toBe('fi')
    fireEvent.change(screen.getByRole('combobox', { name: 'Käyttöliittymän kieli' }), {
      target: { value: 'sv' },
    })
    expect(screen.getByRole('heading', { name: 'Vem använder tjänsten?' })).toBeInTheDocument()
  })
})
