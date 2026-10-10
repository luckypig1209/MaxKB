import assert from 'node:assert/strict'
import test from 'node:test'

import {
  createPollScheduler,
  nextPollDelay,
  shouldKeepPolling,
  shouldRefreshHistory,
  POLL_INTERVAL_MS,
} from '../analysisPollingCore.js'

function createClock() {
  const timers = []
  let now = 0
  let seq = 0
  const setTimer = (fn, ms) => {
    const id = { id: ++seq, at: now + ms, fn, cancelled: false }
    timers.push(id)
    return id
  }
  const clearTimer = (id) => {
    if (id) id.cancelled = true
  }
  const flushTimers = async () => {
    const due = timers.filter((item) => !item.cancelled && item.at <= now)
    due.sort((a, b) => a.at - b.at)
    for (const item of due) {
      item.cancelled = true
      item.fn()
    }
    await Promise.resolve()
    await Promise.resolve()
  }
  const advance = async (ms) => {
    now += ms
    await flushTimers()
  }
  return { setTimer, clearTimer, advance }
}

test('backoff uses 1.5s then 3s then 5s', () => {
  assert.equal(nextPollDelay(0), 1500)
  assert.equal(nextPollDelay(1), 1500)
  assert.equal(nextPollDelay(2), 3000)
  assert.equal(nextPollDelay(3), 5000)
  assert.equal(nextPollDelay(9), 5000)
})

test('only ANALYZING keeps polling', () => {
  assert.equal(shouldKeepPolling('ANALYZING'), true)
  for (const status of ['NEED_CLARIFICATION', 'FAILED', 'WAITING_CONFIRMATION', 'CONFIRMED', 'CLOSED']) {
    assert.equal(shouldKeepPolling(status), false)
  }
})

test('slow 5s request never overlaps', async () => {
  const clock = createClock()
  let current = 0
  let maxInFlight = 0
  const releases = []
  const updates = []
  const scheduler = createPollScheduler({
    fetch: () => {
      current += 1
      maxInFlight = Math.max(maxInFlight, current)
      return new Promise((resolve) => {
        releases.push(() => {
          current -= 1
          resolve({ status: 'ANALYZING' })
        })
      })
    },
    onUpdate: (data) => updates.push(data.status),
    setTimer: clock.setTimer,
    clearTimer: clock.clearTimer,
  })
  scheduler.start('a1')
  await clock.advance(POLL_INTERVAL_MS)
  assert.equal(scheduler.getInFlight(), 1)
  await clock.advance(5000)
  assert.equal(scheduler.getInFlight(), 1)
  assert.equal(releases.length, 1)
  releases.shift()()
  await Promise.resolve()
  await Promise.resolve()
  assert.equal(maxInFlight, 1)
  assert.deepEqual(updates, ['ANALYZING'])
  scheduler.stop()
})

test('three failures back off 1.5 / 3 / 5 seconds then recover', async () => {
  const clock = createClock()
  const delays = []
  let failsLeft = 3
  const scheduler = createPollScheduler({
    fetch: async () => {
      if (failsLeft > 0) {
        failsLeft -= 1
        throw new Error('network')
      }
      return { status: 'ANALYZING' }
    },
    onUpdate: () => {},
    setTimer: (fn, ms) => {
      delays.push(ms)
      return clock.setTimer(fn, ms)
    },
    clearTimer: clock.clearTimer,
  })
  scheduler.start('a1')
  await clock.advance(1500)
  await clock.advance(1500)
  await clock.advance(3000)
  await clock.advance(5000)
  assert.deepEqual(delays.slice(0, 4), [1500, 1500, 3000, 5000])
  await clock.advance(1500)
  assert.equal(delays.at(-1), 1500)
  scheduler.stop()
})

test('stop prevents later updates', async () => {
  const clock = createClock()
  let resolveFetch
  const updates = []
  const scheduler = createPollScheduler({
    fetch: () => new Promise((resolve) => {
      resolveFetch = resolve
    }),
    onUpdate: (data) => updates.push(data),
    setTimer: clock.setTimer,
    clearTimer: clock.clearTimer,
  })
  scheduler.start('a1')
  await clock.advance(1500)
  scheduler.stop()
  resolveFetch({ status: 'WAITING_CONFIRMATION' })
  await Promise.resolve()
  await Promise.resolve()
  assert.equal(updates.length, 0)
})

test('stale response does not overwrite later terminal state', async () => {
  const pending = new Map()
  const updates = []
  const scheduler = createPollScheduler({
    fetch: (id) => new Promise((resolve) => pending.set(id, resolve)),
    onUpdate: (data) => updates.push(data.status),
    setTimer: () => 1,
    clearTimer: () => {},
  })
  const first = scheduler.load('old')
  await Promise.resolve()
  const second = scheduler.load('new')
  pending.get('old')({ status: 'ANALYZING' })
  await first
  await Promise.resolve()
  pending.get('new')({ status: 'WAITING_CONFIRMATION' })
  await second
  assert.deepEqual(updates, ['WAITING_CONFIRMATION'])
  scheduler.stop()
})

test('start B while A pending never overlaps and restores inFlight to 0', async () => {
  let current = 0
  let maxActive = 0
  const releases = []
  const updates = []
  const ids = []
  const scheduler = createPollScheduler({
    fetch: (id) => {
      current += 1
      maxActive = Math.max(maxActive, current)
      ids.push(id)
      return new Promise((resolve) => {
        releases.push(() => {
          current -= 1
          resolve({
            status: id === 'b' ? 'WAITING_CONFIRMATION' : 'ANALYZING',
            id,
          })
        })
      })
    },
    onUpdate: (data) => updates.push(data.id),
    setTimer: () => 1,
    clearTimer: () => {},
  })
  const first = scheduler.load('a')
  await Promise.resolve()
  assert.equal(scheduler.getInFlight(), 1)
  const second = scheduler.load('b')
  assert.equal(scheduler.getInFlight(), 1)
  assert.equal(maxActive, 1)
  assert.deepEqual(ids, ['a'])
  releases[0]()
  await first
  await Promise.resolve()
  await Promise.resolve()
  assert.equal(scheduler.getInFlight(), 1)
  assert.equal(maxActive, 1)
  assert.deepEqual(ids, ['a', 'b'])
  releases[1]()
  await second
  assert.equal(maxActive, 1)
  assert.equal(scheduler.getInFlight(), 0)
  assert.equal(current, 0)
  assert.deepEqual(updates, ['b'])
  scheduler.stop()
})

test('shouldRefreshHistory only when leaving ANALYZING', () => {
  assert.equal(shouldRefreshHistory('ANALYZING', 'NEED_CLARIFICATION'), true)
  assert.equal(shouldRefreshHistory('ANALYZING', 'WAITING_CONFIRMATION'), true)
  assert.equal(shouldRefreshHistory('ANALYZING', 'FAILED'), true)
  assert.equal(shouldRefreshHistory('ANALYZING', 'CLOSED'), true)
  assert.equal(shouldRefreshHistory('ANALYZING', 'ANALYZING'), false)
  assert.equal(shouldRefreshHistory('NEED_CLARIFICATION', 'WAITING_CONFIRMATION'), false)
  assert.equal(shouldRefreshHistory('WAITING_CONFIRMATION', 'CONFIRMED'), false)
  assert.equal(shouldRefreshHistory(undefined, 'WAITING_CONFIRMATION'), false)
  assert.equal(shouldRefreshHistory('ANALYZING', ''), false)
})

test('history list status follows terminal poll update once', async () => {
  const statuses = ['ANALYZING', 'ANALYZING', 'NEED_CLARIFICATION', 'NEED_CLARIFICATION']
  let index = 0
  let lastStatus
  let historyRefreshes = 0
  const history = [{ id: 'a', status: 'ANALYZING' }]
  const clock = createClock()
  const scheduler = createPollScheduler({
    fetch: async () => {
      const status = statuses[Math.min(index, statuses.length - 1)]
      index += 1
      return { id: 'a', status }
    },
    onUpdate: (data) => {
      if (shouldRefreshHistory(lastStatus, data.status)) {
        historyRefreshes += 1
        history[0] = { ...history[0], status: data.status }
      }
      lastStatus = data.status
    },
    setTimer: clock.setTimer,
    clearTimer: clock.clearTimer,
  })
  await scheduler.load('a')
  assert.equal(history[0].status, 'ANALYZING')
  assert.equal(historyRefreshes, 0)
  await clock.advance(POLL_INTERVAL_MS)
  assert.equal(history[0].status, 'ANALYZING')
  assert.equal(historyRefreshes, 0)
  await clock.advance(POLL_INTERVAL_MS)
  assert.equal(history[0].status, 'NEED_CLARIFICATION')
  assert.equal(historyRefreshes, 1)
  await clock.advance(POLL_INTERVAL_MS)
  assert.equal(historyRefreshes, 1)
  scheduler.stop()
})

