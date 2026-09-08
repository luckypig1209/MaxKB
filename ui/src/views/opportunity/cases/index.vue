<template>
  <div class="p-16-24 case-page">
    <div class="flex-between mb-16">
      <div>
        <h2>{{ $t('views.opportunity.caseManagement') }}</h2>
        <p class="color-secondary mt-4">案例与产品事实分开管理，发布前必须完成脱敏审核</p>
      </div>
      <div>
        <el-button @click="$router.push('/opportunity')">返回分析</el-button>
        <el-button type="primary" @click="openCreate">新建案例</el-button>
      </div>
    </div>

    <el-card>
      <el-form class="case-filter" :inline="true" :model="filters">
        <el-form-item class="filter-item" label="案例">
          <el-input v-model="filters.name" clearable placeholder="名称关键字" />
        </el-form-item>
        <el-form-item class="filter-item" label="行业">
          <el-input v-model="filters.industry" clearable placeholder="行业" />
        </el-form-item>
        <el-form-item class="filter-item" label="状态">
          <el-select v-model="filters.status" clearable>
            <el-option v-for="item in statusOptions" :key="item" :label="statusText(item)" :value="item" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="loadCases">查询</el-button>
          <el-button @click="resetFilters">重置</el-button>
        </el-form-item>
      </el-form>

      <el-table v-loading="loading" :data="cases" row-key="id">
        <el-table-column prop="code" label="案例编码" min-width="200" />
        <el-table-column prop="name" label="案例名称" min-width="220" />
        <el-table-column prop="industry" label="行业" width="130" />
        <el-table-column label="关联产品" min-width="170">
          <template #default="{ row }">
            {{ row.products.map((item: CaseProductReference) => item.name).join('、') || '-' }}
          </template>
        </el-table-column>
        <el-table-column label="审核/发布" width="190">
          <template #default="{ row }">
            <el-tag :type="statusTag(row.status)">{{ statusText(row.status) }}</el-tag>
            <el-tag class="ml-4" :type="row.desensitization_status === 'PASSED' ? 'success' : 'warning'">
              {{ desensitizationText(row.desensitization_status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="资料" width="90">
          <template #default="{ row }">{{ row.documents.length }}</template>
        </el-table-column>
        <el-table-column label="更新时间" width="170">
          <template #default="{ row }">{{ formatTime(row.update_time) }}</template>
        </el-table-column>
        <el-table-column label="操作" fixed="right" width="330">
          <template #default="{ row }">
            <el-button link type="primary" @click="openDetail(row)">查看</el-button>
            <el-button v-if="editable(row.status)" link type="primary" @click="openEdit(row)">编辑</el-button>
            <el-button v-if="bindable(row.status)" link type="primary" @click="openBinding(row)">绑定资料</el-button>
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
    </el-card>

    <el-dialog v-model="editorVisible" :title="editingId ? '编辑案例' : '新建案例'" width="760px">
      <el-form ref="caseFormRef" :model="form" :rules="rules" label-width="110px">
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="案例编码" prop="code"><el-input v-model="form.code" /></el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="案例名称" prop="name"><el-input v-model="form.name" /></el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="行业"><el-input v-model="form.industry" /></el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="客户类型"><el-input v-model="form.customer_type" /></el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="业务场景"><el-input v-model="form.scenario" type="textarea" :rows="2" /></el-form-item>
        <el-form-item label="客户痛点">
          <el-input v-model="painPointText" type="textarea" :rows="2" placeholder="每行一项" />
        </el-form-item>
        <el-form-item label="项目规模">
          <el-input v-model="projectScaleText" type="textarea" :rows="2" placeholder='JSON，例如 {"devices":"1000+"}' />
        </el-form-item>
        <el-form-item label="实施条件">
          <el-input v-model="conditionText" type="textarea" :rows="2" placeholder="每行一项" />
        </el-form-item>
        <el-form-item label="实施过程"><el-input v-model="form.implementation_process" type="textarea" :rows="2" /></el-form-item>
        <el-form-item label="实施成效">
          <el-input v-model="outcomeText" type="textarea" :rows="2" placeholder="每行一项" />
        </el-form-item>
        <el-form-item label="适用边界"><el-input v-model="form.applicability_boundary" type="textarea" :rows="2" /></el-form-item>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="关联产品" prop="product_codes">
              <el-select v-model="form.product_codes" multiple style="width: 100%">
                <el-option v-for="item in products" :key="item.code" :label="item.name" :value="item.code" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="主产品">
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
            <el-form-item label="归属部门">
              <el-select v-model="form.owner_department_id" clearable style="width: 100%">
                <el-option v-for="item in departments" :key="item.id" :label="item.name" :value="item.id" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="敏感等级">
              <el-select v-model="form.sensitivity_level" style="width: 100%">
                <el-option label="公开" value="PUBLIC" />
                <el-option label="内部" value="INTERNAL" />
                <el-option label="敏感" value="SENSITIVE" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="授权范围">
              <el-select v-model="form.access_scope" style="width: 100%">
                <el-option label="工作空间" value="WORKSPACE" />
                <el-option label="部门" value="DEPARTMENT" />
                <el-option label="私有" value="PRIVATE" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
      </el-form>
      <template #footer>
        <el-button @click="editorVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveCase">保存草稿</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="detailVisible" title="案例详情" width="720px">
      <el-descriptions v-if="activeCase" :column="2" border>
        <el-descriptions-item label="案例编码">{{ activeCase.code }}</el-descriptions-item>
        <el-descriptions-item label="状态">{{ statusText(activeCase.status) }}</el-descriptions-item>
        <el-descriptions-item label="行业">{{ activeCase.industry || '-' }}</el-descriptions-item>
        <el-descriptions-item label="客户类型">{{ activeCase.customer_type || '-' }}</el-descriptions-item>
        <el-descriptions-item label="关联产品" :span="2">
          {{ activeCase.products.map((item) => item.name).join('、') || '-' }}
        </el-descriptions-item>
        <el-descriptions-item label="业务场景" :span="2">{{ activeCase.scenario || '-' }}</el-descriptions-item>
        <el-descriptions-item label="客户痛点" :span="2">{{ activeCase.pain_points.join('、') || '-' }}</el-descriptions-item>
        <el-descriptions-item label="实施成效" :span="2">{{ activeCase.outcomes.join('、') || '-' }}</el-descriptions-item>
        <el-descriptions-item label="适用边界" :span="2">{{ activeCase.applicability_boundary || '-' }}</el-descriptions-item>
        <el-descriptions-item label="资料数量">{{ activeCase.documents.length }}</el-descriptions-item>
        <el-descriptions-item label="授权范围">{{ activeCase.access_scope }}</el-descriptions-item>
      </el-descriptions>
    </el-dialog>

    <el-dialog v-model="bindingVisible" title="绑定案例资料" width="520px">
      <el-alert type="info" :closable="false" title="文档必须位于当前配置的案例知识库中" class="mb-16" />
      <el-form label-width="110px">
        <el-form-item label="文档 ID"><el-input v-model="bindingForm.document_id" /></el-form-item>
        <el-form-item label="资料版本"><el-input v-model="bindingForm.document_version" /></el-form-item>
        <el-form-item label="允许下载"><el-switch v-model="bindingForm.allow_download" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="bindingVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="bindDocument">确认绑定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import opportunityApi from '@/api/opportunity'
import type {
  CaseProfile,
  CaseProductReference,
  CaseStatus,
  DepartmentProfile,
  ProductProfile,
} from '@/api/type/opportunity'

type CaseAction = 'SUBMIT_REVIEW' | 'APPROVE' | 'REJECT' | 'PUBLISH' | 'OFFLINE' | 'ARCHIVE'

const statusOptions: CaseStatus[] = [
  'DRAFT', 'PENDING_REVIEW', 'APPROVED', 'REJECTED', 'PUBLISHED', 'OFFLINE', 'ARCHIVED',
]
const loading = ref(false)
const saving = ref(false)
const cases = ref<CaseProfile[]>([])
const products = ref<ProductProfile[]>([])
const departments = ref<DepartmentProfile[]>([])
const filters = reactive({ name: '', industry: '', status: '' })
const editorVisible = ref(false)
const detailVisible = ref(false)
const bindingVisible = ref(false)
const editingId = ref('')
const activeCase = ref<CaseProfile>()
const caseFormRef = ref<FormInstance>()
const painPointText = ref('')
const conditionText = ref('')
const outcomeText = ref('')
const projectScaleText = ref('{}')
const form = reactive<any>({})
const bindingForm = reactive({ document_id: '', document_version: '1.0', allow_download: false })
const rules: FormRules = {
  code: [{ required: true, message: '请输入案例编码', trigger: 'blur' }],
  name: [{ required: true, message: '请输入案例名称', trigger: 'blur' }],
  product_codes: [{ required: true, type: 'array', min: 1, message: '至少关联一个产品', trigger: 'change' }],
}

const defaultForm = () => ({
  code: '', name: '', industry: '', customer_type: '', scenario: '', implementation_process: '',
  applicability_boundary: '', product_codes: [] as string[], primary_product_code: '',
  owner_department_id: '', sensitivity_level: 'INTERNAL', access_scope: 'WORKSPACE',
  authorized_department_ids: [] as string[], authorized_user_ids: [] as string[],
})

const lines = (value: string) => value.split('\n').map((item) => item.trim()).filter(Boolean)
const formatTime = (value?: string) => value ? value.replace('T', ' ').slice(0, 16) : '-'
const statusText = (status: CaseStatus) => ({
  DRAFT: '草稿', PENDING_REVIEW: '待审核', APPROVED: '已审核', REJECTED: '已驳回',
  PUBLISHED: '已发布', OFFLINE: '已下线', ARCHIVED: '已归档',
}[status])
const desensitizationText = (status: string) => ({ PASSED: '已脱敏', REJECTED: '脱敏驳回', PENDING: '待脱敏' }[status] || status)
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
const actionText = (action: CaseAction) => ({
  SUBMIT_REVIEW: '提交审核', APPROVE: '通过', REJECT: '驳回', PUBLISH: '发布',
  OFFLINE: '下线', ARCHIVE: '归档',
}[action])

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
  projectScaleText.value = '{}'
  editorVisible.value = true
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
  projectScaleText.value = JSON.stringify(row.project_scale || {}, null, 2)
  editorVisible.value = true
}
const openDetail = (row: CaseProfile) => {
  opportunityApi.getCase(row.id, loading).then((res) => {
    activeCase.value = res.data
    detailVisible.value = true
  })
}
const buildPayload = () => {
  let projectScale: Record<string, unknown> = {}
  try {
    projectScale = projectScaleText.value.trim() ? JSON.parse(projectScaleText.value) : {}
  } catch {
    ElMessage.error('项目规模必须是有效 JSON')
    return null
  }
  return {
    ...form,
    pain_points: lines(painPointText.value),
    implementation_conditions: lines(conditionText.value),
    outcomes: lines(outcomeText.value),
    project_scale: projectScale,
  }
}
const saveCase = async () => {
  if (!(await caseFormRef.value?.validate().catch(() => false))) return
  const payload = buildPayload()
  if (!payload) return
  const request = editingId.value
    ? opportunityApi.updateCase(editingId.value, payload, saving)
    : opportunityApi.createCase(payload, saving)
  request.then(() => {
    ElMessage.success('案例草稿已保存')
    editorVisible.value = false
    loadCases()
  })
}
const changeStatus = (row: CaseProfile, action: CaseAction) => {
  ElMessageBox.prompt(`确认执行“${actionText(action)}”吗？`, '案例状态操作', {
    inputPlaceholder: '可填写审核或操作意见',
    confirmButtonText: '确认', cancelButtonText: '取消',
  }).then(({ value }) => {
    opportunityApi.changeCaseStatus(row.id, { action, comment: value || '' }, saving).then(() => {
      ElMessage.success('案例状态已更新')
      loadCases()
    })
  }).catch(() => undefined)
}
const openBinding = (row: CaseProfile) => {
  activeCase.value = row
  Object.assign(bindingForm, { document_id: '', document_version: '1.0', allow_download: false })
  bindingVisible.value = true
}
const bindDocument = () => {
  if (!activeCase.value || !bindingForm.document_id.trim()) {
    ElMessage.warning('请输入文档 ID')
    return
  }
  opportunityApi.bindCaseDocument(activeCase.value.id, bindingForm.document_id.trim(), {
    document_version: bindingForm.document_version,
    allow_download: bindingForm.allow_download,
  }, saving).then(() => {
    ElMessage.success('案例资料已绑定')
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
  color: var(--el-text-color-secondary);
}
.case-filter .filter-item {
  width: 250px;
}
.case-filter .el-input,
.case-filter .el-select {
  width: 190px;
}
</style>
