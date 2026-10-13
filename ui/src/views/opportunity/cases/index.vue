<template>
  <div class="hx-pmain case-page hx-tool-page">
    <HxOverview
      :title="t('views.opportunity.cases.title')"
      :context="t('views.opportunity.cases.subtitle')"
      :metrics="overviewMetrics"
    >
      <template #actions>
        <el-button @click="$router.push('/opportunity')">{{ t('views.opportunity.cases.backToAnalysis') }}</el-button>
        <el-button type="primary" @click="openCreate">{{ t('views.opportunity.cases.register') }}</el-button>
      </template>
    </HxOverview>

    <div class="hx-panel">
      <el-form class="case-filter" :inline="true" :model="filters">
        <el-form-item class="filter-item" :label="t('views.opportunity.cases.caseName')">
          <el-input v-model="filters.name" clearable :placeholder="t('views.opportunity.cases.name')" />
        </el-form-item>
        <el-form-item class="filter-item" :label="t('views.opportunity.cases.industry')">
          <el-input v-model="filters.industry" clearable :placeholder="t('views.opportunity.cases.industry')" />
        </el-form-item>
        <el-form-item class="filter-item" :label="t('views.opportunity.cases.statusLabel')">
          <el-select v-model="filters.status" clearable>
            <el-option v-for="item in statusOptions" :key="item" :label="statusText(item)" :value="item" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button @click="loadCases">{{ t('views.opportunity.cases.search') }}</el-button>
          <el-button @click="resetFilters">{{ t('views.opportunity.cases.reset') }}</el-button>
        </el-form-item>
      </el-form>

      <el-table v-loading="loading" :data="cases" row-key="id">
        <el-table-column prop="code" :label="t('views.opportunity.cases.caseCode')" min-width="200" />
        <el-table-column prop="name" :label="t('views.opportunity.cases.caseName')" min-width="220" />
        <el-table-column prop="industry" :label="t('views.opportunity.cases.industry')" width="130" />
        <el-table-column :label="t('views.opportunity.cases.linkedProducts')" min-width="170">
          <template #default="{ row }">
            {{ row.products.map((item: CaseProductReference) => item.name).join('、') || '-' }}
          </template>
        </el-table-column>
        <el-table-column :label="t('views.opportunity.cases.reviewPublish')" width="190">
          <template #default="{ row }">
            <el-tag :type="statusTag(row.status)">{{ statusText(row.status) }}</el-tag>
            <el-tag class="ml-4" :type="row.desensitization_status === 'PASSED' ? 'success' : 'warning'">
              {{ desensitizationText(row.desensitization_status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column :label="t('views.opportunity.cases.materials')" width="90">
          <template #default="{ row }">{{ row.documents.length }}</template>
        </el-table-column>
        <el-table-column :label="t('views.opportunity.cases.updatedAt')" width="170">
          <template #default="{ row }">{{ formatTime(row.update_time) }}</template>
        </el-table-column>
        <el-table-column :label="t('views.opportunity.cases.actions')" fixed="right" width="330">
          <template #default="{ row }">
            <el-button link type="primary" @click="openDetail(row)">{{ t('views.opportunity.cases.view') }}</el-button>
            <el-button v-if="editable(row.status)" link type="primary" @click="openEdit(row)">{{ t('views.opportunity.cases.edit') }}</el-button>
            <el-button v-if="bindable(row.status)" link type="primary" @click="openBinding(row)">{{ t('views.opportunity.cases.bind') }}</el-button>
            <el-button
              v-for="action in availableActions(row.status)"
              :key="action"
              link
              :type="action === 'REJECT' || action === 'OFFLINE' ? 'danger' : 'primary'"
              @click="changeStatus(row, action)"
            >
              {{ actionText(action) }}
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-drawer
      v-model="registrationVisible"
      class="registration-drawer"
      :title="t('views.opportunity.cases.registerTitle')"
      direction="rtl"
      size="min(900px, 92vw)"
    >
      <p class="registration-hint">{{ t('views.opportunity.cases.documentHint') }}</p>
      <el-steps :active="registrationStep" align-center class="registration-steps">
        <el-step :title="t('views.opportunity.cases.stepDocument')" />
        <el-step :title="t('views.opportunity.cases.stepBasics')" />
        <el-step :title="t('views.opportunity.cases.stepProducts')" />
        <el-step :title="t('views.opportunity.cases.stepScale')" />
        <el-step :title="t('views.opportunity.cases.stepReview')" />
      </el-steps>
      <el-form ref="registrationFormRef" :model="form" :rules="registrationRules" label-width="120px">
        <section v-if="registrationStep === 0" class="registration-step">
          <el-form-item :label="t('views.opportunity.cases.documentLabel')" prop="document_id">
            <el-select
              v-model="form.document_id"
              filterable
              clearable
              style="width: 100%"
              :placeholder="t('views.opportunity.cases.documentPlaceholder')"
            >
              <el-option
                v-for="item in availableDocuments"
                :key="item.id"
                :label="item.name"
                :value="item.id"
              >
                <span>{{ item.name }}</span>
                <span class="document-status">
                  <el-tag size="small" type="success">{{ item.parsed ? t('views.opportunity.cases.parsed') : t('views.opportunity.cases.parsing') }}</el-tag>
                  <el-tag size="small" :type="item.is_bound ? 'info' : 'success'">{{ item.is_bound ? t('views.opportunity.cases.bound') : t('views.opportunity.cases.available') }}</el-tag>
                </span>
              </el-option>
            </el-select>
          </el-form-item>
          <el-alert v-if="!availableDocuments.length" type="warning" :closable="false" :title="t('views.opportunity.cases.noDocuments')" />
          <div class="document-actions">
            <el-button link type="primary" @click="$router.push('/knowledge')">{{ t('views.opportunity.cases.openKnowledge') }}</el-button>
          </div>
          <el-row :gutter="16">
            <el-col :span="12">
              <el-form-item :label="t('views.opportunity.cases.documentVersion')">
                <el-input v-model="form.document_version" />
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item :label="t('views.opportunity.cases.allowDownload')">
                <el-switch v-model="form.allow_download" />
              </el-form-item>
            </el-col>
          </el-row>
        </section>

        <section v-else-if="registrationStep === 1" class="registration-step">
          <el-row :gutter="16">
            <el-col :span="12"><el-form-item :label="t('views.opportunity.cases.code')" prop="code"><el-input v-model="form.code" /></el-form-item></el-col>
            <el-col :span="12"><el-form-item :label="t('views.opportunity.cases.name')" prop="name"><el-input v-model="form.name" /></el-form-item></el-col>
            <el-col :span="12"><el-form-item :label="t('views.opportunity.cases.industry')"><el-input v-model="form.industry" /></el-form-item></el-col>
            <el-col :span="12"><el-form-item :label="t('views.opportunity.cases.customerType')"><el-input v-model="form.customer_type" /></el-form-item></el-col>
          </el-row>
          <el-form-item :label="t('views.opportunity.cases.scenario')"><el-input v-model="form.scenario" type="textarea" :rows="3" /></el-form-item>
          <el-form-item :label="t('views.opportunity.cases.painPoints')"><el-input v-model="painPointText" type="textarea" :rows="3" :placeholder="t('views.opportunity.cases.linePlaceholder')" /></el-form-item>
        </section>

        <section v-else-if="registrationStep === 2" class="registration-step">
          <el-form-item :label="t('views.opportunity.cases.products')" prop="product_codes">
            <el-select v-model="form.product_codes" multiple style="width: 100%" :placeholder="t('views.opportunity.cases.productsPlaceholder')">
              <el-option v-for="item in products" :key="item.code" :label="item.name" :value="item.code" />
            </el-select>
          </el-form-item>
          <el-row :gutter="16">
            <el-col :span="12"><el-form-item :label="t('views.opportunity.cases.primaryProduct')"><el-select v-model="form.primary_product_code" clearable style="width: 100%"><el-option v-for="code in form.product_codes" :key="code" :label="products.find((item) => item.code === code)?.name || code" :value="code" /></el-select></el-form-item></el-col>
            <el-col :span="12"><el-form-item :label="t('views.opportunity.cases.ownerDepartment')"><el-select v-model="form.owner_department_id" clearable style="width: 100%"><el-option v-for="item in departments" :key="item.id" :label="item.name" :value="item.id" /></el-select></el-form-item></el-col>
            <el-col :span="12"><el-form-item :label="t('views.opportunity.cases.sensitivity')"><el-select v-model="form.sensitivity_level" style="width: 100%"><el-option label="PUBLIC" value="PUBLIC" /><el-option label="INTERNAL" value="INTERNAL" /><el-option label="SENSITIVE" value="SENSITIVE" /></el-select></el-form-item></el-col>
            <el-col :span="12"><el-form-item :label="t('views.opportunity.cases.accessScope')"><el-select v-model="form.access_scope" style="width: 100%"><el-option label="WORKSPACE" value="WORKSPACE" /><el-option label="DEPARTMENT" value="DEPARTMENT" /><el-option label="PRIVATE" value="PRIVATE" /></el-select></el-form-item></el-col>
          </el-row>
        </section>

        <section v-else-if="registrationStep === 3" class="registration-step">
          <el-form-item :label="t('views.opportunity.cases.projectScale')">
            <div class="scale-editor">
              <div v-for="(row, index) in projectScaleRows" :key="row.id" class="scale-row">
                <el-input v-model="row.metric" :placeholder="t('views.opportunity.cases.scaleMetric')" />
                <el-input v-model="row.value" :placeholder="t('views.opportunity.cases.scaleValue')" />
                <el-input v-model="row.unit" :placeholder="t('views.opportunity.cases.scaleUnit')" />
                <el-button link type="danger" :aria-label="t('views.opportunity.cases.removeScaleRow')" @click="removeScaleRow(index)">×</el-button>
              </div>
              <el-button link type="primary" @click="addScaleRow">+ {{ t('views.opportunity.cases.addScaleRow') }}</el-button>
            </div>
          </el-form-item>
          <el-form-item :label="t('views.opportunity.cases.implementationConditions')"><el-input v-model="conditionText" type="textarea" :rows="2" :placeholder="t('views.opportunity.cases.linePlaceholder')" /></el-form-item>
          <el-form-item :label="t('views.opportunity.cases.implementationProcess')"><el-input v-model="form.implementation_process" type="textarea" :rows="2" /></el-form-item>
          <el-form-item :label="t('views.opportunity.cases.outcomes')"><el-input v-model="outcomeText" type="textarea" :rows="2" :placeholder="t('views.opportunity.cases.linePlaceholder')" /></el-form-item>
          <el-form-item :label="t('views.opportunity.cases.applicabilityBoundary')"><el-input v-model="form.applicability_boundary" type="textarea" :rows="2" /></el-form-item>
        </section>

        <section v-else class="registration-step review-step">
          <p>{{ t('views.opportunity.cases.reviewSummary') }}</p>
          <el-descriptions :column="1" border>
            <el-descriptions-item :label="t('views.opportunity.cases.documentLabel')">{{ selectedDocumentName }}</el-descriptions-item>
            <el-descriptions-item :label="t('views.opportunity.cases.name')">{{ form.name || t('views.opportunity.cases.emptyValue') }}</el-descriptions-item>
            <el-descriptions-item :label="t('views.opportunity.cases.products')">{{ selectedProductNames || t('views.opportunity.cases.emptyValue') }}</el-descriptions-item>
            <el-descriptions-item :label="t('views.opportunity.cases.projectScale')">{{ scaleSummary || t('views.opportunity.cases.emptyValue') }}</el-descriptions-item>
          </el-descriptions>
        </section>
      </el-form>
      <template #footer>
        <el-button @click="registrationVisible = false">{{ t('views.opportunity.cases.cancel') }}</el-button>
        <el-button v-if="registrationStep > 0" @click="registrationStep -= 1">{{ t('views.opportunity.cases.previous') }}</el-button>
        <el-button v-if="registrationStep < 4" type="primary" @click="nextRegistrationStep">{{ t('views.opportunity.cases.next') }}</el-button>
        <el-button v-else type="primary" :loading="saving" @click="submitRegistration">{{ t('views.opportunity.cases.saveDraft') }}</el-button>
      </template>
    </el-drawer>

      <el-dialog v-model="editorVisible" :title="editingId ? t('views.opportunity.cases.editTitle') : t('views.opportunity.cases.registerTitle')" width="760px">
      <el-form ref="caseFormRef" :model="form" :rules="rules" label-width="110px">
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item :label="t('views.opportunity.cases.code')" prop="code"><el-input v-model="form.code" /></el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item :label="t('views.opportunity.cases.name')" prop="name"><el-input v-model="form.name" /></el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item :label="t('views.opportunity.cases.industry')"><el-input v-model="form.industry" /></el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item :label="t('views.opportunity.cases.customerType')"><el-input v-model="form.customer_type" /></el-form-item>
          </el-col>
        </el-row>
        <el-form-item :label="t('views.opportunity.cases.scenario')"><el-input v-model="form.scenario" type="textarea" :rows="2" /></el-form-item>
        <el-form-item :label="t('views.opportunity.cases.painPoints')">
          <el-input v-model="painPointText" type="textarea" :rows="2" :placeholder="t('views.opportunity.cases.linePlaceholder')" />
        </el-form-item>
        <el-form-item :label="t('views.opportunity.cases.projectScale')">
          <div class="scale-editor">
            <div v-for="(row, index) in projectScaleRows" :key="row.id" class="scale-row">
              <el-input v-model="row.metric" :placeholder="t('views.opportunity.cases.scaleMetric')" />
              <el-input v-model="row.value" :placeholder="t('views.opportunity.cases.scaleValue')" />
              <el-input v-model="row.unit" :placeholder="t('views.opportunity.cases.scaleUnit')" />
              <el-button link type="danger" :aria-label="t('views.opportunity.cases.removeScaleRow')" @click="removeScaleRow(index)">×</el-button>
            </div>
            <el-button link type="primary" @click="addScaleRow">+ {{ t('views.opportunity.cases.addScaleRow') }}</el-button>
          </div>
        </el-form-item>
        <el-form-item :label="t('views.opportunity.cases.implementationConditions')">
          <el-input v-model="conditionText" type="textarea" :rows="2" :placeholder="t('views.opportunity.cases.linePlaceholder')" />
        </el-form-item>
        <el-form-item :label="t('views.opportunity.cases.implementationProcess')"><el-input v-model="form.implementation_process" type="textarea" :rows="2" /></el-form-item>
        <el-form-item :label="t('views.opportunity.cases.outcomes')">
          <el-input v-model="outcomeText" type="textarea" :rows="2" :placeholder="t('views.opportunity.cases.linePlaceholder')" />
        </el-form-item>
        <el-form-item :label="t('views.opportunity.cases.applicabilityBoundary')"><el-input v-model="form.applicability_boundary" type="textarea" :rows="2" /></el-form-item>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item :label="t('views.opportunity.cases.products')" prop="product_codes">
              <el-select v-model="form.product_codes" multiple style="width: 100%">
                <el-option v-for="item in products" :key="item.code" :label="item.name" :value="item.code" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item :label="t('views.opportunity.cases.primaryProduct')">
              <el-select v-model="form.primary_product_code" clearable style="width: 100%">
                <el-option
                  v-for="code in form.product_codes"
                  :key="code"
                  :label="products.find((item) => item.code === code)?.name || code"
                  :value="code"
                />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item :label="t('views.opportunity.cases.ownerDepartment')">
              <el-select v-model="form.owner_department_id" clearable style="width: 100%">
                <el-option v-for="item in departments" :key="item.id" :label="item.name" :value="item.id" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item :label="t('views.opportunity.cases.sensitivity')">
              <el-select v-model="form.sensitivity_level" style="width: 100%">
                <el-option v-for="value in ['PUBLIC', 'INTERNAL', 'SENSITIVE']" :key="value" :label="t(`views.opportunity.cases.sensitivityValues.${value}`)" :value="value" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item :label="t('views.opportunity.cases.accessScope')">
              <el-select v-model="form.access_scope" style="width: 100%">
                <el-option v-for="value in ['WORKSPACE', 'DEPARTMENT', 'PRIVATE']" :key="value" :label="t(`views.opportunity.cases.accessScopeValues.${value}`)" :value="value" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
      </el-form>
      <template #footer>
        <el-button @click="editorVisible = false">{{ t('views.opportunity.cases.cancel') }}</el-button>
        <el-button type="primary" :loading="saving" @click="saveCase">{{ t('views.opportunity.cases.saveDraft') }}</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="detailVisible" :title="t('views.opportunity.cases.detailTitle')" width="720px">
      <el-descriptions v-if="activeCase" :column="2" border>
        <el-descriptions-item :label="t('views.opportunity.cases.code')">{{ activeCase.code }}</el-descriptions-item>
        <el-descriptions-item :label="t('views.opportunity.cases.statusLabel')">{{ statusText(activeCase.status) }}</el-descriptions-item>
        <el-descriptions-item :label="t('views.opportunity.cases.industry')">{{ activeCase.industry || t('views.opportunity.cases.emptyValue') }}</el-descriptions-item>
        <el-descriptions-item :label="t('views.opportunity.cases.customerType')">{{ activeCase.customer_type || t('views.opportunity.cases.emptyValue') }}</el-descriptions-item>
        <el-descriptions-item :label="t('views.opportunity.cases.products')" :span="2">
          {{ activeCase.products.map((item) => item.name).join(t('views.opportunity.cases.listSeparator')) || t('views.opportunity.cases.emptyValue') }}
        </el-descriptions-item>
        <el-descriptions-item :label="t('views.opportunity.cases.scenario')" :span="2">{{ activeCase.scenario || t('views.opportunity.cases.emptyValue') }}</el-descriptions-item>
        <el-descriptions-item :label="t('views.opportunity.cases.painPoints')" :span="2">{{ activeCase.pain_points.join(t('views.opportunity.cases.listSeparator')) || t('views.opportunity.cases.emptyValue') }}</el-descriptions-item>
        <el-descriptions-item :label="t('views.opportunity.cases.outcomes')" :span="2">{{ activeCase.outcomes.join(t('views.opportunity.cases.listSeparator')) || t('views.opportunity.cases.emptyValue') }}</el-descriptions-item>
        <el-descriptions-item :label="t('views.opportunity.cases.applicabilityBoundary')" :span="2">{{ activeCase.applicability_boundary || t('views.opportunity.cases.emptyValue') }}</el-descriptions-item>
        <el-descriptions-item :label="t('views.opportunity.cases.materials')">{{ activeCase.documents.length }}</el-descriptions-item>
        <el-descriptions-item :label="t('views.opportunity.cases.accessScope')">{{ activeCase.access_scope }}</el-descriptions-item>
      </el-descriptions>
    </el-dialog>

    <el-dialog v-model="bindingVisible" :title="t('views.opportunity.cases.documentBinding')" width="520px">
      <el-alert type="info" :closable="false" :title="t('views.opportunity.cases.documentHint')" class="mb-16" />
      <el-form label-width="110px">
        <el-form-item :label="t('views.opportunity.cases.documentLabel')">
          <el-select v-model="bindingForm.document_id" filterable style="width: 100%" :placeholder="t('views.opportunity.cases.documentPlaceholder')">
            <el-option v-for="item in bindingDocuments" :key="item.id" :label="item.name" :value="item.id">
              <span>{{ item.name }}</span>
              <el-tag v-if="item.is_bound" size="small" type="info" class="document-status">{{ t('views.opportunity.cases.bound') }}</el-tag>
            </el-option>
          </el-select>
        </el-form-item>
        <el-form-item :label="t('views.opportunity.cases.documentVersion')"><el-input v-model="bindingForm.document_version" /></el-form-item>
        <el-form-item :label="t('views.opportunity.cases.allowDownload')"><el-switch v-model="bindingForm.allow_download" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="bindingVisible = false">{{ t('views.opportunity.cases.cancel') }}</el-button>
        <el-button type="primary" :loading="saving" @click="bindDocument">{{ t('views.opportunity.cases.confirm') }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import { useI18n } from 'vue-i18n'
import opportunityApi from '@/api/opportunity'
import type {
  CaseDocumentCandidate,
  CaseProfile,
  CaseProductReference,
  CaseStatus,
  DepartmentProfile,
  ProductProfile,
} from '@/api/type/opportunity'
import HxOverview from '../components/HxOverview.vue'
import { formatOpportunityTime } from '../utils/time'

type CaseAction = 'SUBMIT_REVIEW' | 'APPROVE' | 'REJECT' | 'PUBLISH' | 'OFFLINE' | 'ARCHIVE'

const statusOptions: CaseStatus[] = [
  'DRAFT', 'PENDING_REVIEW', 'APPROVED', 'REJECTED', 'PUBLISHED', 'OFFLINE', 'ARCHIVED',
]
const { t } = useI18n()
const loading = ref(false)
const saving = ref(false)
const cases = ref<CaseProfile[]>([])
const overviewMetrics = computed(() => [
  { label: t('views.opportunity.cases.currentFilter'), value: cases.value.length },
  { label: t('views.opportunity.cases.published'), value: cases.value.filter((item) => item.status === 'PUBLISHED').length, hint: t('views.opportunity.cases.currentFilter') },
  { label: t('views.opportunity.cases.pendingReview'), value: cases.value.filter((item) => item.status === 'PENDING_REVIEW').length, hint: t('views.opportunity.cases.currentFilter') },
])
const products = ref<ProductProfile[]>([])
const departments = ref<DepartmentProfile[]>([])
const filters = reactive({ name: '', industry: '', status: '' })
const editorVisible = ref(false)
const registrationVisible = ref(false)
const detailVisible = ref(false)
const bindingVisible = ref(false)
const registrationStep = ref(0)
const editingId = ref('')
const activeCase = ref<CaseProfile>()
const caseFormRef = ref<FormInstance>()
const painPointText = ref('')
const conditionText = ref('')
const outcomeText = ref('')
type ScaleRow = { id: number; metric: string; value: string; unit: string }
let scaleRowId = 0
const projectScaleRows = ref<ScaleRow[]>([])
const form = reactive<any>({})
const bindingForm = reactive({ document_id: '', document_version: '1.0', allow_download: false })
const availableDocuments = ref<CaseDocumentCandidate[]>([])
const bindingDocuments = ref<CaseDocumentCandidate[]>([])
const registrationFormRef = ref<FormInstance>()
const rules: FormRules = {
  code: [{ required: true, message: () => t('views.opportunity.cases.required'), trigger: 'blur' }],
  name: [{ required: true, message: () => t('views.opportunity.cases.required'), trigger: 'blur' }],
  product_codes: [{ required: true, type: 'array', min: 1, message: () => t('views.opportunity.cases.required'), trigger: 'change' }],
}
const registrationRules: FormRules = {
  document_id: [{ required: true, message: () => t('views.opportunity.cases.documentRequired'), trigger: 'change' }],
  code: [{ required: true, message: () => t('views.opportunity.cases.required'), trigger: 'blur' }],
  name: [{ required: true, message: () => t('views.opportunity.cases.required'), trigger: 'blur' }],
  product_codes: [{ required: true, type: 'array', min: 1, message: () => t('views.opportunity.cases.required'), trigger: 'change' }],
}

const defaultForm = () => ({
  code: '', name: '', industry: '', customer_type: '', scenario: '', implementation_process: '',
  applicability_boundary: '', product_codes: [] as string[], primary_product_code: '',
  owner_department_id: '', sensitivity_level: 'INTERNAL', access_scope: 'WORKSPACE',
  authorized_department_ids: [] as string[], authorized_user_ids: [],
  document_id: '', document_version: '1.0', allow_download: false,
})

const lines = (value: string) => value.split('\n').map((item) => item.trim()).filter(Boolean)
const formatTime = formatOpportunityTime
const statusText = (status: CaseStatus) => t(`views.opportunity.cases.status.${status}`)
const desensitizationText = (status: string) => t(`views.opportunity.cases.desensitization.${status}`)
const statusTag = (status: CaseStatus) => {
  if (status === 'PUBLISHED') return 'success'
  if (status === 'REJECTED' || status === 'OFFLINE') return 'danger'
  if (status === 'PENDING_REVIEW') return 'warning'
  return 'info'
}
const editable = (status: CaseStatus) => ['DRAFT', 'REJECTED', 'APPROVED'].includes(status)
const bindable = (status: CaseStatus) => ['DRAFT', 'REJECTED', 'APPROVED', 'OFFLINE'].includes(status)
const caseActions: Record<CaseStatus, CaseAction[]> = {
  DRAFT: ['SUBMIT_REVIEW'], REJECTED: ['SUBMIT_REVIEW', 'ARCHIVE'],
  PENDING_REVIEW: ['APPROVE', 'REJECT'], APPROVED: ['PUBLISH', 'ARCHIVE'],
  PUBLISHED: ['OFFLINE'], OFFLINE: ['PUBLISH', 'ARCHIVE'], ARCHIVED: [],
}
const availableActions = (status: CaseStatus): CaseAction[] => caseActions[status]
const actionText = (action: CaseAction) => t(`views.opportunity.cases.actionsStatus.${action}`)

const newScaleRow = (value: Partial<ScaleRow> = {}): ScaleRow => ({
  id: ++scaleRowId,
  metric: value.metric || '',
  value: value.value || '',
  unit: value.unit || '',
})
const resetScaleRows = () => { projectScaleRows.value = [newScaleRow()] }
const addScaleRow = () => projectScaleRows.value.push(newScaleRow())
const removeScaleRow = (index: number) => {
  if (projectScaleRows.value.length === 1) {
    projectScaleRows.value[0] = newScaleRow()
    return
  }
  projectScaleRows.value.splice(index, 1)
}
const setScaleRows = (scale: Record<string, unknown> = {}) => {
  const rows = Object.entries(scale).map(([metric, raw]) => {
    if (raw && typeof raw === 'object' && !Array.isArray(raw)) {
      const value = raw as Record<string, unknown>
      return newScaleRow({ metric, value: String(value.value ?? ''), unit: String(value.unit ?? '') })
    }
    return newScaleRow({ metric, value: String(raw ?? ''), unit: '' })
  })
  projectScaleRows.value = rows.length ? rows : [newScaleRow()]
}
const buildProjectScale = () => Object.fromEntries(
  projectScaleRows.value
    .filter((row) => row.metric.trim())
    .map((row) => [row.metric.trim(), row.unit.trim() ? { value: row.value.trim(), unit: row.unit.trim() } : row.value.trim()]),
)
const selectedDocumentName = computed(() => availableDocuments.value.find((item) => item.id === form.document_id)?.name || form.document_id || t('views.opportunity.cases.emptyValue'))
const selectedProductNames = computed(() => (form.product_codes || []).map((code: string) => products.value.find((item) => item.code === code)?.name || code).join(t('views.opportunity.cases.listSeparator')))
const scaleSummary = computed(() => Object.entries(buildProjectScale()).map(([key, value]) => `${key}: ${typeof value === 'object' ? `${(value as any).value}${(value as any).unit}` : value}`).join(t('views.opportunity.cases.summarySeparator')))

const loadCases = () => {
  opportunityApi.listCases({ ...filters }, loading).then((res) => (cases.value = res.data || []))
}
const resetFilters = () => {
  Object.assign(filters, { name: '', industry: '', status: '' })
  loadCases()
}
const openCreate = () => {
  editingId.value = ''
  Object.assign(form, defaultForm())
  painPointText.value = ''
  conditionText.value = ''
  outcomeText.value = ''
  resetScaleRows()
  registrationStep.value = 0
  registrationVisible.value = true
  opportunityApi.listAvailableCaseDocuments({}, loading).then((res) => {
    availableDocuments.value = res.data || []
  }).catch(() => ElMessage.error(t('views.opportunity.cases.loadFailed')))
}
const openEdit = (row: CaseProfile) => {
  editingId.value = row.id
  Object.assign(form, {
    ...defaultForm(), ...row,
    product_codes: row.products.map((item) => item.code),
    primary_product_code: row.products.find((item) => item.is_primary)?.code || '',
  })
  painPointText.value = row.pain_points.join('\n')
  conditionText.value = row.implementation_conditions.join('\n')
  outcomeText.value = row.outcomes.join('\n')
  form.document_id = row.documents[0]?.document_id || ''
  form.document_version = row.documents[0]?.document_version || '1.0'
  setScaleRows(row.project_scale || {})
  editorVisible.value = true
}
const openDetail = (row: CaseProfile) => {
  opportunityApi.getCase(row.id, loading).then((res) => {
    activeCase.value = res.data
    detailVisible.value = true
  })
}
const buildPayload = () => {
  const payload = {
    ...form,
    pain_points: lines(painPointText.value),
    implementation_conditions: lines(conditionText.value),
    outcomes: lines(outcomeText.value),
    project_scale: buildProjectScale(),
  }
  if (!payload.document_id) delete payload.document_id
  return payload
}
const saveCase = async () => {
  if (!(await caseFormRef.value?.validate().catch(() => false))) return
  const payload = buildPayload()
  if (!payload) return
  const request = editingId.value
    ? opportunityApi.updateCase(editingId.value, payload, saving)
    : opportunityApi.createCase(payload, saving)
  request.then(() => {
    ElMessage.success(t('views.opportunity.cases.saved'))
    editorVisible.value = false
    loadCases()
  })
}
const nextRegistrationStep = async () => {
  const valid = await registrationFormRef.value?.validate().catch(() => false)
  if (!valid) return
  if (registrationStep.value === 3 && projectScaleRows.value.some((row) => !row.metric.trim() || !row.value.trim())) {
    ElMessage.warning(t('views.opportunity.cases.invalidScale'))
    return
  }
  registrationStep.value += 1
}
const submitRegistration = async () => {
  const valid = await registrationFormRef.value?.validate().catch(() => false)
  if (!valid || !form.document_id) {
    ElMessage.warning(t('views.opportunity.cases.documentRequired'))
    return
  }
  const payload = buildPayload()
  if (!payload) return
  opportunityApi.createCase(payload, saving).then(() => {
    ElMessage.success(t('views.opportunity.cases.saved'))
    registrationVisible.value = false
    loadCases()
  })
}
const changeStatus = (row: CaseProfile, action: CaseAction) => {
  ElMessageBox.prompt(t('views.opportunity.cases.confirmAction', { action: actionText(action) }), t('views.opportunity.cases.statusOperation'), {
    inputPlaceholder: t('views.opportunity.cases.operationComment'),
    confirmButtonText: t('views.opportunity.cases.confirm'), cancelButtonText: t('views.opportunity.cases.cancel'),
  }).then(({ value }) => {
    opportunityApi.changeCaseStatus(row.id, { action, comment: value || '' }, saving).then(() => {
      ElMessage.success(t('views.opportunity.cases.statusUpdated'))
      loadCases()
    })
  }).catch(() => undefined)
}
const openBinding = (row: CaseProfile) => {
  activeCase.value = row
  Object.assign(bindingForm, { document_id: '', document_version: '1.0', allow_download: false })
  bindingVisible.value = true
  opportunityApi.listAvailableCaseDocuments({ case_id: row.id }, loading).then((res) => {
    bindingDocuments.value = res.data || []
    const existing = row.documents[0]
    if (existing && bindingDocuments.value.some((item) => item.id === existing.document_id)) {
      bindingForm.document_id = existing.document_id
      bindingForm.document_version = existing.document_version
    }
  }).catch(() => ElMessage.error(t('views.opportunity.cases.loadFailed')))
}
const bindDocument = () => {
  if (!activeCase.value || !bindingForm.document_id.trim()) {
    ElMessage.warning(t('views.opportunity.cases.documentRequired'))
    return
  }
  opportunityApi.bindCaseDocument(activeCase.value.id, bindingForm.document_id.trim(), {
    document_version: bindingForm.document_version,
    allow_download: bindingForm.allow_download,
  }, saving).then(() => {
    ElMessage.success(t('views.opportunity.cases.boundSaved'))
    bindingVisible.value = false
    loadCases()
  })
}

onMounted(() => {
  loadCases()
  opportunityApi.listProducts().then((res) => (products.value = res.data || []))
  opportunityApi.listDepartments().then((res) => (departments.value = res.data || []))
})
</script>

<style scoped>
.case-page .color-secondary {
  color: var(--muted);
}
.case-filter .filter-item {
  width: 250px;
}
.case-filter .el-input,
.case-filter .el-select {
  width: 190px;
}
.registration-hint {
  color: var(--muted);
  margin: 0 0 16px;
}
.registration-steps {
  margin-bottom: 24px;
}
.registration-step {
  min-height: 360px;
}
.document-status {
  float: right;
}
.document-actions {
  margin: -4px 0 16px 120px;
}
.scale-editor {
  width: 100%;
}
.scale-row {
  display: grid;
  grid-template-columns: minmax(120px, 1fr) minmax(120px, 1fr) minmax(100px, 0.75fr) auto;
  gap: 8px;
  align-items: center;
  margin-bottom: 8px;
}
.review-step {
  padding: 8px 0;
}
@media (max-width: 1280px) {
  .case-page :deep(.el-table__cell) {
    padding-left: 8px;
    padding-right: 8px;
  }
}
@media (max-width: 1024px) {
  .case-filter .filter-item {
    width: 210px;
  }
  .scale-row {
    grid-template-columns: 1fr 1fr;
  }
  .scale-row .el-button {
    justify-self: start;
  }
}
</style>
