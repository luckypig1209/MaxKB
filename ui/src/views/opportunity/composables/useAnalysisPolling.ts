import { onUnmounted } from 'vue'
import { createPollScheduler, shouldKeepPolling } from './analysisPollingCore.js'

export { nextPollDelay, shouldKeepPolling, shouldRefreshHistory, POLL_INTERVAL_MS, POLL_BACKOFF_MS } from './analysisPollingCore.js'

export function useAnalysisPolling<T extends { status: string }>(options: {
  fetch: (id: string) => Promise<T>
  onUpdate: (data: T) => void
  onError?: (error: unknown) => void
}) {
  const scheduler = createPollScheduler({
    fetch: options.fetch,
    onUpdate: (data) => options.onUpdate(data as T),
    onError: options.onError,
    setTimer: (fn, ms) => window.setTimeout(fn, ms),
    clearTimer: (id) => window.clearTimeout(id as number),
  })

  onUnmounted(() => scheduler.stop())

  return {
    start: scheduler.start,
    stop: scheduler.stop,
    load: scheduler.load,
    shouldKeepPolling,
    getInFlight: scheduler.getInFlight,
  }
}
