import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const settingsSource = fs.readFileSync(path.resolve(here, '../index.vue'), 'utf8')

test('embed settings are gated by the runtime backend flag', () => {
  assert.match(settingsSource, /const embedEnabled = ref\(false\)/)
  assert.match(settingsSource, /const embedFlagLoaded = ref\(false\)/)
  assert.match(settingsSource, /<el-tab-pane v-if="embedEnabled"[^>]+name="embed"/)
  assert.match(settingsSource, /const \{ embed_enabled: enabled, \.\.\.settingData \} = data/)
  assert.match(settingsSource, /if \(embedEnabled\.value\) \{[\s\S]*?listEmbedClients\(\)/)
  assert.match(settingsSource, /const TAB_NAMES = \['engine', 'department', 'product'\]/)
  assert.doesNotMatch(settingsSource, /const TAB_NAMES = \[[^\]]*['"]embed['"]/)
})

test('legacy embed tab query is rejected while the flag is disabled', () => {
  assert.match(settingsSource, /tab === 'embed' && embedFlagLoaded\.value && embedEnabled\.value/)
  assert.match(settingsSource, /if \(tab && !isAllowedTab\(String\(tab\)\)\)/)
  assert.match(settingsSource, /if \(String\(tab\) === 'embed' && !embedFlagLoaded\.value\) return/)
  assert.match(settingsSource, /tab: 'engine'/)
  assert.match(settingsSource, /\{ immediate: true \}/)
})
