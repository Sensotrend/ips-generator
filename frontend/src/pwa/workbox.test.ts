import { describe, expect, it } from 'vitest'
import { isApiRequest, workboxOptions } from './workbox'

describe('service worker caching (PHI rule)', () => {
  it('serves every API URL network-only', () => {
    for (const path of [
      '/api/jobs',
      '/api/jobs/1/draft',
      '/api/jobs/1/source/original',
      '/api/jobs/1/ips',
      '/api/jobs/1/events',
    ]) {
      const url = new URL(path, 'https://app.example')
      const rules = workboxOptions.runtimeCaching.filter((rule) => rule.urlPattern({ url }))
      expect(rules.map((rule) => rule.handler)).toEqual(['NetworkOnly'])
    }
  })

  it('has no runtime cache other than NetworkOnly', () => {
    expect(workboxOptions.runtimeCaching.every((rule) => rule.handler === 'NetworkOnly')).toBe(true)
  })

  it('never answers API navigations with the app shell', () => {
    expect(workboxOptions.navigateFallbackDenylist.some((re) => re.test('/api/jobs/1/ips'))).toBe(
      true,
    )
    expect(isApiRequest({ url: new URL('https://app.example/index.html') })).toBe(false)
  })

  it('precaches only static app-shell assets', () => {
    expect(workboxOptions.globPatterns.join()).not.toMatch(/json(?!\w)/)
  })
})
