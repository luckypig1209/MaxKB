export const POLL_INTERVAL_MS = 1500
export const POLL_BACKOFF_MS = [1500, 3000, 5000]
export const POLL_STOP_STATUSES = [
  'NEED_CLARIFICATION',
  'FAILED',
  'WAITING_CONFIRMATION',
  'CONFIRMED',
  'CLOSED',
]

export function nextPollDelay(consecutiveFailures) {
  const count = Math.max(0, Number(consecutiveFailures) || 0)
  if (count <= 0) return POLL_INTERVAL_MS
  return POLL_BACKOFF_MS[Math.min(count, POLL_BACKOFF_MS.length) - 1]
}

export function shouldKeepPolling(status) {
  return status === 'ANALYZING'
}

export function shouldRefreshHistory(previousStatus, nextStatus) {
  return previousStatus === 'ANALYZING' && Boolean(nextStatus) && nextStatus !== 'ANALYZING'
}

export function isStaleResponse(responseSeq, latestSeq) {
  return responseSeq !== latestSeq
}

function isAbortError(error) {
  return Boolean(error && (error.name === 'AbortError' || error.code === 'ERR_CANCELED'))
}

export function createPollScheduler({ fetch, onUpdate, onError, setTimer, clearTimer }) {
  let generation = 0
  let timer = null
  let inFlight = 0
  let failures = 0
  let currentId = null
  let latestSeq = 0
  let idleWaiters = []

  const getInFlight = () => inFlight

  function flushIdle() {
    if (inFlight > 0) return
    const waiters = idleWaiters
    idleWaiters = []
    waiters.forEach((resolve) => resolve())
  }

  function whenIdle() {
    if (inFlight === 0) return Promise.resolve()
    return new Promise((resolve) => {
      idleWaiters.push(resolve)
    })
  }

  function stop() {
    generation += 1
    if (timer != null) {
      clearTimer(timer)
      timer = null
    }
    currentId = null
  }

  function schedule(gen, delay) {
    if (gen !== generation) return
    if (timer != null) clearTimer(timer)
    timer = setTimer(() => {
      timer = null
      tick(gen)
    }, delay)
  }

  async function tick(gen) {
    if (gen !== generation || !currentId || inFlight > 0) return
    inFlight += 1
    const seq = ++latestSeq
    const id = currentId
    try {
      const data = await fetch(id)
      if (gen !== generation || isStaleResponse(seq, latestSeq)) return
      failures = 0
      onUpdate(data)
      if (!shouldKeepPolling(data?.status)) {
        stop()
        return
      }
      schedule(gen, POLL_INTERVAL_MS)
    } catch (error) {
      if (gen !== generation || isStaleResponse(seq, latestSeq) || isAbortError(error)) return
      failures += 1
      if (typeof onError === 'function') onError(error)
      schedule(gen, nextPollDelay(failures))
    } finally {
      inFlight = Math.max(0, inFlight - 1)
      flushIdle()
    }
  }

  function begin(id) {
    stop()
    const gen = generation
    currentId = id
    latestSeq = 0
    failures = 0
    return gen
  }

  function start(id) {
    const gen = begin(id)
    if (inFlight === 0) {
      schedule(gen, POLL_INTERVAL_MS)
      return Promise.resolve()
    }
    return whenIdle().then(() => {
      if (gen !== generation) return
      schedule(gen, POLL_INTERVAL_MS)
    })
  }

  function load(id) {
    const gen = begin(id)
    if (inFlight === 0) {
      return Promise.resolve(tick(gen))
    }
    return whenIdle().then(() => {
      if (gen !== generation) return
      return tick(gen)
    })
  }

  return { start, stop, load, getInFlight }
}
