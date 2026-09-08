<template>
  <div>
    <div class="flex-between">
      <h4>{{ $t('views.opportunity.candidates') }}</h4>
      <span class="color-secondary">{{ $t('views.opportunity.candidateHint') }}</span>
    </div>
    <el-empty v-if="visible.length === 0" :description="$t('views.opportunity.noCandidate')" />
    <article
      v-if="preferred"
      class="preferred-card"
      :class="{ selected: selectedCode === preferred.product_code }"
      @click="$emit('select', preferred.product_code)"
    >
      <div class="preferred-head">
        <el-tag type="primary" effect="dark">{{ $t('views.opportunity.preferred') }}</el-tag>
        <h3>{{ preferred.product_name }}</h3>
        <strong class="score">{{ preferred.score }}</strong>
      </div>
      <el-progress :percentage="Math.min(preferred.score, 100)" :show-text="false" />
      <p class="level">{{ $t(`views.opportunity.recommendation.${preferred.recommendation_level}`) }}</p>
      <p class="color-secondary">{{ departmentText(preferred) }}</p>
      <div class="counts">
        <el-tag type="success" effect="plain">{{ $t('views.opportunity.matchStatus.FULL') }} {{ counts(preferred).FULL }}</el-tag>
        <el-tag type="warning" effect="plain">{{ $t('views.opportunity.matchStatus.PARTIAL') }} {{ counts(preferred).PARTIAL }}</el-tag>
        <el-tag type="info" effect="plain">{{ $t('views.opportunity.matchStatus.INSUFFICIENT') }} {{ counts(preferred).INSUFFICIENT }}</el-tag>
      </div>
      <p v-if="highlight(preferred)" class="why">{{ highlight(preferred) }}</p>
      <div v-if="preferred.case_references?.length" class="case-tags">
        <el-tag v-for="item in preferred.case_references.slice(0, 3)" :key="item.case_id" type="info">
          {{ item.case_name }}
        </el-tag>
      </div>
      <el-button class="mt-12" text type="primary" @click.stop="$emit('open-evidence', flattenEvidence(preferred))">
        {{ $t('views.opportunity.evidence') }}
      </el-button>
    </article>
    <div v-if="others.length" class="other-list">
      <button
        v-for="item in others"
        :key="item.product_code"
        type="button"
        class="other-card"
        :class="{ selected: selectedCode === item.product_code }"
        @click="$emit('select', item.product_code)"
      >
        <div class="flex-between">
          <strong>{{ $t('views.opportunity.rankN', { n: item.rank }) }} {{ item.product_name }}</strong>
          <span class="score-sm">{{ item.score }}</span>
        </div>
        <el-progress :percentage="Math.min(item.score, 100)" :show-text="false" />
        <p class="color-secondary">
          {{ $t(`views.opportunity.recommendation.${item.recommendation_level}`) }} · {{ departmentText(item) }}
        </p>
      </button>
    </div>
  </div>
</template>
<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { CandidateResult, EvidenceItem } from '@/api/type/opportunity'

const props = defineProps<{ candidates: CandidateResult[]; selectedCode?: string }>()
defineEmits<{
  (e: 'open-evidence', items: EvidenceItem[]): void
  (e: 'select', code: string): void
}>()
const { t } = useI18n()
const visible = computed(() =>
  (props.candidates || []).filter((item) => Number(item.score) > 0).sort((a, b) => (a.rank || 99) - (b.rank || 99)),
)
const preferred = computed(() => visible.value[0])
const others = computed(() => visible.value.slice(1))
const counts = (item: CandidateResult) => {
  const result = { FULL: 0, PARTIAL: 0, NO: 0, INSUFFICIENT: 0 }
  for (const match of item.match_items || []) {
    if (match.status === 'FULL') result.FULL += 1
    else if (match.status === 'PARTIAL') result.PARTIAL += 1
    else if (match.status === 'NO') result.NO += 1
    else result.INSUFFICIENT += 1
  }
  return result
}
const departmentText = (item: CandidateResult) =>
  item.department?.status === 'RESOLVED'
    ? item.department.owner_department_name
    : t('views.opportunity.departmentUnresolved')
const highlight = (item: CandidateResult) => {
  const full = (item.match_items || []).find((match) => match.status === 'FULL' && match.reason)
  return full?.reason || item.risks?.[0] || ''
}
const flattenEvidence = (item: CandidateResult): EvidenceItem[] => {
  return (item.match_items || []).flatMap((match) => match.evidence || [])
}
</script>
<style scoped>
.preferred-card,
.other-card {
  width: 100%;
  text-align: left;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 12px;
  padding: 16px 18px;
  background: var(--el-bg-color);
  cursor: pointer;
}
.preferred-card {
  margin-top: 12px;
  border-color: var(--el-color-primary-light-5);
  background: var(--el-color-primary-light-9);
}
.preferred-card.selected,
.other-card.selected {
  box-shadow: 0 0 0 2px var(--el-color-primary-light-7);
}
.preferred-head {
  display: flex;
  align-items: center;
  gap: 10px;
}
.preferred-head h3 {
  margin: 0;
  font-size: 18px;
}
.score {
  margin-left: auto;
  font-size: 28px;
  color: var(--el-color-primary);
}
.score-sm {
  font-size: 18px;
  font-weight: 700;
  color: var(--el-color-primary);
}
.level,
.why,
.counts {
  margin-top: 8px;
}
.counts {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.case-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 10px;
}
.other-list {
  display: grid;
  gap: 10px;
  margin-top: 12px;
}
.other-card {
  border-radius: 10px;
}
.color-secondary {
  color: var(--el-text-color-secondary);
}
</style>
