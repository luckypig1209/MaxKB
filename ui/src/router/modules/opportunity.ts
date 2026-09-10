import { RoleConst } from '@/utils/permission/data'

const OpportunityRouter = {
  path: '/opportunity',
  name: 'opportunity',
  meta: {
    title: 'views.opportunity.title',
    menu: true,
    permission: [RoleConst.USER.getWorkspaceRole, RoleConst.WORKSPACE_MANAGE.getWorkspaceRole],
    icon: 'app-workspace',
    iconActive: 'app-workspace-active',
    group: 'workspace',
    order: 4,
  },
  redirect: '/opportunity',
  component: () => import('@/layout/layout-template/SimpleLayout.vue'),
  children: [
    {
      path: '/opportunity',
      name: 'opportunity-index',
      meta: { title: '商机分析', activeMenu: '/opportunity', sameRoute: 'opportunity' },
      component: () => import('@/views/opportunity/index.vue'),
    },
    {
      path: '/opportunity/settings',
      name: 'opportunity-settings',
      meta: {
        title: '商机分析设置',
        activeMenu: '/opportunity',
        permission: [RoleConst.WORKSPACE_MANAGE.getWorkspaceRole],
      },
      component: () => import('@/views/opportunity/settings/index.vue'),
      hidden: true,
    },
    {
      path: '/opportunity/cases',
      name: 'opportunity-cases',
      meta: {
        title: '案例管理',
        activeMenu: '/opportunity',
        permission: [RoleConst.WORKSPACE_MANAGE.getWorkspaceRole],
      },
      component: () => import('@/views/opportunity/cases/index.vue'),
      hidden: true,
    },
    {
      path: '/opportunity/records',
      name: 'opportunity-records',
      meta: { title: '我的商机', activeMenu: '/opportunity' },
      component: () => import('@/views/opportunity/records/index.vue'),
      hidden: true,
    },
    {
      path: '/opportunity/:id',
      name: 'opportunity-detail',
      meta: { title: '商机分析结果', activeMenu: '/opportunity' },
      component: () => import('@/views/opportunity/index.vue'),
      hidden: true,
    },
  ],
}

export default OpportunityRouter
