import type { FlagCode } from '../api/types'
import { FLAG_LABELS, WARNING_FLAGS } from '../lib/labels'

export function FlagChips({ flags }: { flags: FlagCode[] }) {
  if (flags.length === 0) return null
  return (
    <ul className="chips" aria-label="Review flags">
      {flags.map((flag) => (
        <li key={flag} className={WARNING_FLAGS.has(flag) ? 'chip chip-warn' : 'chip'}>
          {FLAG_LABELS[flag]}
        </li>
      ))}
    </ul>
  )
}
