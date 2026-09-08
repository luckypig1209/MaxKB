<template>
  <div>
    <h4>逐项比对</h4>
    <el-table :data="rows" size="small" class="mt-8" @cell-click="onCell">
      <el-table-column prop="description" :label="$t('views.opportunity.requirements')" min-width="180" />
      <el-table-column
        v-for="candidate in candidates"
        :key="candidate.product_code"
        :label="candidate.product_name"
        min-width="160"
      >
        <template #default="{ row }">
          <el-tag :type="tagType(row[candidate.product_code]?.status)">
            {{ statusText(row[candidate.product_code]?.status) }}
          </el-tag>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>
<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { CandidateResult, EvidenceItem, MatchStatus, RequirementItem } from '@/api/type/opportunity'

const props = defineProps<{ requirements: RequirementItem[]; candidates: CandidateResult[] }>()
const emit = defineEmits(['open-evidence'])
const { t } = useI18n()

const rows = computed(() =>
  (props.requirements || []).map((requirement) => {
    const row: Record<string, any> = {
      id: requirement.id,
      description: requirement.description,
    }
    for (const candidate of props.candidates) {
      row[candidate.product_code] = (candidate.match_items || []).find(
        (item) => item.requirement_id === requirement.id,
      )
    }
    return row
  }),
)

const statusText = (status?: MatchStatus) =>
  status ? t(`views.opportunity.matchStatus.${status}`) : '-'
const tagType = (status?: MatchStatus) => {
  if (status === 'FULL') return 'success'
  if (status === 'PARTIAL') return 'warning'
  if (status === 'NO') return 'danger'
  return 'info'
}
const onCell = (row: Record<string, any>, column: { label?: string }) => {
  const candidate = props.candidates.find((item) => item.product_name === column.label)
  if (!candidate) return
  const match = row[candidate.product_code]
  emit('open-evidence', (match?.evidence || []) as EvidenceItem[])
}
</script>
