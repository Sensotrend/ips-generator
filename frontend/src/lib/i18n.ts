import { useSyncExternalStore } from 'react'
import { en, type MessageKey, type Messages } from '../locales/en'
import { fi } from '../locales/fi'
import { sv } from '../locales/sv'

export const LOCALES = ['en', 'fi', 'sv'] as const
export type Locale = (typeof LOCALES)[number]

/** Each language in its own language, so a reader can find theirs whatever the current one. */
export const LOCALE_NAMES: Record<Locale, string> = { en: 'English', fi: 'Suomi', sv: 'Svenska' }

const CATALOGUES: Record<Locale, Messages> = { en, fi, sv }
const KEY = 'ips.locale'

/** Message keys as callers write them: plural pairs `x_one` / `x_other` are called as `x`. */
type BaseKey<K extends string> = K extends `${infer B}_${'one' | 'other'}` ? B : K
export type TKey = BaseKey<MessageKey>
export type Params = Record<string, string | number>

const isLocale = (value: unknown): value is Locale => LOCALES.includes(value as Locale)

/** The language is not PHI, so localStorage is fine; it must still work without storage. */
function detect(): Locale {
  try {
    const stored = window.localStorage.getItem(KEY)
    if (isLocale(stored)) return stored
  } catch {
    // storage unavailable: fall through to the browser language
  }
  for (const tag of navigator.languages ?? [navigator.language]) {
    const base = tag.toLowerCase().split('-')[0]
    if (isLocale(base)) return base
  }
  return 'en'
}

let current: Locale = detect()
const listeners = new Set<() => void>()
document.documentElement.lang = current

export const getLocale = (): Locale => current

export function setLocale(next: Locale): void {
  current = next
  document.documentElement.lang = next
  try {
    window.localStorage.setItem(KEY, next)
  } catch {
    // storage unavailable: keep the choice in memory only
  }
  listeners.forEach((listener) => listener())
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

/**
 * Look up a message in the current language (missing keys fall back to English). `{name}`
 * placeholders are filled from `params`; a numeric `count` picks the `_one` / `_other` variant.
 */
export function translate(key: TKey, params: Params = {}): string {
  const catalogue = CATALOGUES[current] as Record<string, string>
  let name: string = key
  if (typeof params.count === 'number') {
    const plural = `${key}_${new Intl.PluralRules(current).select(params.count)}`
    if (plural in catalogue) name = plural
  }
  const template = catalogue[name] ?? (en as Record<string, string>)[name] ?? key
  return template.replace(/\{(\w+)\}/g, (match, id: string) =>
    id in params ? String(params[id]) : match,
  )
}

/** Value of a backend enum (`on_hold`, `active`, …) in the current language. */
export function translateEnum(value: string): string {
  const key = `enum.${value}`
  return key in en ? translate(key as TKey) : value.replace(/_/g, ' ')
}

/** Job or step status from the backend in the current language; the raw value if unknown. */
export function translateStatus(status: string): string {
  const key = `status.${status}`
  return key in en ? translate(key as TKey) : status
}

/** Subscribes the component to language changes; `t` itself is the same function every render. */
export function useT(): { t: typeof translate; locale: Locale } {
  const locale = useSyncExternalStore(subscribe, getLocale)
  return { t: translate, locale }
}

/** Name of a document language code (`fi`) in the interface language; the code if unknown. */
export function languageName(code: string): string {
  try {
    return new Intl.DisplayNames([current], { type: 'language' }).of(code) ?? code
  } catch {
    return code
  }
}
