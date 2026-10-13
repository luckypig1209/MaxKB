<template>
  <section v-if="logs.length" class="hx-block">
    <div class="flex-between">
      <h3 class="hx-panel__title">商机操作记录</h3>
      <span v-if="report" class="hx-tag">{{ report.report_no }} · V{{ report.version }}</span>
    </div>
    <el-timeline>
      <el-timeline-item v-for="item in logs" :key="item.id" :timestamp="formatTime(item.create_time)">
        <strong>{{ actionText(item.action) }}</strong>
        <span v-if="reason(item.detail)" class="color-secondary ml-8">{{ reason(item.detail) }}</span>
      </el-timeline-item>
    </el-timeline>
  </section>
</template>

<script setup lang="ts">
import type { OpportunityAnalysis } from '@/api/type/opportunity'
import { formatOpportunityTime } from '../utils/time'

defineProps<{
  logs: NonNullable<OpportunityAnalysis['audit_logs']>
  report?: OpportunityAnalysis['report']
}>()

const actionText = (action: string) => ({
  ANALYSIS_CREATED: '创建商机分析',
  CLARIFICATION_REQUIRED: '等待补充参数',
  CLARIFICATION_SUBMITTED: '已补充参数',
  REQUIREMENT_PROFILE_VERSIONED: '保存需求画像版本',
  ANALYSIS_RETRIED: '重新分析',
  REPORT_GENERATED: '生成报告快照',
  DECISION_ACCEPT: '接受推荐',
  DECISION_RESELECT: '改选产品',
  DECISION_REJECT: '驳回建议',
  DECISION_NO_MATCH: '标记无匹配',
  DECISION_CANCEL: '取消商机',
}[action] || action)
const formatTime = formatOpportunityTime
const reason = (detail: Record<string, unknown>) => typeof detail?.reason === 'string' ? detail.reason : ''
</script>

<style scoped>
.hx-panel__title {
  margin: 0;
}
.color-secondary {
  color: var(--muted);
}
</style>
