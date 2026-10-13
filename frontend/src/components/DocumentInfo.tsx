import type { DocumentInfo as Info } from '../api/types'
import type { Locale } from '../lib/i18n'
import { useT } from '../lib/i18n'

/** Metadata of the summary document: shown on screen and kept in the printout. */
export function DocumentInfo({ info, locale }: { info: Info; locale: Locale }) {
  const { t } = useT()
  const date = (iso: string) => new Date(iso).toLocaleDateString(locale)
  const status =
    info.approved_at && info.attester_mode
      ? t(info.attester_mode === 'personal' ? 'doc.status.personal' : 'doc.status.professional', {
          date: date(info.approved_at),
        })
      : t('doc.status.draft')
  return (
    <dl className="document-info">
      <dt>{t('doc.created')}</dt>
      <dd>{date(info.created_at)}</dd>
      <dt>{t('doc.status')}</dt>
      <dd>{status}</dd>
      {info.ai_assisted && (
        <>
          <dt>{t('doc.ai')}</dt>
          <dd>{t('doc.ai.yes')}</dd>
        </>
      )}
      <dt>{t('doc.software')}</dt>
      <dd>
        {info.software} {info.software_version}
      </dd>
    </dl>
  )
}
