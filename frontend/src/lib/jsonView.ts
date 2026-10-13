export interface JsonLine {
  text: string
  /** Locator (`$.a.b[2].c`, as in the source segments) of the leaf on this line; null for brackets. */
  locator: string | null
}

const IDENTIFIER = /^[^\W\d]\w*$/u

/** Same path syntax as the backend's ingest, so a fact's locator finds its line. */
const keyPath = (key: string): string =>
  IDENTIFIER.test(key) ? `.${key}` : `['${key.replace(/\\/g, '\\\\').replace(/'/g, "\\'")}']`

/** Indented JSON, one entry per line, each value line tagged with its locator. */
export function jsonLines(text: string): JsonLine[] | null {
  let root: unknown
  try {
    root = JSON.parse(text)
  } catch {
    return null
  }
  const lines: JsonLine[] = []
  const walk = (value: unknown, path: string, indent: string, prefix: string, comma: string) => {
    const isArray = Array.isArray(value)
    if (value !== null && typeof value === 'object') {
      const entries: [string, unknown][] = isArray
        ? value.map((v, i) => [String(i), v])
        : Object.entries(value)
      if (entries.length > 0) {
        const [open, close] = isArray ? ['[', ']'] : ['{', '}']
        lines.push({ text: `${indent}${prefix}${open}`, locator: null })
        entries.forEach(([key, child], i) => {
          const childComma = i < entries.length - 1 ? ',' : ''
          const childPath = isArray ? `${path}[${key}]` : path + keyPath(key)
          const childPrefix = isArray ? '' : `${JSON.stringify(key)}: `
          walk(child, childPath, `${indent}  `, childPrefix, childComma)
        })
        lines.push({ text: `${indent}${close}${comma}`, locator: null })
        return
      }
    }
    const leaf =
      value !== null && typeof value === 'object' ? (isArray ? '[]' : '{}') : JSON.stringify(value)
    lines.push({ text: `${indent}${prefix}${leaf}${comma}`, locator: path })
  }
  walk(root, '$', '', '', '')
  return lines
}
