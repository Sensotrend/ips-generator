import { afterEach, describe, expect, it } from 'vitest'
import { en } from '../locales/en'
import { fi } from '../locales/fi'
import { sv } from '../locales/sv'
import { setLocale, translate, translateEnum } from './i18n'

const placeholders = (text: string) => [...text.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort()

describe('catalogues', () => {
  const english = en as Record<string, string>
  for (const [name, catalogue] of [
    ['fi', fi],
    ['sv', sv],
  ] as const) {
    it(`${name} has exactly the English keys`, () => {
      expect(Object.keys(catalogue).sort()).toEqual(Object.keys(english).sort())
    })

    it(`${name} keeps the placeholders of every English message`, () => {
      for (const [key, text] of Object.entries(catalogue as Record<string, string>)) {
        expect(placeholders(text), key).toEqual(placeholders(english[key]))
      }
    })

    it(`${name} has no untranslated copies of long English sentences`, () => {
      for (const [key, text] of Object.entries(catalogue as Record<string, string>)) {
        if (english[key].length > 40) expect(text, key).not.toBe(english[key])
      }
    })
  }
})

describe('translate', () => {
  afterEach(() => setLocale('en'))

  it('fills placeholders and picks plural forms', () => {
    expect(translate('review.dropped', { count: 1 })).toMatch(/^1 extracted fact was/)
    expect(translate('review.dropped', { count: 2 })).toMatch(/^2 extracted facts were/)
    setLocale('fi')
    expect(translate('source.page', { page: 2, total: 5 })).toBe('Sivu 2 / 5')
  })

  it('switches language, remembers it and sets the document language', () => {
    setLocale('sv')
    expect(translate('fact.save')).toBe('Spara')
    expect(document.documentElement.lang).toBe('sv')
    expect(window.localStorage.getItem('ips.locale')).toBe('sv')
  })

  it('translates known enum values and prettifies unknown ones', () => {
    setLocale('fi')
    expect(translateEnum('on_hold')).toBe('tauolla')
    expect(translateEnum('some_new_value')).toBe('some new value')
  })
})
