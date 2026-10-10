<template>
  <div class="app-top-bar-container border-b">
    <div class="header-brand">
      <LogoFull height="32px" />
      <span class="hx-product-name">商机智能分析</span>
    </div>

    <div class="header-desktop">
      <div class="flex-between w-full align-center">
        <h4><el-divider class="ml-16 mr-16" direction="vertical" />{{ $t('views.system.title') }}</h4>
        <div class="flex align-center mr-8">
          <TopAbout type="system"></TopAbout>
          <el-divider class="ml-8 mr-8" direction="vertical" />
          <el-button
            link
            @click="goHome"
            style="color: var(--el-text-color-primary)"
            v-if="
              hasPermission(
                [
                  RoleConst.USER.getWorkspaceRole,
                  RoleConst.EXTENDS_USER.getWorkspaceRole,
                  RoleConst.EXTENDS_WORKSPACE_MANAGE.getWorkspaceRole,
                  RoleConst.WORKSPACE_MANAGE.getWorkspaceRole,
                ],
                'OR',
              )
            "
          >
            <AppIcon class="mr-8" iconName="app-workspace" style="font-size: 16px"></AppIcon>
            {{ $t('views.workspace.toWorkspace') }}</el-button
          >
        </div>
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
        <h4>{{ $t('views.system.title') }}</h4>
        <TopAbout type="system"></TopAbout>
        <el-button
          link
          @click="goHome"
          v-if="
            hasPermission(
              [
                RoleConst.USER.getWorkspaceRole,
                RoleConst.EXTENDS_USER.getWorkspaceRole,
                RoleConst.EXTENDS_WORKSPACE_MANAGE.getWorkspaceRole,
                RoleConst.WORKSPACE_MANAGE.getWorkspaceRole,
              ],
              'OR',
            )
          "
        >
          <AppIcon class="mr-8" iconName="app-workspace" style="font-size: 16px"></AppIcon>
          {{ $t('views.workspace.toWorkspace') }}
        </el-button>
        <Avatar></Avatar>
      </div>
    </el-drawer>
  </div>
</template>
<script setup lang="ts">
import { ref, watch } from 'vue'
import { Menu } from '@element-plus/icons-vue'
import { RoleConst } from '@/utils/permission/data'
import Avatar from './avatar/index.vue'
import TopAbout from './top-about/index.vue'
import { useRoute, useRouter } from 'vue-router'
import { hasPermission } from '@/utils/permission'

const router = useRouter()
const route = useRoute()
const menuOpen = ref(false)
const goHome = () => {
  menuOpen.value = false
  router.push('/')
}
watch(
  () => route.fullPath,
  () => {
    menuOpen.value = false
  },
)
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
