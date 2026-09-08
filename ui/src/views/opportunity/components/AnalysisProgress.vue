<template>
  <div class="progress-panel">
    <el-alert :type="alertType" :closable="false" :title="title" :description="detail" show-icon />
    <ol v-if="steps.length" class="step-list">
      <li v-for="step in steps" :key="step.key" :class="step.status">
        <span class="dot" />
        <div>
          <strong>{{ step.label }}</strong>
          <p v-if="step.status === 'active' && progressDetail" class="step-detail">{{ progressDetail }}</p>
        </div>
      </li>
    </ol>
  </div>
</template>
<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { OpportunityAnalysis } from '@/api/type/opportunity'

const props = defineProps<{
  status: string
  error?: string | null
  progress?: NonNullable<OpportunityAnalysis['result_snapshot']>['progress']
}>()
const { t } = useI18n()
const title = computed(() => {
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
const steps = computed(() => props.progress?.steps || [])
const progressDetail = computed(() => props.progress?.detail || '')
const detail = computed(() => {
  if (props.error) return props.error
  if (props.status === 'ANALYZING') {
    return progressDetail.value || t('views.opportunity.analyzingHint')
  }
  if (props.status === 'NEED_CLARIFICATION') return t('views.opportunity.clarificationHint')
  if (props.status === 'WAITING_CONFIRMATION') return t('views.opportunity.resultReadyHint')
  return ''
})
const alertType = computed(() => {
  if (props.status === 'FAILED') return 'error'
  if (props.status === 'NEED_CLARIFICATION') return 'warning'
  if (props.status === 'CONFIRMED') return 'success'
  if (props.status === 'WAITING_CONFIRMATION') return 'success'
  if (props.status === 'ANALYZING') return 'info'
  return 'info'
})
</script>
<style scoped>
.progress-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.step-list {
  list-style: none;
  margin: 0;
  padding: 4px 4px 0;
}
.step-list li {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  padding: 6px 0;
  color: var(--el-text-color-secondary);
}
.step-list li.active {
  color: var(--el-color-primary);
}
.step-list li.done {
  color: var(--el-color-success);
}
.dot {
  width: 10px;
  height: 10px;
  margin-top: 6px;
  border-radius: 50%;
  background: var(--el-border-color);
  flex-shrink: 0;
}
.done .dot {
  background: var(--el-color-success);
}
.active .dot {
  background: var(--el-color-primary);
  box-shadow: 0 0 0 4px var(--el-color-primary-light-8);
}
.step-detail {
  margin: 4px 0 0;
  font-size: 13px;
}
</style>
