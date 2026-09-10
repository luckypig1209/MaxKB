<template>
  <div class="flex align-center top-about">
    <el-tooltip
      v-if="
        hasPermission(
          [
            RoleConst.WORKSPACE_MANAGE.getWorkspaceRole,
            PermissionConst.TRIGGER_READ.getWorkspacePermissionWorkspaceManageRole,
          ],
          'OR',
        ) && type === 'workspace'
      "
      effect="dark"
      :content="$t('views.trigger.title')"
      placement="top"
    >
      <el-button
        text
        @click="router.push({ name: 'trigger' })"
        :class="route.path.includes('trigger') ? 'active' : ''"
      >
        <AppIcon
          iconName="app-trigger"
          :class="route.path.includes('trigger') ? 'color-primary' : 'color-secondary'"
          style="font-size: 20px"
        ></AppIcon>
      </el-button>
    </el-tooltip>
  </div>
</template>
<script setup lang="ts">
import { hasPermission } from '@/utils/permission'
import { PermissionConst, RoleConst } from '@/utils/permission/data'
import { useRoute, useRouter } from 'vue-router'
const route = useRoute()
const router = useRouter()

withDefaults(defineProps<{ type?: 'workspace' | 'system' }>(), {
  type: 'workspace',
})
</script>
<style scoped lang="scss">
.top-about {
  .el-button.is-text {
    max-height: 32px;
    padding: 6px !important;
  }
  .el-button + .el-button {
    margin-left: 8px !important;
  }
  .active {
    background-color: var(--accent-soft);
    box-shadow: none;
    &:hover {
      background: var(--accent-soft);
    }
  }
}
</style>
