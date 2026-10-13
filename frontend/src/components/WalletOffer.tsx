import QRCode from 'qrcode'
import { useState } from 'react'
import { api } from '../api/client'
import { useT } from '../lib/i18n'

type State =
  | { kind: 'idle' }
  | { kind: 'busy' }
  | { kind: 'failed' }
  | { kind: 'ready'; offerUrl: string; qr: string }

/**
 * Stores the approved IPS in a digital wallet: the API gets a credential-offer URL from the
 * issuer, shown as a QR code (and as a link for a wallet on the same device). The QR image lives
 * only in component state; nothing is persisted.
 */
export function WalletOffer({ jobId }: { jobId: string }) {
  const { t } = useT()
  const [state, setState] = useState<State>({ kind: 'idle' })

  async function create() {
    setState({ kind: 'busy' })
    try {
      const { url } = await api.walletOffer(jobId)
      const qr = await QRCode.toDataURL(url, { width: 256, margin: 2 })
      setState({ kind: 'ready', offerUrl: url, qr })
    } catch {
      setState({ kind: 'failed' })
    }
  }

  return (
    <div className="wallet-offer">
      <h3>{t('approve.wallet.title')}</h3>
      {state.kind === 'ready' ? (
        <>
          <p>{t('approve.wallet.scan')}</p>
          <img src={state.qr} width={256} height={256} alt={t('approve.wallet.qrAlt')} />
          <p>
            <a href={state.offerUrl}>{t('approve.wallet.open')}</a>
          </p>
        </>
      ) : (
        <>
          <button type="button" onClick={() => void create()} disabled={state.kind === 'busy'}>
            {t(state.kind === 'busy' ? 'approve.wallet.busy' : 'approve.wallet.button')}
          </button>
          {state.kind === 'failed' && (
            <p className="note note-warning" role="alert">
              {t('approve.wallet.failed')}
            </p>
          )}
        </>
      )}
    </div>
  )
}
