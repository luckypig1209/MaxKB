<template>
  <div class="hx-pmain opportunity-records-page hx-tool-page">
    <HxOverview
      :title="$t('views.opportunity.records.title')"
      :context="$t('views.opportunity.records.subtitle')"
      :metrics="overviewMetrics"
    >
      <template #actions>
        <el-button @click="$router.push('/opportunity')">{{ $t('views.opportunity.backToAnalysis') }}</el-button>
      </template>
    </HxOverview>

    <div class="hx-panel">
      <el-form class="record-filter" :inline="true" :model="filters" @submit.prevent>
        <el-form-item :label="$t('views.opportunity.records.product')">
          <el-input v-model="filters.product_code" clearable :placeholder="$t('views.opportunity.records.productPlaceholder')" />
        </el-form-item>
        <el-form-item :label="$t('views.opportunity.records.department')">
          <el-input v-model="filters.department_code" clearable :placeholder="$t('views.opportunity.records.departmentPlaceholder')" />
        </el-form-item>
        <el-form-item :label="$t('views.opportunity.records.status')">
          <el-select v-model="filters.status" clearable>
            <el-option
              v-for="item in statusOptions"
              :key="item"
              :label="statusLabel(item)"
              :value="item"
            />
          </el-select>
        </el-form-item>
        <el-form-item :label="$t('views.opportunity.records.acceptedAt')">
          <el-date-picker
            v-model="filters.dateRange"
            type="daterange"
            value-format="YYYY-MM-DD"
            :start-placeholder="$t('views.opportunity.records.startDate')"
            :end-placeholder="$t('views.opportunity.records.endDate')"
            range-separator="~"
          />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="search">{{ $t('views.opportunity.records.search') }}</el-button>
          <el-button @click="resetFilters">{{ $t('views.opportunity.records.clear') }}</el-button>
        </el-form-item>
      </el-form>

      <el-table v-loading="loading" :data="records" row-key="id" class="record-table">
        <el-table-column :label="$t('views.opportunity.records.product')" min-width="220">
          <template #default="{ row }">
            <div class="product-cell">
              <strong>{{ row.product_name || row.product_code || '-' }}</strong>
              <span v-if="row.product_code" class="muted">{{ row.product_code }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column :label="$t('views.opportunity.records.requirement')" min-width="260">
          <template #default="{ row }"><span class="requirement-cell">{{ row.original_requirement || '-' }}</span></template>
        </el-table-column>
        <el-table-column :label="$t('views.opportunity.records.department')" min-width="150">
          <template #default="{ row }">{{ row.department_name || row.department_code || $t('views.opportunity.departmentUnresolved') }}</template>
        </el-table-column>
        <el-table-column :label="$t('views.opportunity.records.status')" width="120">
          <template #default="{ row }"><el-tag :type="statusTag(row.status)">{{ statusLabel(row.status) }}</el-tag></template>
        </el-table-column>
        <el-table-column :label="$t('views.opportunity.records.acceptedAt')" width="170">
          <template #default="{ row }">{{ formatTime(row.accepted_at) }}</template>
        </el-table-column>
        <el-table-column :label="$t('views.opportunity.records.updatedAt')" width="170">
          <template #default="{ row }">{{ formatTime(row.update_time) }}</template>
        </el-table-column>
        <el-table-column :label="$t('common.operation')" width="120" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openDetail(row.id)">{{ $t('views.opportunity.records.view') }}</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty :description="$t('views.opportunity.records.empty')" />
        </template>
      </el-table>
      <div v-if="total > 0" class="record-pagination">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="pageSize"
          layout="total, sizes, prev, pager, next"
          :total="total"
          :page-sizes="[10, 20, 50]"
          @current-change="loadRecords"
          @size-change="onPageSizeChange"
        />
      </div>
    </div>

    <el-drawer v-model="detailVisible" :title="$t('views.opportunity.records.detail')" size="min(720px, 100%)">
      <template v-if="activeRecord">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item :label="$t('views.opportunity.records.product')">
            {{ activeRecord.product_name || activeRecord.product_code || '-' }}
          </el-descriptions-item>
          <el-descriptions-item :label="$t('views.opportunity.records.department')">
            {{ activeRecord.department_name || activeRecord.department_code || $t('views.opportunity.departmentUnresolved') }}
          </el-descriptions-item>
          <el-descriptions-item :label="$t('views.opportunity.records.acceptedAt')">{{ formatTime(activeRecord.accepted_at) }}</el-descriptions-item>
          <el-descriptions-item :label="$t('views.opportunity.records.report')">{{ activeRecord.report?.report_no || '-' }}</el-descriptions-item>
          <el-descriptions-item :label="$t('views.opportunity.records.requirement')" :span="2">
            <div class="detail-text">{{ activeRecord.original_requirement || '-' }}</div>
          </el-descriptions-item>
        </el-descriptions>

        <section class="detail-section">
          <h3>{{ $t('views.opportunity.records.followUp') }}</h3>
          <el-form label-position="top" @submit.prevent>
            <el-form-item :label="$t('views.opportunity.records.status')">
              <el-select v-model="statusDraft" class="status-control">
                <el-option v-for="item in availableStatusOptions" :key="item" :label="statusLabel(item)" :value="item" />
              </el-select>
            </el-form-item>
            <el-form-item :label="$t('views.opportunity.records.note')">
              <el-input v-model="noteDraft" type="textarea" :rows="3" maxlength="1024" show-word-limit />
            </el-form-item>
            <el-button type="primary" :loading="saving" @click="saveStatus">{{ $t('views.opportunity.records.saveStatus') }}</el-button>
          </el-form>
        </section>

        <section class="detail-section">
          <h3>{{ $t('views.opportunity.records.snapshot') }}</h3>
          <div v-if="activeRecord.candidate" class="snapshot-card">
            <strong>{{ activeRecord.candidate.product_name || activeRecord.product_name }}</strong>
            <span v-if="activeRecord.candidate.score != null">
              {{ $t('views.opportunity.matchScore', { score: normalizedScore(activeRecord.candidate.score) }) }}
            </span>
            <p>
              {{ activeRecord.candidate.recommendation_level
                ? $t(`views.opportunity.recommendation.${activeRecord.candidate.recommendation_level}`)
                : '-' }}
            </p>
          </div>
          <p v-if="activeRecord.cases?.length" class="detail-text">
            {{ $t('views.opportunity.records.cases') }}：{{ activeRecord.cases.map((item) => item.case_name).join('、') }}
          </p>
          <p v-if="activeRecord.evidence?.length" class="detail-text">
            {{ $t('views.opportunity.records.evidence') }}：{{ activeRecord.evidence.length }}
          </p>
        </section>

        <div class="detail-actions">
          <el-button type="primary" @click="viewAnalysis">{{ $t('views.opportunity.records.viewAnalysis') }}</el-button>
          <el-button :disabled="!activeRecord.report" @click="exportReport">{{ $t('views.opportunity.records.exportReport') }}</el-button>
        </div>
      </template>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import opportunityApi from '@/api/opportunity'
import type { OpportunityFollowUpStatus, OpportunityRecord } from '@/api/type/opportunity'
import HxOverview from '../components/HxOverview.vue'

const router = useRouter()
const { t } = useI18n()
const statusOptions: OpportunityFollowUpStatus[] = ['PENDING', 'FOLLOWING', 'TRANSFERRED', 'CLOSED']
const loading = ref(false)
const saving = ref(false)
const records = ref<OpportunityRecord[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const detailVisible = ref(false)
const activeRecord = ref<OpportunityRecord>()
const statusDraft = ref<OpportunityFollowUpStatus>('PENDING')
const noteDraft = ref('')
const filters = reactive<{
  status: OpportunityFollowUpStatus | ''
  product_code: string
  department_code: string
  dateRange: string[]
}>({ status: '', product_code: '', department_code: '', dateRange: [] })

const overviewMetrics = computed(() => [
  { label: t('views.opportunity.records.metricsTotal'), value: total.value },
  { label: t('views.opportunity.records.metricsPending'), value: records.value.filter((item) => item.status === 'PENDING').length },
  { label: t('views.opportunity.records.metricsFollowing'), value: records.value.filter((item) => item.status === 'FOLLOWING').length },
])

const transitionOptions: Record<OpportunityFollowUpStatus, OpportunityFollowUpStatus[]> = {
  PENDING: ['PENDING', 'FOLLOWING', 'TRANSFERRED', 'CLOSED'],
  FOLLOWING: ['FOLLOWING', 'TRANSFERRED', 'CLOSED'],
  TRANSFERRED: ['TRANSFERRED', 'FOLLOWING', 'CLOSED'],
  CLOSED: ['CLOSED'],
}
const availableStatusOptions = computed(() =>
  activeRecord.value ? transitionOptions[activeRecord.value.status] : statusOptions,
)
const statusLabel = (status: OpportunityFollowUpStatus) => t(`views.opportunity.records.statusValues.${status}`)
const statusTag = (status: OpportunityFollowUpStatus) => ({
  PENDING: 'warning', FOLLOWING: 'primary', TRANSFERRED: 'info', CLOSED: 'success',
}[status] as 'warning' | 'primary' | 'info' | 'success')
const formatTime = (value?: string) => (value ? value.replace('T', ' ').slice(0, 16) : '-')
const normalizedScore = (score: unknown) => {
  const value = Number(score)
  return Number.isFinite(value) ? Math.round(Math.min(100, Math.max(0, value))) : 0
}

const requestParams = () => {
  const params: Record<string, unknown> = { current_page: page.value, page_size: pageSize.value }
  if (filters.status) params.status = filters.status
  if (filters.product_code) params.product_code = filters.product_code
  if (filters.department_code) params.department_code = filters.department_code
  if (filters.dateRange[0]) params.start_time = `${filters.dateRange[0]}T00:00:00`
  if (filters.dateRange[1]) params.end_time = `${filters.dateRange[1]}T23:59:59`
  return params
}

const loadRecords = () => {
  loading.value = true
  opportunityApi.listOpportunityRecords(requestParams(), loading).then((res) => {
    records.value = res.data?.records || []
    total.value = res.data?.total || 0
  })
}
const search = () => {
  page.value = 1
  loadRecords()
}
const resetFilters = () => {
  filters.status = ''
  filters.product_code = ''
  filters.department_code = ''
  filters.dateRange = []
  search()
}
const onPageSizeChange = (value: number) => {
  pageSize.value = value
  page.value = 1
  loadRecords()
}
const openDetail = (id: string) => {
  detailVisible.value = true
  opportunityApi.getOpportunityRecord(id).then((res) => {
    activeRecord.value = res.data
    if (res.data) {
      statusDraft.value = res.data.status
      noteDraft.value = res.data.latest_note || ''
    }
  })
}
const saveStatus = () => {
  if (!activeRecord.value || saving.value) return
  const request = () => {
    saving.value = true
    opportunityApi.updateOpportunityRecordStatus(activeRecord.value!.id, {
      status: statusDraft.value,
      note: noteDraft.value,
    }, saving).then((res) => {
      activeRecord.value = res.data
      const index = records.value.findIndex((item) => item.id === res.data?.id)
      if (index >= 0 && res.data) records.value[index] = { ...records.value[index], ...res.data }
      ElMessage.success(t('views.opportunity.records.statusSaved'))
    }).finally(() => { saving.value = false })
  }
  if (statusDraft.value === 'CLOSED' && activeRecord.value.status !== 'CLOSED') {
    ElMessageBox.confirm(t('views.opportunity.records.closeConfirm'), t('views.opportunity.records.closeTitle'), {
      type: 'warning', confirmButtonText: t('views.opportunity.records.closeConfirmButton'),
      cancelButtonText: t('views.opportunity.records.cancelButton'),
    }).then(request).catch(() => undefined)
    return
  }
  request()
}
const viewAnalysis = () => {
  if (activeRecord.value) router.push(`/opportunity/${activeRecord.value.analysis_id}`)
}
const exportReport = () => {
  if (activeRecord.value?.report) opportunityApi.exportReport(activeRecord.value.analysis_id, activeRecord.value.report.report_no)
}

loadRecords()
</script>

<style scoped>
.record-filter { display: flex; flex-wrap: wrap; gap: 0 12px; }
.record-table { margin-top: 4px; }
.product-cell { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.muted { color: var(--muted); font-size: 12px; }
.requirement-cell { display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 2; overflow: hidden; }
.record-pagination { display: flex; justify-content: flex-end; padding-top: 16px; }
.detail-section { margin-top: 24px; }
.detail-section h3 { margin: 0 0 12px; font-size: 15px; }
.status-control { width: 220px; max-width: 100%; }
.detail-text { white-space: pre-wrap; word-break: break-word; line-height: 1.6; }
.snapshot-card { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 16px; border: 1px solid var(--line); border-radius: 10px; padding: 12px; }
.snapshot-card p { flex-basis: 100%; margin: 0; color: var(--muted); }
.detail-actions { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 26px; }
@media (max-width: 640px) {
  .record-filter :deep(.el-form-item) { width: 100%; margin-right: 0; }
  .record-filter :deep(.el-input), .record-filter :deep(.el-select), .record-filter :deep(.el-date-editor) { width: 100%; }
  .record-pagination { justify-content: center; overflow-x: auto; }
}
</style>
