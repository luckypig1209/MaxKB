<template>
  <header class="hx-overview">
    <div>
      <h2>{{ title }}</h2>
      <p v-if="context" class="hx-overview__context">{{ context }}</p>
    </div>
    <div v-if="metrics.length" class="hx-overview__metrics">
      <div v-for="item in metrics" :key="item.label" class="hx-metric">
        <span>{{ item.label }}</span>
        <strong>{{ item.value }}</strong>
        <em v-if="item.hint">{{ item.hint }}</em>
      </div>
    </div>
    <div class="hx-overview__actions">
      <slot name="actions" />
    </div>
  </header>
</template>
<script setup lang="ts">
interface OverviewMetric {
  label: string
  value: string | number
  hint?: string
}

withDefaults(
  defineProps<{
    title: string
    context?: string
    metrics?: OverviewMetric[]
  }>(),
  { metrics: (): OverviewMetric[] => [] },
)
</script>
