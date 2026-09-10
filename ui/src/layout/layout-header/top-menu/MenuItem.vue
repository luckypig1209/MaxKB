<template>
  <div
    class="menu-item-container h-full border-r-6"
    :class="isActive ? 'active' : ''"
    @click="router.push({ name: menu.name })"
  >
    <div class="title flex align-center">
      <AppIcon
        :iconName="isActive ? menu.meta?.iconActive || menu.meta?.icon : menu?.meta?.icon"
        style="font-size: 16px"
        class="mr-4"
      />
      <span class="title-text"> {{ $t(menu.meta?.title as string) }}</span>
    </div>
  </div>
</template>
<script setup lang="ts">
import { useRouter, useRoute, type RouteRecordRaw } from 'vue-router'
import { computed } from 'vue'

const router = useRouter()
const route = useRoute()

const props = defineProps<{
  menu: RouteRecordRaw
}>()

const isActive = computed(() => {
  const { name, path, meta } = route
  return (name == props.menu.name && path == props.menu.path) || meta?.activeMenu == props.menu.path
})
</script>
<style lang="scss" scoped>
.menu-item-container {
  margin-right: 8px;
  cursor: pointer;
  font-size: 14px;
  position: relative;
  padding: 6px 12px;
  border-radius: 9px;

  .icon {
    font-size: 15px;
    margin-right: 5px;
    margin-top: 2px;
  }

  &:hover {
    background-color: rgba(var(--el-text-color-primary-rgb), 0.1);
  }
  &.active {
    background-color: var(--accent-soft);
    box-shadow: none;

    .title {
      color: var(--accent-ink) !important;
    }
  }
  .title-text {
    @media (max-width: 1200px) {
      display: none;
    }
  }
}
</style>
