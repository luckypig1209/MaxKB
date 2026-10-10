<template>
  <section class="progress-card">
    <header class="progress-head">
      <span class="status-mark" :class="statusTone" aria-hidden="true">{{ statusGlyph }}</span>
      <div class="progress-copy">
        <h3>{{ title }}</h3>
        <p class="progress-detail" aria-live="polite">{{ detail }}</p>
      </div>
      <el-button
        v-if="canCancel"
        class="cancel-btn"
        :loading="cancelling"
        :disabled="cancelling"
        @click="$emit('cancel')"
      >
        {{ $t('views.opportunity.cancelAnalysis') }}
      </el-button>
    </header>
    <div v-if="showMeter" class="meter-block">
      <div
        class="meter"
        role="progressbar"
        :aria-label="progressBarLabel"
        :aria-valuenow="percent"
        aria-valuemin="0"
        aria-valuemax="100"
        :aria-valuetext="percent + '%'"
      >
        <span class="meter-fill" :style="{ width: percent + '%' }" />
      </div>
      <div class="meter-meta">
        <strong>{{ percent }}%</strong>
        <span v-if="showUnits">{{ $t('views.opportunity.progressUnits', { done: completedUnits, total: totalUnits }) }}</span>
      </div>
    </div>
    <p v-if="showElapsed" class="time-row">
      <span>{{ $t('views.opportunity.waitedFor', { time: elapsedLabel }) }}</span>
      <span v-if="lastUpdatedLabel">{{ $t('views.opportunity.lastUpdated', { time: lastUpdatedLabel }) }}</span>
    </p>
    <p v-if="staleRunning" class="stale-note">{{ $t('views.opportunity.modelStillRunning') }}</p>
    <ul v-if="counterItems.length" class="counter-row">
      <li v-for="item in counterItems" :key="item.key">{{ item.label }}</li>
    </ul>
    <ol v-if="steps.length" class="step-list">
      <li v-for="step in steps" :key="step.key" :class="step.status">
        <span class="dot" aria-hidden="true" />
        <div>
          <strong>{{ step.label }}</strong>
          <span class="step-status">{{ stepStatusText(step.status) }}</span>
          <p v-if="step.status === 'active' && progressDetail" class="step-detail">{{ progressDetail }}</p>
        </div>
      </li>
    </ol>
  </section>
</template>
<script setup lang="ts">
import { computed, onUnmounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import type { AnalysisProgressSnapshot, AnalysisStatus } from '@/api/type/opportunity'

const props = defineProps<{
  status: AnalysisStatus | string
  error?: string | null
  progress?: AnalysisProgressSnapshot
  cancelling?: boolean
}>()
defineEmits<{ (e: 'cancel'): void }>()
const { t } = useI18n()
const now = ref(Date.now())
const ticker = window.setInterval(() => {
  now.value = Date.now()
}, 1000)
onUnmounted(() => window.clearInterval(ticker))

const analyzing = computed(() => props.status === 'ANALYZING')
const cancelled = computed(() => props.status === 'CLOSED' && props.progress?.state === 'CANCELLED')
const canCancel = computed(() => analyzing.value)
const steps = computed(() => props.progress?.steps || [])
const progressDetail = computed(() => props.progress?.detail || '')
const percent = computed(() => Math.max(0, Math.min(100, Number(props.progress?.percent) || 0)))
const completedUnits = computed(() => Number(props.progress?.completed_units) || 0)
const totalUnits = computed(() => Math.max(Number(props.progress?.total_units) || 0, steps.value.length || 5))
const isProgressV2 = computed(() => Number(props.progress?.version) >= 2)
const showUnits = computed(() => isProgressV2.value)
const showElapsed = computed(() => (
  analyzing.value && Boolean(props.progress?.started_at || Number(props.progress?.elapsed_ms) > 0)
))
const showMeter = computed(() => Boolean(props.progress && (analyzing.value || props.progress.percent != null)))
const progressBarLabel = computed(() => t('views.opportunity.progressBarLabel', { percent: percent.value }))
const stepStatusText = (status?: string) => {
  if (status === 'done') return t('views.opportunity.stepDone')
  if (status === 'active') return t('views.opportunity.stepActive')
  return t('views.opportunity.stepPending')
}

const title = computed(() => {
  if (cancelled.value) return t('views.opportunity.cancelled')
  const map: Record<string, string> = {
    ANALYZING: t('views.opportunity.analyzing'),
    NEED_CLARIFICATION: t('views.opportunity.clarification'),
    WAITING_CONFIRMATION: t('views.opportunity.waiting'),
    CONFIRMED: t('views.opportunity.confirmed'),
    FAILED: t('views.opportunity.failed'),
    CLOSED: t('views.opportunity.closed'),
  }
  return map[props.status] || props.status
})

const detail = computed(() => {
  if (props.error) return props.error
  if (analyzing.value) return progressDetail.value || t('views.opportunity.analyzingHint')
  if (props.status === 'NEED_CLARIFICATION') return t('views.opportunity.clarificationHint')
  if (props.status === 'WAITING_CONFIRMATION') return t('views.opportunity.resultReadyHint')
  if (cancelled.value) return t('views.opportunity.cancelledHint')
  return progressDetail.value
})

const statusTone = computed(() => {
  if (props.status === 'FAILED') return 'is-bad'
  if (props.status === 'CONFIRMED' || props.status === 'WAITING_CONFIRMATION') return 'is-ok'
  if (props.status === 'NEED_CLARIFICATION') return 'is-warn'
  if (cancelled.value) return 'is-muted'
  if (analyzing.value) return 'is-on'
  return 'is-muted'
})

const statusGlyph = computed(() => {
  if (props.status === 'FAILED') return '!'
  if (props.status === 'CONFIRMED' || props.status === 'WAITING_CONFIRMATION') return '✓'
  if (props.status === 'NEED_CLARIFICATION') return '?'
  if (cancelled.value) return '×'
  if (analyzing.value) return '…'
  return '·'
})

const parseTime = (value?: string) => {
  if (!value) return NaN
  const parsed = Date.parse(value)
  return Number.isNaN(parsed) ? NaN : parsed
}

const elapsedLabel = computed(() => {
  void now.value
  const started = parseTime(props.progress?.started_at)
  const elapsedMs = Number.isNaN(started)
    ? Number(props.progress?.elapsed_ms) || 0
    : Math.max(0, now.value - started)
  const total = Math.floor(elapsedMs / 1000)
  const minutes = Math.floor(total / 60)
  const seconds = total % 60
  if (minutes <= 0) return t('views.opportunity.elapsedSeconds', { n: seconds })
  return t('views.opportunity.elapsedMinutes', { m: minutes, s: seconds })
})

const lastUpdatedLabel = computed(() => {
  void now.value
  const updated = parseTime(props.progress?.last_updated_at)
  if (Number.isNaN(updated)) return ''
  const delta = Math.max(0, Math.floor((now.value - updated) / 1000))
  if (delta < 5) return t('views.opportunity.justNow')
  if (delta < 60) return t('views.opportunity.secondsAgo', { n: delta })
  return t('views.opportunity.minutesAgo', { n: Math.floor(delta / 60) })
})

const staleRunning = computed(() => {
  void now.value
  if (!analyzing.value || props.progress?.state === 'FAILED') return false
  const updated = parseTime(props.progress?.last_updated_at)
  if (Number.isNaN(updated)) return false
  return now.value - updated >= 30000
})

const counters = computed(() => props.progress?.counters || {})
const counterItems = computed(() => {
  const data = counters.value
  const items = []
  if (data.queries_total || data.queries_done) {
    items.push({
      key: 'retrieve',
      label: t('views.opportunity.retrieveCount', {
        done: data.queries_done || 0,
        total: data.queries_total || 0,
      }),
    })
  }
  if (data.retrieved_hits) {
    items.push({
      key: 'hits',
      label: t('views.opportunity.hitCount', { count: data.retrieved_hits }),
    })
  }
  if (data.unique_paragraphs) {
    items.push({
      key: 'paragraphs',
      label: t('views.opportunity.paragraphCount', { count: data.unique_paragraphs }),
    })
  }
  if (data.products_found) {
    items.push({
      key: 'found',
      label: t('views.opportunity.productFound', { count: data.products_found }),
    })
  }
  if (data.products_found || data.products_matched) {
    items.push({
      key: 'match',
      label: t('views.opportunity.matchCount', {
        done: data.products_matched || 0,
        total: data.products_found || 0,
      }),
    })
  }
  return items
})
</script>
<style scoped>
.progress-card {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.progress-head {
  display: flex;
  align-items: flex-start;
  gap: 10px;
}
.progress-copy {
  min-width: 0;
  flex: 1;
}
.progress-copy h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 700;
  color: var(--ink);
}
.progress-detail {
  margin: 4px 0 0;
  font-size: 12.5px;
  line-height: 1.5;
  color: var(--ink2);
}
.status-mark {
  width: 22px;
  height: 22px;
  border-radius: 8px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 700;
  flex-shrink: 0;
  margin-top: 1px;
  color: var(--muted);
  background: var(--surface2);
}
.status-mark.is-on {
  color: var(--accent-ink);
  background: var(--accent-soft);
}
.status-mark.is-ok {
  color: var(--green);
  background: var(--green-s);
}
.status-mark.is-warn {
  color: var(--amber);
  background: var(--amber-s);
}
.status-mark.is-bad {
  color: var(--red);
  background: var(--red-s);
}
.cancel-btn {
  flex-shrink: 0;
}
.meter-block {
  display: grid;
  gap: 6px;
}
.meter {
  height: 8px;
  border-radius: 8px;
  background: var(--surface2);
  overflow: hidden;
}
.meter-fill {
  display: block;
  height: 100%;
  border-radius: 8px;
  background: var(--accent);
  transition: width 0.16s var(--ease);
}
@media (prefers-reduced-motion: reduce) {
  .meter-fill {
    transition: none;
  }
}
.meter-meta,
.time-row,
.counter-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 14px;
  margin: 0;
  font-size: 12px;
  color: var(--ink2);
}
.meter-meta strong {
  color: var(--ink);
}
.stale-note {
  margin: 0;
  font-size: 12px;
  color: var(--amber);
  background: var(--amber-s);
  border-radius: 8px;
  padding: 6px 10px;
}
.counter-row {
  list-style: none;
  padding: 0;
}
.counter-row li {
  background: var(--surface2);
  border-radius: 8px;
  padding: 5px 11px;
  font-size: 12px;
  color: var(--ink2);
}
.step-list {
  list-style: none;
  margin: 0;
  padding: 4px 0 0;
}
.step-list li {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  padding: 6px 0;
  color: var(--muted);
  font-size: 13.5px;
}
.step-list li.active {
  color: var(--accent);
}
.step-list li.done {
  color: var(--green);
}
.step-status {
  margin-left: 8px;
  font-size: 12px;
  font-weight: 500;
  color: var(--muted);
}
.active .step-status {
  color: var(--accent-ink);
}
.done .step-status {
  color: var(--green);
}
.dot {
  width: 7px;
  height: 7px;
  margin-top: 6px;
  border-radius: 50%;
  background: var(--line2);
  flex-shrink: 0;
}
.done .dot {
  background: var(--green);
}
.active .dot {
  background: var(--accent);
  box-shadow: 0 0 0 4px var(--accent-soft);
}
.step-detail {
  margin: 4px 0 0;
  font-size: 12.5px;
  color: var(--ink2);
}
</style>
