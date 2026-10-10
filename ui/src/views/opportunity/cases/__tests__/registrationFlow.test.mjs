import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const source = fs.readFileSync(path.resolve(here, '../index.vue'), 'utf8')
const locales = ['zh-CN', 'zh-Hant', 'en-US'].map((locale) => fs.readFileSync(
  path.resolve(here, `../../../../locales/lang/${locale}/views/opportunity.ts`),
  'utf8',
))

test('registration wizard chooses a document by name and has all five steps', () => {
  assert.match(source, /v-model="registrationVisible"/)
  assert.match(source, /stepDocument/)
  assert.match(source, /stepBasics/)
  assert.match(source, /stepProducts/)
  assert.match(source, /stepScale/)
  assert.match(source, /stepReview/)
  assert.match(source, /v-model="form\.document_id"[\s\S]*<el-option/)
  assert.doesNotMatch(source, /v-model="bindingForm\.document_id"[^>]*\/>/)
})

test('project scale rows are converted to a JSON payload without a JSON textarea', () => {
  assert.match(source, /projectScaleRows/)
  assert.match(source, /metric: string; value: string; unit: string/)
  assert.match(source, /const buildProjectScale = /)
  assert.match(source, /project_scale: buildProjectScale\(\)/)
  assert.doesNotMatch(source, /projectScaleText/)
})

test('case registration copy is present in all supported locales', () => {
  for (const locale of locales) {
    assert.match(locale, /cases:\s*\{/)
    assert.match(locale, /registerTitle:/)
    assert.match(locale, /stepDocument:/)
    assert.match(locale, /scaleMetric:/)
    assert.match(locale, /statusLabel:/)
  }
})
