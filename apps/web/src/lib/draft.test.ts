import { beforeEach, describe, expect, it, vi } from 'vitest'
import { clearDraft, loadDraft, saveDraft } from './draft'

const TOKEN = 'Ks92MxD7yP-abcdefghijklmnopqrstuvwxyz012345'
const DRAFT = { selectedId: 'a1', originalText: 'original', reviewText: 'edited' }

beforeEach(() => {
  sessionStorage.clear()
  vi.restoreAllMocks()
})

describe('round trip', () => {
  it('restores what was saved', () => {
    saveDraft(TOKEN, DRAFT)

    expect(loadDraft(TOKEN)).toEqual(DRAFT)
  })

  it('returns null when nothing was saved', () => {
    expect(loadDraft(TOKEN)).toBeNull()
  })

  it('keeps drafts for different sessions apart', () => {
    saveDraft(TOKEN, DRAFT)
    saveDraft('a-different-token', { ...DRAFT, reviewText: 'other' })

    expect(loadDraft(TOKEN)?.reviewText).toBe('edited')
  })

  it('clears', () => {
    saveDraft(TOKEN, DRAFT)
    clearDraft(TOKEN)

    expect(loadDraft(TOKEN)).toBeNull()
  })

  it('survives a null selectedId, which is the skip path', () => {
    saveDraft(TOKEN, { ...DRAFT, selectedId: null })

    expect(loadDraft(TOKEN)?.selectedId).toBeNull()
  })
})

describe('the token is never written to storage', () => {
  it('appears in no key', () => {
    saveDraft(TOKEN, DRAFT)

    const keys = Object.keys(sessionStorage)

    expect(keys).toHaveLength(1)
    expect(keys[0]).not.toContain(TOKEN)
  })

  it('appears in no value', () => {
    saveDraft(TOKEN, DRAFT)

    expect(JSON.stringify(sessionStorage)).not.toContain(TOKEN)
  })

  it('is not recoverable from the key even in part', () => {
    saveDraft(TOKEN, DRAFT)

    const key = Object.keys(sessionStorage)[0]!

    // A prefix of the token would be enough to shorten a brute force.
    for (let length = 6; length <= TOKEN.length; length++) {
      expect(key).not.toContain(TOKEN.slice(0, length))
    }
  })
})

describe('stored data is untrusted', () => {
  it.each([
    ['malformed json', '{not json'],
    ['a bare string', '"hello"'],
    ['null', 'null'],
    ['an array', '[]'],
    ['a non-string reviewText', '{"selectedId":null,"originalText":"a","reviewText":42}'],
    ['a non-string originalText', '{"selectedId":null,"originalText":{},"reviewText":"a"}'],
    ['a non-string selectedId', '{"selectedId":7,"originalText":"a","reviewText":"b"}'],
    ['missing fields', '{"reviewText":"b"}'],
  ])('discards %s', (_label, raw) => {
    saveDraft(TOKEN, DRAFT)
    const key = Object.keys(sessionStorage)[0]!
    sessionStorage.setItem(key, raw)

    expect(loadDraft(TOKEN)).toBeNull()
  })

  it('keeps only the three known fields', () => {
    saveDraft(TOKEN, DRAFT)
    const key = Object.keys(sessionStorage)[0]!
    sessionStorage.setItem(
      key,
      '{"selectedId":null,"originalText":"a","reviewText":"b","token":"leaked"}',
    )

    expect(loadDraft(TOKEN)).toEqual({ selectedId: null, originalText: 'a', reviewText: 'b' })
  })
})

describe('storage being unavailable is not fatal', () => {
  it('save does not throw when setItem throws', () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('QuotaExceededError')
    })

    expect(() => saveDraft(TOKEN, DRAFT)).not.toThrow()
  })

  it('load returns null when getItem throws', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new DOMException('SecurityError')
    })

    expect(loadDraft(TOKEN)).toBeNull()
  })

  it('clear does not throw when removeItem throws', () => {
    vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(() => {
      throw new DOMException('SecurityError')
    })

    expect(() => clearDraft(TOKEN)).not.toThrow()
  })
})
