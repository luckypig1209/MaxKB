<template>
  <img src="@/assets/logo/hongxin-mark.png" :height="height" alt="中电鸿信" />
</template>

<script setup lang="ts">
defineOptions({ name: 'LogoIcon' })

defineProps({
  height: {
    type: String,
    default: '36px',
  },
})
</script>
