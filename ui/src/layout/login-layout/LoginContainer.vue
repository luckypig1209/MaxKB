<template>
  <div class="login-container">
    <div v-if="showMobileBrand" class="login-mobile-brand">
      <LogoFull height="40px" />
    </div>
    <section class="login-card">
      <header v-if="title || subTitle">
        <h2 class="login-card__title">{{ title }}</h2>
        <p v-if="subTitle" class="login-card__subtitle">{{ subTitle }}</p>
      </header>
      <slot />
      <p v-if="showSecurityNote" class="login-security">{{ $t('views.login.securityNote') }}</p>
    </section>
  </div>
</template>
<script setup lang="ts">
import LogoFull from '@/components/logo/LogoFull.vue'

withDefaults(
  defineProps<{
    title?: string
    subTitle?: string
    showMobileBrand?: boolean
    showSecurityNote?: boolean
  }>(),
  {
    showMobileBrand: true,
    showSecurityNote: false,
  },
)
</script>
<style lang="scss" scoped>
.login-container {
  width: 100%;
}
</style>
