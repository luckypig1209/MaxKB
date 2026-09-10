<template>
  <div>
    <el-input
      v-model="text"
      type="textarea"
      :rows="8"
      :placeholder="$t('views.opportunity.requirementPlaceholder')"
    />
    <div class="flex-right mt-12">
      <el-button
        :type="primary ? 'primary' : 'default'"
        :loading="loading"
        :disabled="!text.trim()"
        @click="$emit('submit')"
      >
        {{ $t('views.opportunity.create') }}
      </el-button>
    </div>
  </div>
</template>
<script setup lang="ts">
import { computed } from 'vue'
const props = withDefaults(defineProps<{ modelValue: string; loading?: boolean; primary?: boolean }>(), {
  primary: true,
})
const emit = defineEmits(['update:modelValue', 'submit'])
const text = computed({
  get: () => props.modelValue,
  set: (value: string) => emit('update:modelValue', value),
})
</script>
