import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { Source } from '../api/types'
import { source as textSource } from '../test-fixtures'
import { TextSourceViewer } from './TextSourceViewer'

const jsonSource: Source = {
  media_type: 'application/json',
  page_count: 1,
  pages_without_text: [],
  original_url: null,
  json_text: '{"asiakas":[{"asiakas_id":"SYN-1","sukupuoli":"NAINEN"}]}',
  segments: [
    { page: 1, locator: '$.asiakas[0].asiakas_id', text: 'asiakas[0].asiakas_id: SYN-1' },
    { page: 1, locator: '$.asiakas[0].sukupuoli', text: 'asiakas[0].sukupuoli: NAINEN' },
  ],
}

describe('TextSourceViewer', () => {
  it('has no view toggle for sources without JSON text', () => {
    render(<TextSourceViewer source={textSource} focus={null} />)
    expect(screen.queryByRole('button', { name: 'JSON' })).not.toBeInTheDocument()
  })

  it('switches between rows and the indented JSON, marking the focused line', () => {
    const focus = {
      quote: 'asiakas[0].sukupuoli: NAINEN',
      page: 1,
      locator: '$.asiakas[0].sukupuoli',
    }
    const { container } = render(<TextSourceViewer source={jsonSource} focus={focus} />)
    expect(screen.getByText('asiakas[0].asiakas_id: SYN-1')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'JSON' }))
    expect(screen.getByText(/"asiakas_id": "SYN-1"/)).toBeInTheDocument()
    expect(container.querySelector('.source-json .seg-focus')).toHaveTextContent(
      '"sukupuoli": "NAINEN"',
    )
    fireEvent.click(screen.getByRole('button', { name: 'Rows' }))
    expect(screen.getByText('asiakas[0].asiakas_id: SYN-1')).toBeInTheDocument()
  })
})
