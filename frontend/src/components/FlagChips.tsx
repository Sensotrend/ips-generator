import type { FlagCode } from '../api/types'
import { useT } from '../lib/i18n'
import { flagLabel, WARNING_FLAGS } from '../lib/labels'

export function FlagChips({ flags }: { flags: FlagCode[] }) {
  const { t } = useT()
  if (flags.length === 0) return null
  return (
    <ul className="chips" aria-label={t('flag.list')}>
      {flags.map((flag) => (
        <li key={flag} className={WARNING_FLAGS.has(flag) ? 'chip chip-warn' : 'chip'}>
          {flagLabel(flag)}
        </li>
      ))}
    </ul>
  )
}
