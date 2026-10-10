<template>
  <div class="analysis-actions">
    <el-select
      v-if="analysis.status === 'WAITING_CONFIRMATION'"
      v-model="selected"
      class="analysis-actions__select"
    >
      <el-option
        v-for="item in confirmable"
        :key="item.product_code"
        :label="item.product_name"
        :value="item.product_code"
      />
    </el-select>
    <div class="analysis-actions__buttons">
      <el-button v-if="analysis.report" @click="$emit('export')">导出报告</el-button>
      <el-button v-if="analysis.status === 'FAILED'" @click="$emit('retry')">
        {{ $t('views.opportunity.retry') }}
      </el-button>
      <el-button
        v-if="['ANALYZING', 'NEED_CLARIFICATION', 'FAILED'].includes(analysis.status)"
        @click="$emit('decision', 'CANCEL')"
      >
        取消商机
      </el-button>
      <el-button v-if="analysis.status === 'WAITING_CONFIRMATION'" @click="$emit('decision', 'NO_MATCH')">
        标记无匹配
      </el-button>
      <el-button v-if="analysis.status === 'WAITING_CONFIRMATION'" @click="$emit('decision', 'REJECT')">
        驳回建议
      </el-button>
      <el-button
        v-if="analysis.status === 'WAITING_CONFIRMATION'"
        type="primary"
        :disabled="!selected"
        @click="$emit('decision', selected === firstCode ? 'ACCEPT' : 'RESELECT', selected)"
      >
        {{ selected === firstCode ? '接受推荐' : '确认改选' }}
      </el-button>
    </div>
  </div>
</template>
<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { OpportunityAnalysis } from '@/api/type/opportunity'
const props = defineProps<{ analysis: OpportunityAnalysis; selected?: string }>()
defineEmits(['decision', 'retry', 'export'])
const selected = ref(props.selected || '')
const confirmable = computed(() =>
  (props.analysis.result_snapshot?.candidates || []).filter((item) => Number(item.score) > 0),
)
const firstCode = computed(() => confirmable.value[0]?.product_code || '')
watch(
  () => props.selected,
  (value) => {
    selected.value = value || ''
  },
)
</script>
<style scoped>
.analysis-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: stretch;
  gap: 10px;
  min-width: 0;
  max-width: 100%;
  box-sizing: border-box;
}
.analysis-actions__select {
  min-width: 0;
  max-width: 100%;
  flex: 1 1 220px;
}
.analysis-actions__select :deep(.el-select__wrapper) {
  min-width: 0;
  max-width: 100%;
}
.analysis-actions__buttons {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  min-width: 0;
  max-width: 100%;
}
@media (max-width: 1023px) {
  .analysis-actions {
    flex-direction: column;
  }
  .analysis-actions__select {
    flex: 1 1 auto;
    width: 100%;
  }
}
</style>
