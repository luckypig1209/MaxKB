<template>
  <div class="app-top-bar-container border-b">
    <div class="header-brand">
      <LogoFull height="32px" />
      <span class="hx-product-name">商机智能分析</span>
    </div>

    <div class="header-desktop">
      <div class="flex-between w-full">
        <div class="ml-24 flex align-center w-120">
          <el-divider
            class="mr-8"
            direction="vertical"
            v-if="hasPermission(EditionConst.IS_EE, 'OR')"
          />
          <WorkspaceDropdown
            v-if="hasPermission(EditionConst.IS_EE, 'OR')"
            :data="user.workspace_list"
            :currentWorkspace="currentWorkspace"
            @changeWorkspace="changeWorkspace"
          />
        </div>
        <TopMenu></TopMenu>
        <TopAbout class="mr-12"></TopAbout>
      </div>
      <Avatar></Avatar>
    </div>

    <div class="header-mobile">
      <el-button text class="header-menu-btn" :aria-label="$t('layout.openMenu')" @click="menuOpen = true">
        <el-icon :size="20"><Menu /></el-icon>
      </el-button>
    </div>

    <el-drawer
      v-model="menuOpen"
      direction="rtl"
      size="280px"
      append-to-body
      :title="$t('layout.menu')"
    >
      <div class="mobile-nav">
        <WorkspaceDropdown
          v-if="hasPermission(EditionConst.IS_EE, 'OR')"
          :data="user.workspace_list"
          :currentWorkspace="currentWorkspace"
          @changeWorkspace="changeWorkspace"
        />
        <TopMenu></TopMenu>
        <TopAbout></TopAbout>
        <Avatar></Avatar>
      </div>
    </el-drawer>
  </div>
</template>
<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Menu } from '@element-plus/icons-vue'
import TopMenu from './top-menu/index.vue'
import Avatar from './avatar/index.vue'
import TopAbout from './top-about/index.vue'
import { EditionConst } from '@/utils/permission/data'
import { hasPermission } from '@/utils/permission/index'
import type { WorkspaceItem } from '@/api/type/workspace'
import useStore from '@/stores'
const router = useRouter()
const route = useRoute()
const menuOpen = ref(false)

const { user } = useStore()
const currentWorkspace = computed(() => {
  return user.workspace_list.find((w) => w.id == user.workspace_id)
})

watch(
  () => route.fullPath,
  () => {
    menuOpen.value = false
  },
)

function changeWorkspace(item: WorkspaceItem) {
  const {
    meta: { activeMenu },
  } = route as any
  if (item.id === user.workspace_id) return
  user.setWorkspaceId(item.id || 'default')
  if (activeMenu.includes('application') && route.path != '/application') {
    router.push('/application')
  } else if (activeMenu.includes('knowledge') && route.path != '/knowledge') {
    router.push('/knowledge')
  } else {
    window.location.reload()
  }
}
</script>
<style lang="scss" scoped>
.app-top-bar-container {
  height: var(--app-header-height);
  box-sizing: border-box;
  padding: 0 20px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  width: 100%;
}
.header-brand {
  display: flex;
  align-items: center;
  flex-shrink: 0;
  min-width: 0;
}
.header-desktop {
  display: flex;
  align-items: center;
  flex: 1;
  min-width: 0;
}
.header-mobile {
  display: none;
  flex-shrink: 0;
}
.header-menu-btn {
  padding: 8px;
}
.mobile-nav {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.mobile-nav :deep(.top-menu-container) {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  height: auto;
}
.mobile-nav :deep(.menu-item-container) {
  margin: 0;
  height: auto;
}
.mobile-nav :deep(.title-text) {
  display: inline;
}
@media (max-width: 1023px) {
  .app-top-bar-container {
    padding: 0 12px;
  }
  .header-desktop {
    display: none;
  }
  .header-mobile {
    display: flex;
    align-items: center;
  }
}
</style>
