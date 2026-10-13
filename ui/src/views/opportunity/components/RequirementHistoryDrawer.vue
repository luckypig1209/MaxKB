<template>
  <el-drawer v-model="visible" title="需求画像版本历史" size="560px" @open="load">
    <el-empty v-if="!loading && versions.length === 0" description="暂无画像版本" />
    <el-timeline v-loading="loading">
      <el-timeline-item
        v-for="item in versions"
        :key="item.id"
        :timestamp="formatTime(item.create_time)"
      >
        <div class="flex-between">
          <strong>V{{ item.version }}</strong>
          <el-tag size="small" type="info">{{ sourceText(item.source) }}</el-tag>
        </div>
        <div class="color-secondary mt-4">澄清轮次：{{ item.clarification_round }}</div>
        <div class="mt-8">场景：{{ item.profile.business_scenarios.join('、') || '-' }}</div>
        <div class="mt-4">需求：{{ requirementText(item) }}</div>
      </el-timeline-item>
    </el-timeline>
  </el-drawer>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import opportunityApi from '@/api/opportunity'
import type { RequirementProfileVersion } from '@/api/type/opportunity'
import { formatOpportunityTime } from '../utils/time'

const props = defineProps<{ modelValue: boolean; analysisId?: string }>()
const emit = defineEmits<{ (e: 'update:modelValue', value: boolean): void }>()
const loading = ref(false)
const versions = ref<RequirementProfileVersion[]>([])
const visible = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value),
})

const load = () => {
  if (!props.analysisId) return
  opportunityApi.getRequirementVersions(props.analysisId, loading).then((res) => {
    versions.value = res.data || []
  })
}
const sourceText = (source: RequirementProfileVersion['source']) =>
  source === 'CLARIFICATION' ? '参数补充后' : '首次解析'
const formatTime = formatOpportunityTime
const requirementText = (item: RequirementProfileVersion) =>
  item.profile.requirements.map((requirement) => requirement.description).join('；') || '-'
</script>

<style scoped>
.color-secondary {
  color: var(--el-text-color-secondary);
}
</style>
