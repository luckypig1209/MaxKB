<template>
  <div class="clarify">
    <h4>{{ $t('views.opportunity.clarification') }}</h4>
    <p class="color-secondary">{{ $t('views.opportunity.clarificationFillHint') }}</p>
    <ol>
      <li v-for="item in questions" :key="item">{{ item }}</li>
    </ol>
    <el-input
      v-model="answer"
      type="textarea"
      :rows="6"
      class="mt-12"
      :placeholder="$t('views.opportunity.clarificationPlaceholder')"
    />
    <div class="flex-right mt-12">
      <el-button type="primary" :disabled="!answer.trim()" :loading="loading" @click="submit">
        {{ $t('views.opportunity.submitClarification') }}
      </el-button>
    </div>
  </div>
</template>
<script setup lang="ts">
import { ref } from 'vue'
defineProps<{ questions: string[]; loading?: boolean }>()
const emit = defineEmits(['submit'])
const answer = ref('')
const submit = () => {
  if (!answer.value.trim()) return
  emit('submit', answer.value.trim())
}
</script>
<style scoped>
.clarify ol {
  margin: 8px 0 0;
  padding-left: 20px;
  line-height: 1.7;
}
.color-secondary {
  color: var(--el-text-color-secondary);
}
</style>
