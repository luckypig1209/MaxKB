import { nanoid } from 'nanoid'

/**
 * Generate an API idempotency key without relying on secure-context-only APIs.
 * nanoid uses crypto.getRandomValues, which remains available on supported LAN HTTP pages.
 */
export const createIdempotencyKey = () => nanoid()
