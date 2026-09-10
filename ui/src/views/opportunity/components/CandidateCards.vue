<template>
  <div>
    <div class="flex-between">
      <h4>{{ $t('views.opportunity.candidates') }}</h4>
      <span class="color-secondary">{{ $t('views.opportunity.candidateHint') }}</span>
    </div>
    <el-empty v-if="visible.length === 0" :description="$t('views.opportunity.noCandidate')" />
    <div
      v-if="preferred"
      class="preferred-card"
      :class="{ selected: selectedCode === preferred.product_code }"
    >
      <button
        type="button"
        class="preferred-select"
        :aria-pressed="selectedCode === preferred.product_code"
        @click="$emit('select', preferred.product_code)"
      >
        <div class="preferred-head">
          <el-tag type="primary" effect="dark">{{ $t('views.opportunity.preferred') }}</el-tag>
          <h3>{{ preferred.product_name }}</h3>
          <strong class="score">{{ scoreText(preferred) }}</strong>
        </div>
        <el-progress :percentage="normalizedScore(preferred)" :show-text="false" />
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
      </button>
      <el-button class="mt-12 evidence-button" text type="primary" @click="$emit('open-evidence', flattenEvidence(preferred))">
        {{ $t('views.opportunity.evidence') }}
      </el-button>
    </div>
    <div v-if="others.length" class="other-list">
      <button
        v-for="item in others"
        :key="item.product_code"
        type="button"
        class="other-card"
        :class="{ selected: selectedCode === item.product_code }"
        :aria-pressed="selectedCode === item.product_code"
        @click="$emit('select', item.product_code)"
      >
        <div class="other-head">
          <strong>{{ $t('views.opportunity.rankN', { n: item.rank }) }}</strong>
          <span class="other-product-name">{{ item.product_name }}</span>
          <span class="score-sm">{{ scoreText(item) }}</span>
        </div>
        <el-progress :percentage="normalizedScore(item)" :show-text="false" />
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
  (props.candidates || []).filter((item) => normalizedScore(item) > 0).sort((a, b) => (a.rank || 99) - (b.rank || 99)),
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
const normalizedScore = (item: CandidateResult) => {
  const value = Number(item.score)
  return Number.isFinite(value) ? Math.round(Math.min(100, Math.max(0, value))) : 0
}
const scoreText = (item: CandidateResult) => t('views.opportunity.matchScore', { score: normalizedScore(item) })
</script>
<style scoped>
.preferred-card,
.other-card {
  width: 100%;
  max-width: 100%;
  min-width: 0;
  box-sizing: border-box;
  text-align: left;
  border: 1px solid var(--line);
  padding: 16px 18px;
  background: var(--surface);
  cursor: pointer;
  transition: 0.16s var(--ease);
}
.preferred-card {
  margin-top: 12px;
  border-radius: 16px;
  border-color: var(--line);
  background: var(--accent-soft);
  animation: hx-rise 0.4s var(--ease);
}
.preferred-select {
  display: block;
  width: 100%;
  min-width: 0;
  border: 0;
  padding: 0;
  color: inherit;
  text-align: left;
  background: transparent;
  cursor: pointer;
}
.preferred-select:focus-visible,
.other-card:focus-visible,
.evidence-button:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 3px;
}
.other-card {
  border-radius: 14px;
}
.preferred-card:hover,
.other-card:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow);
  border-color: var(--line2);
}
.preferred-card.selected,
.other-card.selected {
  box-shadow: 0 0 0 2px var(--accent);
}
.preferred-head {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  min-width: 0;
}
.preferred-head h3 {
  margin: 0;
  min-width: 0;
  font-size: 16px;
  font-weight: 700;
  overflow-wrap: anywhere;
}
.score {
  min-width: max-content;
  font-size: 20px;
  color: var(--accent);
  white-space: nowrap;
}
.score-sm {
  font-size: 16px;
  font-weight: 700;
  color: var(--accent);
  white-space: nowrap;
}
.other-head {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.other-product-name {
  min-width: 0;
  overflow-wrap: anywhere;
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
.evidence-button {
  max-width: 100%;
}
.color-secondary {
  color: var(--muted);
}
@media (max-width: 390px) {
  .preferred-head {
    grid-template-columns: auto minmax(0, 1fr);
  }
  .score {
    grid-column: 1 / -1;
    justify-self: start;
  }
  .other-head {
    grid-template-columns: auto minmax(0, 1fr);
  }
  .score-sm {
    grid-column: 1 / -1;
    justify-self: start;
  }
}
</style>
