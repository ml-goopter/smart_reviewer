/* An in-memory stand-in for Web Storage.
 *
 * jsdom exposes sessionStorage but not localStorage, so the language
 * preference has no real backing store under test. Stubbing this in is the
 * nearest seam to the browser API — the code under test still goes through
 * getItem/setItem and still has to cope with what comes back.
 *
 * Not a test file: vitest collects only *.test.ts.
 */

export function memoryStorage(): Storage {
  const entries = new Map<string, string>()

  return {
    getItem: (key) => entries.get(key) ?? null,
    setItem: (key, value) => {
      entries.set(key, String(value))
    },
    removeItem: (key) => {
      entries.delete(key)
    },
    clear: () => {
      entries.clear()
    },
    key: (index) => [...entries.keys()][index] ?? null,
    get length() {
      return entries.size
    },
  }
}

/** Storage that throws on every access, as it does in private browsing and
 *  in a sandboxed iframe. */
export function throwingStorage(): Storage {
  const fail = (): never => {
    throw new Error('storage is disabled')
  }

  return {
    getItem: fail,
    setItem: fail,
    removeItem: fail,
    clear: fail,
    key: fail,
    get length(): number {
      return fail()
    },
  }
}
