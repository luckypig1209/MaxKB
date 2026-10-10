import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const opportunityRoot = path.resolve(here, '../..')
const stylesRoot = path.resolve(opportunityRoot, '../../styles')

function read(rel) {
  return fs.readFileSync(path.join(opportunityRoot, rel), 'utf8')
}

function styleBlock(source) {
  const start = source.lastIndexOf('<style')
  assert.notEqual(start, -1)
  return source.slice(start)
}

test('embed shell can shrink and does not hide page overflow', () => {
  const style = styleBlock(read('embed/index.vue'))
  assert.match(style, /\.embed-shell[\s\S]*min-width:\s*0/)
  assert.match(style, /\.embed-content[\s\S]*min-width:\s*0/)
  assert.match(style, /\.embed-content[\s\S]*max-width:\s*100%/)
  assert.doesNotMatch(style, /overflow-x:\s*hidden/)
})

test('analysis actions wrap instead of a fixed 240px row', () => {
  const source = read('components/AnalysisActions.vue')
  const style = styleBlock(source)
  assert.doesNotMatch(source, /width:\s*240px/)
  assert.match(source, /class="analysis-actions"/)
  assert.match(style, /flex-wrap:\s*wrap/)
  assert.match(style, /flex-direction:\s*column/)
})

test('match matrix keeps wide tables inside a local scroller', () => {
  const source = read('components/MatchMatrix.vue')
  const style = styleBlock(source)
  assert.match(source, /class="match-matrix__scroll"/)
  assert.match(style, /overflow-x:\s*auto/)
  assert.doesNotMatch(style, /overflow-x:\s*hidden/)
})

test('workspace children can shrink below intrinsic table width', () => {
  const source = fs.readFileSync(path.join(stylesRoot, 'hx-theme.scss'), 'utf8')
  assert.match(source, /\.hx-workspace\s*>\s*\*[\s\S]*min-width:\s*0/)
  assert.match(source, /\.hx-workspace\s*>\s*\*[\s\S]*max-width:\s*100%/)
})
