<template>
  <div class="p-16-24 settings-page">
    <div class="flex-between mb-16">
      <div>
        <h2>{{ $t('views.opportunity.settings') }}</h2>
        <p class="color-secondary mt-4">{{ $t('views.opportunity.settingsIntro') }}</p>
      </div>
      <div>
        <el-button @click="$router.push('/opportunity/cases')">{{ $t('views.opportunity.caseManagement') }}</el-button>
        <el-button @click="$router.push('/opportunity')">{{ $t('views.opportunity.backToAnalysis') }}</el-button>
      </div>
    </div>

    <el-tabs v-model="activeTab" type="border-card" class="settings-tabs">
      <el-tab-pane :label="$t('views.opportunity.engineTab')" name="engine">
        <p class="tab-intro">{{ $t('views.opportunity.engineHint') }}</p>
        <el-descriptions :column="1" border class="bind-status mb-16" size="small">
          <el-descriptions-item :label="$t('views.opportunity.llm')">
            <span :class="setting.llm_model_id ? 'bind-ok' : 'bind-miss'">{{ boundModelText }}</span>
          </el-descriptions-item>
          <el-descriptions-item :label="$t('views.opportunity.knowledge')">
            <span :class="setting.product_knowledge_id ? 'bind-ok' : 'bind-miss'">{{ boundKnowledgeText }}</span>
          </el-descriptions-item>
          <el-descriptions-item :label="$t('views.opportunity.caseKnowledge')">
            <span :class="setting.case_knowledge_id ? 'bind-ok' : 'color-secondary'">{{ boundCaseKnowledgeText }}</span>
          </el-descriptions-item>
        </el-descriptions>
        <el-alert
          v-if="!modelLoading && !hasAvailableModel"
          class="mb-16"
          type="warning"
          show-icon
          :closable="false"
          :title="$t('views.opportunity.modelEmptyHint')"
        />
        <el-alert
          v-else-if="orphanModel"
          class="mb-16"
          type="warning"
          show-icon
          :closable="false"
          :title="$t('views.opportunity.orphanModelHint')"
        />
        <el-alert
          v-if="!knowledgeLoading && knowledgeList.length === 0"
          class="mb-16"
          type="warning"
          show-icon
          :closable="false"
          :title="$t('views.opportunity.knowledgeEmptyHint')"
        />
        <el-form label-position="top" :model="setting" class="settings-form" @submit.prevent>
          <el-form-item :label="$t('views.opportunity.llm')" required>
            <ModelSelect
              v-model="setting.llm_model_id"
              class="field-control"
              :placeholder="$t('views.opportunity.modelPlaceholder')"
              :options="modelOptions"
              :model-type="'LLM'"
              show-footer
              @submitModel="loadModels"
            />
          </el-form-item>
          <el-form-item :label="$t('views.opportunity.knowledge')" required>
            <el-select
              v-model="setting.product_knowledge_id"
              filterable
              clearable
              class="field-control"
              :placeholder="$t('views.opportunity.knowledgePlaceholder')"
            >
              <el-option
                v-for="item in knowledgeList"
                :key="item.id"
                :label="item.name"
                :value="item.id"
              />
            </el-select>
          </el-form-item>
          <el-form-item :label="$t('views.opportunity.caseKnowledge')">
            <el-select
              v-model="setting.case_knowledge_id"
              filterable
              clearable
              class="field-control"
              :placeholder="$t('views.opportunity.caseKnowledgePlaceholder')"
            >
              <el-option
                v-for="item in knowledgeList"
                :key="item.id"
                :label="item.name"
                :value="item.id"
              />
            </el-select>
          </el-form-item>
          <el-row :gutter="16">
            <el-col :xs="24" :sm="8">
              <el-form-item :label="$t('views.opportunity.searchMode')">
                <el-select v-model="setting.search_mode" class="field-control">
                  <el-option :label="$t('views.opportunity.searchModeBlend')" value="blend" />
                  <el-option :label="$t('views.opportunity.searchModeEmbedding')" value="embedding" />
                  <el-option :label="$t('views.opportunity.searchModeKeywords')" value="keywords" />
                </el-select>
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="8">
              <el-form-item label="Top N">
                <el-input-number v-model="setting.top_n" class="field-number" :min="1" :max="100" controls-position="right" />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="8">
              <el-form-item :label="$t('views.opportunity.similarity')">
                <el-input-number
                  v-model="setting.similarity"
                  class="field-number"
                  :min="0"
                  :max="1"
                  :step="0.05"
                  :precision="2"
                  controls-position="right"
                />
              </el-form-item>
            </el-col>
          </el-row>
          <div class="form-actions">
            <el-button type="primary" :loading="saving" @click="saveSetting">{{ $t('views.opportunity.saveSetting') }}</el-button>
            <el-button @click="$router.push('/model')">{{ $t('views.opportunity.goCreateModel') }}</el-button>
            <el-button @click="$router.push('/knowledge')">{{ $t('views.opportunity.goKnowledge') }}</el-button>
          </div>
        </el-form>
      </el-tab-pane>

      <el-tab-pane :label="$t('views.opportunity.departmentTab')" name="department">
        <p class="tab-intro">{{ $t('views.opportunity.departmentHint') }}</p>
        <el-form label-position="top" :model="departmentForm" class="settings-form" @submit.prevent>
          <el-row :gutter="16">
            <el-col :xs="24" :sm="12">
              <el-form-item :label="$t('views.opportunity.code')" required>
                <el-input v-model="departmentForm.code" class="field-control" />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="12">
              <el-form-item :label="$t('views.opportunity.name')" required>
                <el-input v-model="departmentForm.name" class="field-control" />
              </el-form-item>
            </el-col>
          </el-row>
          <div class="form-actions">
            <el-button type="primary" @click="saveDepartment">{{ $t('views.opportunity.saveDepartment') }}</el-button>
          </div>
        </el-form>
        <el-table :data="departments" size="small" class="mt-16">
          <el-table-column prop="code" :label="$t('views.opportunity.code')" min-width="140" />
          <el-table-column prop="name" :label="$t('views.opportunity.name')" min-width="180" />
          <el-table-column prop="status" :label="$t('views.opportunity.status')" width="120" />
          <template #empty>{{ $t('views.opportunity.emptyDepartment') }}</template>
        </el-table>
      </el-tab-pane>

      <el-tab-pane :label="$t('views.opportunity.productTab')" name="product">
        <p class="tab-intro">{{ $t('views.opportunity.productHint') }}</p>
        <el-form label-position="top" :model="productForm" class="settings-form" @submit.prevent>
          <el-row :gutter="16">
            <el-col :xs="24" :sm="12">
              <el-form-item :label="$t('views.opportunity.code')" required>
                <el-input v-model="productForm.code" class="field-control" />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="12">
              <el-form-item :label="$t('views.opportunity.name')" required>
                <el-input v-model="productForm.name" class="field-control" />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="12">
              <el-form-item :label="$t('views.opportunity.alias')">
                <el-input v-model="aliasText" class="field-control" :placeholder="$t('views.opportunity.aliasPlaceholder')" />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="12">
              <el-form-item :label="$t('views.opportunity.ownerDepartment')">
                <el-select v-model="productForm.owner_department_id" clearable filterable class="field-control">
                  <el-option v-for="item in departments" :key="item.id" :label="item.name" :value="item.id" />
                </el-select>
              </el-form-item>
            </el-col>
          </el-row>
          <div class="form-actions">
            <el-button type="primary" @click="saveProduct">{{ $t('views.opportunity.saveProduct') }}</el-button>
          </div>
        </el-form>
        <el-table :data="products" size="small" class="mt-16">
          <el-table-column prop="code" :label="$t('views.opportunity.code')" min-width="140" />
          <el-table-column prop="name" :label="$t('views.opportunity.name')" min-width="180" />
          <el-table-column :label="$t('views.opportunity.ownerDepartment')" min-width="160">
            <template #default="{ row }">
              {{ row.department?.owner_department_name || $t('views.opportunity.departmentUnresolved') }}
            </template>
          </el-table-column>
          <template #empty>{{ $t('views.opportunity.emptyProduct') }}</template>
        </el-table>
      </el-tab-pane>

      <el-tab-pane :label="$t('views.opportunity.embedTab')" name="embed">
        <p class="tab-intro">{{ $t('views.opportunity.embedHint') }}</p>
        <el-form label-position="top" :model="embedForm" class="settings-form" @submit.prevent>
          <el-row :gutter="16">
            <el-col :xs="24" :sm="12">
              <el-form-item :label="$t('views.opportunity.embedName')">
                <el-input v-model="embedForm.name" class="field-control" :placeholder="$t('views.opportunity.embedNamePlaceholder')" />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="12">
              <el-form-item :label="$t('views.opportunity.tokenTtl')">
                <el-input-number
                  v-model="embedForm.token_ttl_seconds"
                  class="field-number"
                  :min="60"
                  :max="900"
                  :step="60"
                  controls-position="right"
                />
                <span class="ml-8">{{ $t('views.opportunity.seconds') }}</span>
              </el-form-item>
            </el-col>
            <el-col :span="24">
              <el-form-item :label="$t('views.opportunity.allowedOrigins')">
                <el-input
                  v-model="embedOrigins"
                  type="textarea"
                  :rows="3"
                  class="field-control field-wide"
                  :placeholder="$t('views.opportunity.allowedOriginsPlaceholder')"
                />
              </el-form-item>
            </el-col>
          </el-row>
          <div class="form-actions">
            <el-button type="primary" :loading="embedSaving" @click="createEmbedClient">
              {{ $t('views.opportunity.createEmbed') }}
            </el-button>
          </div>
        </el-form>
        <el-table :data="embedClients" size="small" class="mt-16">
          <el-table-column prop="name" :label="$t('views.opportunity.embedName')" min-width="130" />
          <el-table-column prop="client_id" label="Client ID" min-width="210" />
          <el-table-column :label="$t('views.opportunity.allowedOrigins')" min-width="260">
            <template #default="{ row }">{{ row.allowed_origins.join('，') }}</template>
          </el-table-column>
          <el-table-column prop="token_ttl_seconds" :label="$t('views.opportunity.tokenTtl')" width="120" />
          <el-table-column prop="active_session_count" :label="$t('views.opportunity.activeSessions')" width="100" />
          <el-table-column :label="$t('views.opportunity.status')" width="80">
            <template #default="{ row }">
              <el-tag :type="row.is_active ? 'success' : 'info'">
                {{ row.is_active ? $t('common.status.enable') : $t('common.status.disable') }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column :label="$t('common.operation')" width="180" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" :disabled="!row.is_active" @click="rotateSecret(row)">
                {{ $t('views.opportunity.rotateSecret') }}
              </el-button>
              <el-button link type="danger" :disabled="!row.is_active" @click="disableClient(row)">
                {{ $t('views.opportunity.disableClient') }}
              </el-button>
            </template>
          </el-table-column>
          <template #empty>{{ $t('views.opportunity.emptyEmbed') }}</template>
        </el-table>
      </el-tab-pane>
    </el-tabs>

    <el-dialog v-model="secretVisible" :title="$t('views.opportunity.saveCredential')" width="620px" :close-on-click-modal="false">
      <el-alert type="warning" :closable="false" show-icon>
        {{ $t('views.opportunity.secretOnceHint') }}
      </el-alert>
      <el-form class="mt-16" label-position="top">
        <el-form-item label="Client ID"><el-input :model-value="issuedCredential.client_id" readonly /></el-form-item>
        <el-form-item label="Client Secret">
          <el-input :model-value="issuedCredential.client_secret" readonly type="textarea" :rows="3" />
        </el-form-item>
        <el-form-item :label="$t('views.opportunity.embedPath')">
          <el-input :model-value="issuedCredential.embed_path" readonly />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button type="primary" @click="secretVisible = false">{{ $t('views.opportunity.secretSaved') }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import { groupBy } from 'lodash'
import ModelSelect from '@/components/model-select/index.vue'
import { loadSharedApi } from '@/utils/dynamics-api/shared-api'
import opportunityApi from '@/api/opportunity'
import useStore from '@/stores'
import type {
  DepartmentProfile,
  OpportunityEmbedClient,
  OpportunitySetting,
  ProductProfile,
} from '@/api/type/opportunity'

const TAB_NAMES = ['engine', 'department', 'product', 'embed'] as const
type TabName = (typeof TAB_NAMES)[number]

const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const { user } = useStore()
const saving = ref(false)
const modelLoading = ref(false)
const knowledgeLoading = ref(false)
const setting = reactive<OpportunitySetting>({
  search_mode: 'blend',
  top_n: 20,
  similarity: 0.3,
  max_candidates: 5,
  llm_model_id: '',
  product_knowledge_id: '',
  case_knowledge_id: '',
})
const departments = ref<DepartmentProfile[]>([])
const products = ref<ProductProfile[]>([])
const departmentForm = reactive({ code: '', name: '' })
const productForm = reactive({ code: '', name: '', owner_department_id: '' })
const aliasText = ref('')
const embedClients = ref<OpportunityEmbedClient[]>([])
const embedSaving = ref(false)
const embedOrigins = ref('')
const embedForm = reactive({ name: '', token_ttl_seconds: 300 })
const secretVisible = ref(false)
const issuedCredential = reactive({ client_id: '', client_secret: '', embed_path: '' })
const modelOptions = ref<Record<string, any[]>>({})
const knowledgeList = ref<Array<{ id: string; name: string }>>([])

const activeTab = computed({
  get: () => {
    const tab = String(route.query.tab || 'engine')
    return (TAB_NAMES as readonly string[]).includes(tab) ? (tab as TabName) : 'engine'
  },
  set: (tab: string) => {
    router.replace({ query: { ...route.query, tab } })
  },
})

const flattenedModels = computed(() => Object.values(modelOptions.value).flat())
const hasAvailableModel = computed(() => flattenedModels.value.some((item) => item.status === 'SUCCESS'))
const orphanModel = computed(() => {
  const id = setting.llm_model_id
  return Boolean(id) && flattenedModels.value.length > 0 && !flattenedModels.value.some((item) => item.id === id)
})
const knowledgeName = (id?: string | null) => knowledgeList.value.find((item) => item.id === id)?.name || ''
const boundModelText = computed(() => {
  const id = setting.llm_model_id
  if (!id) return t('views.opportunity.bindStatusUnbound')
  const found = flattenedModels.value.find((item) => item.id === id)
  if (found?.name) return t('views.opportunity.bindStatusBound', { name: found.name })
  return t('views.opportunity.bindStatusUnknown')
})
const boundKnowledgeText = computed(() => {
  const id = setting.product_knowledge_id
  if (!id) return t('views.opportunity.bindStatusUnbound')
  const name = knowledgeName(id)
  return name ? t('views.opportunity.bindStatusBound', { name }) : t('views.opportunity.bindStatusUnknown')
})
const boundCaseKnowledgeText = computed(() => {
  const id = setting.case_knowledge_id
  if (!id) return t('views.opportunity.bindStatusOptional')
  const name = knowledgeName(id)
  return name ? t('views.opportunity.bindStatusBound', { name }) : t('views.opportunity.bindStatusUnknown')
})

const loadModels = () => {
  modelLoading.value = true
  loadSharedApi({ type: 'model' })
    .getSelectModelList({ model_type: 'LLM' })
    .then((res: any) => {
      modelOptions.value = groupBy(res?.data || [], 'provider')
    })
    .finally(() => {
      modelLoading.value = false
    })
}

const loadKnowledge = () => {
  const mapList = (data: any) => {
    if (Array.isArray(data)) return data
    if (Array.isArray(data?.records)) return data.records
    return []
  }
  knowledgeLoading.value = true
  loadSharedApi({ type: 'knowledge' })
    .getKnowledgeList({ folder_id: user.getWorkspaceId() })
    .then((res: any) => {
      const list = mapList(res.data)
      if (list.length > 0) {
        knowledgeList.value = list
        return
      }
      return loadSharedApi({ type: 'knowledge' })
        .getKnowledgeListPage({ current_page: 1, page_size: 100 }, { folder_id: user.getWorkspaceId() })
        .then((pageRes: any) => {
          knowledgeList.value = mapList(pageRes.data)
        })
    })
    .finally(() => {
      knowledgeLoading.value = false
    })
}

const loadAll = () => {
  opportunityApi.getSetting().then((res) => {
    Object.assign(setting, res.data || {})
    setting.llm_model_id = setting.llm_model_id || ''
    setting.product_knowledge_id = setting.product_knowledge_id || ''
    setting.case_knowledge_id = setting.case_knowledge_id || ''
  })
  opportunityApi.listDepartments().then((res) => (departments.value = res.data || []))
  opportunityApi.listProducts().then((res) => (products.value = res.data || []))
  opportunityApi.listEmbedClients().then((res) => (embedClients.value = res.data || []))
  loadModels()
  loadKnowledge()
}

const saveSetting = () => {
  if (!setting.llm_model_id) {
    ElMessage.warning(t('views.opportunity.selectModelFirst'))
    return
  }
  if (!setting.product_knowledge_id) {
    ElMessage.warning(t('views.opportunity.selectKnowledgeFirst'))
    return
  }
  opportunityApi.updateSetting({ ...setting }, saving).then(() => {
    ElMessage.success(t('views.opportunity.engineSaved'))
    loadAll()
  })
}
const saveDepartment = () => {
  if (!departmentForm.code.trim() || !departmentForm.name.trim()) {
    ElMessage.warning(t('views.opportunity.departmentRequired'))
    return
  }
  opportunityApi.createDepartment({ ...departmentForm, status: 'ACTIVE' }).then(() => {
    departmentForm.code = ''
    departmentForm.name = ''
    loadAll()
  })
}
const saveProduct = () => {
  if (!productForm.code.trim() || !productForm.name.trim()) {
    ElMessage.warning(t('views.opportunity.productRequired'))
    return
  }
  opportunityApi
    .createProduct({
      ...productForm,
      aliases: aliasText.value ? aliasText.value.split(',').map((item) => item.trim()).filter(Boolean) : [],
      status: 'ACTIVE',
    })
    .then(() => {
      productForm.code = ''
      productForm.name = ''
      productForm.owner_department_id = ''
      aliasText.value = ''
      loadAll()
    })
}

const showCredential = (data: OpportunityEmbedClient & { embed_path?: string }) => {
  issuedCredential.client_id = data.client_id
  issuedCredential.client_secret = data.client_secret || ''
  const prefix = window.MaxKB?.prefix ? window.MaxKB.prefix : '/admin'
  issuedCredential.embed_path = data.embed_path || `${prefix}/opportunity/embed/${data.client_id}`
  secretVisible.value = true
}

const createEmbedClient = () => {
  const origins = embedOrigins.value.split(/\n|,/).map((item) => item.trim()).filter(Boolean)
  if (!embedForm.name.trim() || origins.length === 0) {
    ElMessage.warning(t('views.opportunity.embedRequired'))
    return
  }
  opportunityApi.createEmbedClient({
    name: embedForm.name.trim(),
    token_ttl_seconds: embedForm.token_ttl_seconds,
    allowed_origins: origins,
    allowed_scopes: ['analysis:create', 'analysis:read', 'analysis:decision', 'report:export'],
    is_active: true,
  }, embedSaving).then((res) => {
    showCredential(res.data)
    embedForm.name = ''
    embedOrigins.value = ''
    loadAll()
  })
}

const rotateSecret = (client: OpportunityEmbedClient) => {
  ElMessageBox.confirm('轮换后旧密钥及该客户端现有短期会话会立即失效，是否继续？', '轮换密钥', {
    type: 'warning', confirmButtonText: '继续轮换', cancelButtonText: '取消',
  }).then(() => opportunityApi.rotateEmbedClientSecret(client.id)).then((res) => {
    showCredential(res.data)
    loadAll()
  }).catch(() => undefined)
}

const disableClient = (client: OpportunityEmbedClient) => {
  ElMessageBox.confirm('停用后该客户端现有短期会话会立即失效，是否继续？', '停用接入方', {
    type: 'warning', confirmButtonText: '确认停用', cancelButtonText: '取消',
  }).then(() => opportunityApi.disableEmbedClient(client.id)).then(loadAll).catch(() => undefined)
}

watch(
  () => route.query.tab,
  (tab) => {
    if (tab && !(TAB_NAMES as readonly string[]).includes(String(tab))) {
      router.replace({ query: { ...route.query, tab: 'engine' } })
    }
  },
)

onMounted(loadAll)
</script>

<style scoped>
.settings-page .color-secondary {
  color: var(--el-text-color-secondary);
}
.tab-intro {
  color: var(--el-text-color-secondary);
  margin: 0 0 16px;
  line-height: 1.6;
}
.bind-status {
  max-width: 880px;
}
.bind-ok {
  color: var(--el-color-success);
}
.bind-miss {
  color: var(--el-color-danger);
}
.settings-form {
  max-width: 880px;
}
.field-control {
  width: 100%;
  max-width: 560px;
}
.field-wide {
  max-width: 880px;
}
.field-number {
  width: 100%;
  max-width: 220px;
}
.form-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding-top: 8px;
  margin-top: 4px;
  border-top: 1px solid var(--el-border-color-lighter);
}
.settings-tabs :deep(.el-tabs__content) {
  padding: 20px 24px 24px;
}
.settings-form :deep(.el-form-item) {
  display: flex;
  flex-direction: column;
  align-items: stretch;
}
.settings-form :deep(.el-form-item__label) {
  width: auto !important;
  justify-content: flex-start;
}
.settings-form :deep(.el-form-item__content) {
  margin-left: 0 !important;
  width: 100% !important;
  max-width: 100%;
}
.settings-form :deep(.el-input),
.settings-form :deep(.el-select),
.settings-form :deep(.el-textarea),
.settings-form :deep(.w-full) {
  width: 100%;
}
.mb-16 {
  margin-bottom: 16px;
}
.mt-16 {
  margin-top: 16px;
}
.ml-8 {
  margin-left: 8px;
}
</style>
