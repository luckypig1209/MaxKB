/**
 * Browser-only helpers for the portal SSO landing page.
 *
 * The ticket is deliberately never persisted.  A digest is used as the
 * sessionStorage key so a failed landing page cannot retry the same ticket on
 * refresh without putting the opaque credential in browser storage.
 */

export const PORTAL_SSO_DEFAULT_TARGET = '/opportunity'

export const PORTAL_SSO_ALLOWED_TARGETS = new Set([
  '/home',
  '/opportunity',
  '/opportunity/records',
])

const PORTAL_TICKET_PATTERN = /^[A-Za-z0-9_-]{43,512}$/
const UNREPLACED_PORTAL_TICKETS = new Set(['${token}', 'undefined', 'null', '[object Object]'])
const ATTEMPT_KEY_PREFIX = 'maxkb:portal-sso:attempt:'
const inMemoryAttempts = new Set<string>()

export type PortalLandingFailure = 'ticket' | 'portal' | 'config' | 'unbound' | 'unavailable'

export function portalTicketPlaceholder(value: string | null): boolean {
  return value !== null && UNREPLACED_PORTAL_TICKETS.has(value)
}

export function readPortalTicket(hash: string): string | null {
  if (!hash || !hash.startsWith('#')) return null

  const fragment = hash.slice(1)
  const params = new URLSearchParams(fragment)
  const keys = [...params.keys()]
  if (keys.length !== 1 || keys[0] !== 'ticket') return null

  const ticket = params.get('ticket')
  return ticket && PORTAL_TICKET_PATTERN.test(ticket) ? ticket : null
}

export function sanitizePortalTarget(target: unknown): string {
  return typeof target === 'string' && PORTAL_SSO_ALLOWED_TARGETS.has(target)
    ? target
    : PORTAL_SSO_DEFAULT_TARGET
}

async function ticketFingerprint(ticket: string): Promise<string> {
  const bytes = new TextEncoder().encode(ticket)
  const subtle = globalThis.crypto?.subtle
  if (subtle) {
    try {
      const digest = await subtle.digest('SHA-256', bytes)
      return [...new Uint8Array(digest)].map((value) => value.toString(16).padStart(2, '0')).join('')
    } catch {
      // Some embedded shells expose crypto without a usable SubtleCrypto
      // implementation.  Fall through to the non-sensitive in-memory key.
    }
  }

  // The fallback only identifies this browser-session attempt.  It is not a
  // security primitive and intentionally does not preserve the ticket itself.
  let hash = 2166136261
  for (const byte of bytes) {
    hash ^= byte
    hash = Math.imul(hash, 16777619)
  }
  return (hash >>> 0).toString(16)
}

export function portalLandingFailure(code: unknown): PortalLandingFailure {
  if (code === 'SSO_CONFIG_INVALID' || code === 'SSO_DISABLED') return 'config'
  if (code === 'SSO_BIND_REQUIRED' || code === 'SSO_USER_DISABLED') return 'unbound'
  if (
    code === 'SSO_TICKET_INVALID' ||
    code === 'SSO_INVALID_REQUEST' ||
    code === 'SSO_TIMESTAMP_INVALID' ||
    code === 'SSO_NONCE_REPLAY'
  ) {
    return 'ticket'
  }
  return 'unavailable'
}

export async function preparePortalTicket(
  hash: string,
): Promise<{ action: 'exchange'; ticket: string } | { action: 'show'; status: 'ticket' | 'portal' }> {
  const fragment = hash?.startsWith('#') ? hash.slice(1) : ''
  const params = new URLSearchParams(fragment)
  const rawTicket = params.get('ticket')
  if (portalTicketPlaceholder(rawTicket)) return { action: 'show', status: 'portal' }

  const ticket = readPortalTicket(hash)
  if (!ticket || !(await claimPortalTicketAttempt(ticket))) return { action: 'show', status: 'ticket' }
  return { action: 'exchange', ticket }
}

/** Claim a ticket for this browser session; false means it was already tried. */
export async function claimPortalTicketAttempt(ticket: string): Promise<boolean> {
  const fingerprint = await ticketFingerprint(ticket)
  const key = `${ATTEMPT_KEY_PREFIX}${fingerprint}`

  try {
    if (sessionStorage.getItem(key)) return false
    sessionStorage.setItem(key, '1')
    return true
  } catch {
    if (inMemoryAttempts.has(fingerprint)) return false
    inMemoryAttempts.add(fingerprint)
    return true
  }
}
