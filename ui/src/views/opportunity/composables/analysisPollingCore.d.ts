export const POLL_INTERVAL_MS: number
export const POLL_BACKOFF_MS: number[]
export const POLL_STOP_STATUSES: string[]

export function nextPollDelay(consecutiveFailures: number): number
export function shouldKeepPolling(status?: string | null): boolean
export function shouldRefreshHistory(previousStatus?: string | null, nextStatus?: string | null): boolean
export function isStaleResponse(responseSeq: number, latestSeq: number): boolean

export interface AnalysisPoller {
  start: (id: string) => Promise<void>
  stop: () => void
  load: (id: string) => Promise<void>
  getInFlight: () => number
}

export function createPollScheduler(options: {
  fetch: (id: string) => Promise<{ status: string }>
  onUpdate: (data: { status: string }) => void
  onError?: (error: unknown) => void
  setTimer: (fn: () => void, ms: number) => unknown
  clearTimer: (id: unknown) => void
}): AnalysisPoller
