<template>
  <el-collapse>
    <el-collapse-item :title="title" name="profile">
      <div class="chip-row">
        <el-tag v-for="item in profile.business_scenarios || []" :key="`s-${item}`" type="primary" effect="plain">
          {{ item }}
        </el-tag>
        <el-tag v-for="item in profile.pain_points || []" :key="`p-${item}`" type="warning" effect="plain">
          {{ item }}
        </el-tag>
      </div>
      <div class="req-list">
        <div v-for="item in profile.requirements || []" :key="item.id" class="req-item">
          <el-tag :type="priorityType(item.priority)" size="small">{{ priorityText(item.priority) }}</el-tag>
          <span>{{ item.description }}</span>
        </div>
      </div>
      <p v-if="profile.constraints?.length" class="color-secondary mt-8">
        {{ $t('views.opportunity.constraints') }}：{{ profile.constraints.join('；') }}
      </p>
      <el-button v-if="version" class="mt-8" text type="primary" @click="$emit('show-history')">
        {{ $t('views.opportunity.currentVersion', { version }) }}
      </el-button>
      <p v-if="pendingRecommendation" class="pending-note">{{ $t('views.opportunity.recommendationPending') }}</p>
    </el-collapse-item>
  </el-collapse>
</template>
<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { RequirementProfile } from '@/api/type/opportunity'
const props = defineProps<{ profile: RequirementProfile; version?: number | null; pendingRecommendation?: boolean }>()
defineEmits<{ (e: 'show-history'): void }>()
const { t } = useI18n()
const title = computed(() => t('views.opportunity.profileSummary', { count: props.profile.requirements?.length || 0 }))
const priorityType = (priority?: string) => {
  if (priority === 'must') return 'danger'
  if (priority === 'should') return 'warning'
  return 'info'
}
const priorityText = (priority?: string) => {
  if (priority === 'must') return t('views.opportunity.priorityMust')
  if (priority === 'should') return t('views.opportunity.priorityShould')
  return t('views.opportunity.priorityNice')
}
</script>
<style scoped>
.chip-row,
.req-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.req-list {
  flex-direction: column;
  margin-top: 12px;
}
.req-item {
  display: flex;
  gap: 8px;
  align-items: flex-start;
}
.color-secondary {
  color: var(--muted);
}
.pending-note {
  margin: 8px 0 0;
  font-size: 12px;
  color: var(--amber);
  background: var(--amber-s);
  border-radius: 8px;
  padding: 6px 10px;
}
</style>
