import assert from 'node:assert/strict'
import { describe, it } from 'node:test'
import { formatOpportunityTime, toShanghaiDayEnd, toShanghaiDayStart } from '../time.ts'

describe('formatOpportunityTime', () => {
  it('converts UTC to Shanghai without shifting an existing offset twice', () => {
    assert.equal(formatOpportunityTime('2026-10-12T08:00:00+00:00'), '2026/10/12 16:00')
    assert.equal(formatOpportunityTime('2026-10-12T08:00:00Z'), '2026/10/12 16:00')
    assert.equal(formatOpportunityTime('2026-10-12T16:00:00+08:00'), '2026/10/12 16:00')
  })

  it('crosses the Shanghai day boundary at UTC 16:00', () => {
    assert.equal(formatOpportunityTime('2026-10-12T16:00:00+00:00'), '2026/10/13 00:00')
  })

  it('returns a dash for empty or invalid values', () => {
    assert.equal(formatOpportunityTime(null), '-')
    assert.equal(formatOpportunityTime(''), '-')
    assert.equal(formatOpportunityTime('not-a-time'), '-')
  })
})

describe('Shanghai day bounds', () => {
  it('sends the Beijing calendar day with an explicit offset', () => {
    assert.equal(toShanghaiDayStart('2026-10-12'), '2026-10-12T00:00:00+08:00')
    assert.equal(toShanghaiDayEnd('2026-10-12'), '2026-10-12T23:59:59.999+08:00')
  })
})
