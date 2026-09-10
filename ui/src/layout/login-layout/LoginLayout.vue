<template>
  <div class="login-page">
    <div class="login-shell">
      <header class="login-topbar">
        <div class="login-topbar__logo">
          <LogoFull height="40px" />
        </div>
        <el-dropdown v-if="lang" trigger="click">
          <template #dropdown>
            <el-dropdown-menu class="w-180">
              <el-dropdown-item
                v-for="(item, index) in langList"
                :key="index"
                @click="changeLang(item.value)"
                class="flex-between"
              >
                <span :class="item.value === user.getLanguage() ? 'primary' : ''">{{ item.label }}</span>
                <el-icon v-if="item.value === user.getLanguage()" class="primary"><Check /></el-icon>
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
          <el-button>
            {{ currentLanguage }}<el-icon class="el-icon--right"><ArrowDown /></el-icon>
          </el-button>
        </el-dropdown>
      </header>

      <main class="login-main">
        <section class="login-value" aria-labelledby="login-value-title">
          <span class="login-value__chip">{{ $t('views.login.brand.product') }}</span>
          <h1 id="login-value-title" class="login-value__title">{{ $t('views.login.brand.headline') }}</h1>
          <p class="login-value__desc">{{ $t('views.login.brand.description') }}</p>
          <div class="login-flow">
            <ol>
              <li class="login-flow__item">
                <span class="login-flow__index">01</span>
                <div class="login-flow__body">
                  <h3>{{ $t('views.login.brand.flowParseTitle') }}</h3>
                  <p>{{ $t('views.login.brand.flowParseDesc') }}</p>
                </div>
              </li>
              <li class="login-flow__item">
                <span class="login-flow__index">02</span>
                <div class="login-flow__body">
                  <h3>{{ $t('views.login.brand.flowMatchTitle') }}</h3>
                  <p>{{ $t('views.login.brand.flowMatchDesc') }}</p>
                </div>
              </li>
              <li class="login-flow__item">
                <span class="login-flow__index">03</span>
                <div class="login-flow__body">
                  <h3>{{ $t('views.login.brand.flowTraceTitle') }}</h3>
                  <p>{{ $t('views.login.brand.flowTraceDesc') }}</p>
                </div>
              </li>
            </ol>
          </div>
          <div v-if="customLoginImage" class="login-value__media">
            <img :src="customLoginImage" alt="" />
          </div>
        </section>
        <div class="login-panel">
          <slot />
        </div>
      </main>
    </div>
  </div>
</template>
<script setup lang="ts">
import { computed } from 'vue'
import { ArrowDown, Check } from '@element-plus/icons-vue'
import useStore from '@/stores'
import { useLocalStorage } from '@vueuse/core'
import { langList, localeConfigKey, getBrowserLang } from '@/locales/index'
import LogoFull from '@/components/logo/LogoFull.vue'

defineProps({
  lang: {
    type: Boolean,
    default: true,
  },
})

const { user, theme } = useStore()

const changeLang = (lang: string) => {
  useLocalStorage(localeConfigKey, getBrowserLang()).value = lang
  window.location.reload()
}

const currentLanguage = computed(() => {
  return langList.value?.filter((item: any) => item.value === user.getLanguage())?.[0]?.label
})

const customLoginImage = computed(() => {
  const image = theme.themeInfo?.loginImage
  if (!image) return ''
  if (typeof image === 'string') return image
  return URL.createObjectURL(image)
})
</script>
<style lang="scss">
@use './login-page.scss';
</style>
