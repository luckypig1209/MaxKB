<template>
  <el-card>
    <template #header>
      <div class="flex-between">
        <span>相似案例参考</span>
        <el-tag type="info">不作为产品标准能力依据</el-tag>
      </div>
    </template>
    <el-alert
      v-if="enhancement?.status === 'DEGRADED'"
      type="warning"
      :closable="false"
      :title="enhancement.warning || '案例参考暂不可用，产品推荐不受影响'"
    />
    <el-empty v-else-if="referenceGroups.length === 0" description="当前候选产品暂无满足条件的相似案例" />
    <div v-else class="case-groups">
      <section v-for="group in referenceGroups" :key="group.productCode" class="case-group">
        <h4>{{ group.productName }}</h4>
        <el-row :gutter="12">
          <el-col v-for="item in group.references" :key="item.case_id" :span="12">
            <el-card shadow="never" class="case-card">
              <div class="flex-between">
                <strong>{{ item.case_name }}</strong>
                <el-tag :type="item.version_compatible ? 'success' : 'warning'">
                  {{ item.version_compatible ? '版本一致' : '版本待核对' }}
                </el-tag>
              </div>
              <p class="color-secondary mt-8">{{ [item.industry, item.scenario].filter(Boolean).join(' · ') || '未标注行业场景' }}</p>
              <p v-if="item.outcomes.length" class="mt-8">成效：{{ item.outcomes.join('；') }}</p>
              <p v-if="item.applicability_boundary" class="mt-8 boundary">
                使用边界：{{ item.applicability_boundary }}
              </p>
              <div class="flex-between mt-12">
                <span class="color-secondary">相似度 {{ Math.round(item.similarity * 100) }}%</span>
                <el-button link type="primary" @click="$emit('openEvidence', item.evidence)">查看案例依据</el-button>
              </div>
            </el-card>
          </el-col>
        </el-row>
      </section>
    </div>
  </el-card>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { CandidateResult, EvidenceItem } from '@/api/type/opportunity'

const props = defineProps<{
  candidates: CandidateResult[]
  enhancement?: { status: string; count: number; warning?: string | null }
}>()

defineEmits<{
  openEvidence: [items: EvidenceItem[]]
}>()

const referenceGroups = computed(() => props.candidates
  .filter((item) => item.case_references?.length)
  .map((item) => ({
    productCode: item.product_code,
    productName: item.product_name,
    references: item.case_references,
  })))
</script>

<style scoped>
.case-groups,
.case-group + .case-group {
  margin-top: 16px;
}
.case-card {
  height: 100%;
}
.boundary {
  color: var(--el-color-warning-dark-2);
}
.color-secondary {
  color: var(--el-text-color-secondary);
}
</style>
