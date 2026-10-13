import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '../api/client'
import { WalletOffer } from './WalletOffer'

vi.mock('qrcode', () => ({ default: { toDataURL: vi.fn(async () => 'data:image/png;base64,QR') } }))

const OFFER = 'openid-credential-offer://?credential_offer_uri=https%3A%2F%2Fissuer.example%2F1'

describe('WalletOffer', () => {
  beforeEach(() => vi.restoreAllMocks())

  it('shows the QR code and an open-in-wallet link on request', async () => {
    const walletOffer = vi.spyOn(api, 'walletOffer').mockResolvedValue({ url: OFFER })
    render(<WalletOffer jobId="j1" />)
    expect(walletOffer).not.toHaveBeenCalled()

    fireEvent.click(screen.getByRole('button', { name: 'Show QR code' }))
    const qr = await screen.findByRole('img', { name: 'QR code with the wallet credential offer' })
    expect(qr).toHaveAttribute('src', 'data:image/png;base64,QR')
    expect(walletOffer).toHaveBeenCalledWith('j1')
    expect(screen.getByRole('link', { name: 'Open in a wallet on this device' })).toHaveAttribute(
      'href',
      OFFER,
    )
  })

  it('reports a failure and lets the patient retry', async () => {
    vi.spyOn(api, 'walletOffer').mockRejectedValue(new Error('x'))
    render(<WalletOffer jobId="j1" />)
    fireEvent.click(screen.getByRole('button', { name: 'Show QR code' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not create the wallet offer')
    expect(screen.getByRole('button', { name: 'Show QR code' })).toBeEnabled()
  })
})
