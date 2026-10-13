import { useCallback, useState } from 'react'
import type { ReviewerRole } from '../api/types'

const KEY = 'ips.role'

/** The role is not PHI, so sessionStorage is fine; it must still work without storage. */
function read(): ReviewerRole | null {
  try {
    const value = window.sessionStorage.getItem(KEY)
    return value === 'patient' || value === 'clinician' ? value : null
  } catch {
    return null
  }
}

/** Self-declared role (not authentication). It picks the UI and the attester type. */
export function useRole(): [ReviewerRole | null, (role: ReviewerRole | null) => void] {
  const [role, setRoleState] = useState<ReviewerRole | null>(read)
  const setRole = useCallback((next: ReviewerRole | null) => {
    setRoleState(next)
    try {
      if (next) window.sessionStorage.setItem(KEY, next)
      else window.sessionStorage.removeItem(KEY)
    } catch {
      // storage unavailable: keep the choice in memory only
    }
  }, [])
  return [role, setRole]
}
