// Post-build assertion on the generated service worker (PHI rule, PLAN D8):
// /api/ must be NetworkOnly, no caching strategy may appear, and no API URL may be precached.
import { readFileSync } from 'node:fs'

const sw = readFileSync(new URL('../dist/sw.js', import.meta.url), 'utf8')
const failures = []
if (!sw.includes('NetworkOnly')) failures.push('no NetworkOnly route for /api/')
if (!sw.includes('/api/')) failures.push('the /api/ route is missing')
for (const strategy of ['CacheFirst', 'StaleWhileRevalidate', 'NetworkFirst', 'CacheOnly']) {
  if (sw.includes(strategy)) failures.push(`unexpected caching strategy ${strategy}`)
}
const precache = sw.match(/precacheAndRoute\(\s*(\[[\s\S]*?\])/)
if (!precache) failures.push('precache manifest not found')
else if (/"url":\s*"api\//.test(precache[1]) || /url:"api\//.test(precache[1]))
  failures.push('an API URL is precached')
if (failures.length) {
  console.error('Service worker check failed:\n- ' + failures.join('\n- '))
  process.exit(1)
}
console.log('Service worker check passed: app shell precache only, /api/ NetworkOnly.')
