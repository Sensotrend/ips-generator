import { describe, expect, it } from 'vitest'
import { jsonLines } from './jsonView'

describe('jsonLines', () => {
  it('indents the JSON and tags value lines with the ingest locators', () => {
    const lines = jsonLines('{"a":{"b":[1,"x"],"c d":null,"e":{}}}')
    expect(lines?.map((l) => l.text)).toEqual([
      '{',
      '  "a": {',
      '    "b": [',
      '      1,',
      '      "x"',
      '    ],',
      '    "c d": null,',
      '    "e": {}',
      '  }',
      '}',
    ])
    expect(lines?.filter((l) => l.locator).map((l) => l.locator)).toEqual([
      '$.a.b[0]',
      '$.a.b[1]',
      "$.a['c d']",
      '$.a.e',
    ])
  })

  it('returns null for invalid JSON', () => {
    expect(jsonLines('{')).toBeNull()
  })
})
