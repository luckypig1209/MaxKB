import assert from 'node:assert/strict'
import test from 'node:test'
import { readPortalTicket, sanitizePortalTarget } from '../portal-sso.ts'
import { claimPortalTicketAttempt } from '../portal-sso.ts'
import { clearStoredLoginToken } from '../../../stores/modules/login-session.ts'

test('reads only a valid opaque ticket from the fragment', () => {
  const ticket = 'A'.repeat(43)
  assert.equal(readPortalTicket(`#ticket=${ticket}`), ticket)
  assert.equal(readPortalTicket(`#ticket=${ticket}&target=/opportunity`), null)
  assert.equal(readPortalTicket('#ticket=too-short'), null)
  assert.equal(readPortalTicket(`#ticket=${ticket}%2F`), null)
})

test('keeps portal targets inside the explicit route allow-list', () => {
  assert.equal(sanitizePortalTarget('/home'), '/home')
  assert.equal(sanitizePortalTarget('/opportunity/records'), '/opportunity/records')
  assert.equal(sanitizePortalTarget('/opportunity?next=https://evil.example'), '/opportunity')
  assert.equal(sanitizePortalTarget('//evil.example'), '/opportunity')
  assert.equal(sanitizePortalTarget(undefined), '/opportunity')
})

test('claims one ticket only once in the current browser session', async () => {
  const previous = (globalThis as any).sessionStorage
  const values = new Map<string, string>()
  Object.defineProperty(globalThis, 'sessionStorage', {
    configurable: true,
    value: {
      getItem: (key: string) => values.get(key) || null,
      setItem: (key: string, value: string) => values.set(key, value),
    },
  })
  try {
    const ticket = 'B'.repeat(43)
    assert.equal(await claimPortalTicketAttempt(ticket), true)
    assert.equal(await claimPortalTicketAttempt(ticket), false)
  } finally {
    Object.defineProperty(globalThis, 'sessionStorage', {
      configurable: true,
      value: previous,
    })
  }
})

test('session cleanup removes a half-initialized token without reading it', () => {
  const removed: string[] = []
  clearStoredLoginToken({ removeItem: (key: string) => removed.push(key) })
  assert.deepEqual(removed, ['token'])
})
