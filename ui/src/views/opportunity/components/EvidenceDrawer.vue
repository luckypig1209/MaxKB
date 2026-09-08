<template>
  <el-drawer v-model="visible" :title="$t('views.opportunity.evidence')" size="40%">
    <el-empty v-if="evidence.length === 0" description="暂无允许展示的证据" />
    <el-card v-for="item in evidence" :key="item.paragraph_id" class="mb-12">
      <div class="flex-between">
        <strong>{{ item.document_name }}</strong>
        <span>v{{ item.document_version }}</span>
      </div>
      <p class="mt-8">{{ item.title }}</p>
      <p class="color-secondary mt-8">{{ item.content_excerpt }}</p>
    </el-card>
  </el-drawer>
</template>
<script setup lang="ts">
import { computed } from 'vue'
import type { EvidenceItem } from '@/api/type/opportunity'
const props = defineProps<{ modelValue: boolean; evidence: EvidenceItem[] }>()
const emit = defineEmits(['update:modelValue'])
const visible = computed({
  get: () => props.modelValue,
  set: (value: boolean) => emit('update:modelValue', value),
})
</script>
<style scoped>
.color-secondary {
  color: var(--el-text-color-secondary);
}
</style>
