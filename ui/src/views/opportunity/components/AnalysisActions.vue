<template>
  <div class="flex-between">
    <el-select v-if="analysis.status === 'WAITING_CONFIRMATION'" v-model="selected" style="width: 240px">
      <el-option
        v-for="item in confirmable"
        :key="item.product_code"
        :label="item.product_name"
        :value="item.product_code"
      />
    </el-select>
    <div>
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
