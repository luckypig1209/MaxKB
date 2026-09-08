<template>
  <img
    v-if="theme.themeInfo?.loginLogo"
    :src="fileURL"
    :style="{ height }"
    alt="中电鸿信"
    class="mr-8"
  />
  <div v-else class="hongxin-logo" :style="{ '--hongxin-logo-height': height }">
    <img src="@/assets/logo/hongxin-mark.png" alt="" class="hongxin-logo__mark" />
    <span class="hongxin-logo__name">中电鸿信</span>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import useStore from '@/stores'

defineOptions({ name: 'LogoFull' })

defineProps({
  height: {
    type: String,
    default: '36px',
  },
})

const { theme } = useStore()

const fileURL = computed(() => {
  if (!theme.themeInfo) return ''
  if (typeof theme.themeInfo.loginLogo === 'string') return theme.themeInfo.loginLogo
  return URL.createObjectURL(theme.themeInfo.loginLogo)
})
</script>

<style lang="scss" scoped>
.hongxin-logo {
  display: inline-flex;
  align-items: center;
  flex: none;
  height: var(--hongxin-logo-height);
  white-space: nowrap;

  &__mark {
    display: block;
    width: var(--hongxin-logo-height);
    height: var(--hongxin-logo-height);
    object-fit: contain;
  }

  &__name {
    margin-left: calc(var(--hongxin-logo-height) * 0.18);
    color: #0755a5;
    font-family: 'PingFang SC', 'Microsoft YaHei', 'Noto Sans CJK SC', sans-serif;
    font-size: calc(var(--hongxin-logo-height) * 0.62);
    font-weight: 700;
    line-height: 1;
    letter-spacing: calc(var(--hongxin-logo-height) * 0.055);
  }
}
</style>
