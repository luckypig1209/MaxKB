<template>
  <div class="opportunity-page p-16-24">
    <div class="flex-between mb-16">
      <div>
        <h2>{{ $t('views.opportunity.title') }}</h2>
        <p class="color-secondary mt-4">{{ $t('views.opportunity.subtitle') }}</p>
      </div>
      <div>
        <el-button
          v-if="hasPermission(RoleConst.WORKSPACE_MANAGE.getWorkspaceRole, 'OR')"
          @click="$router.push('/opportunity/cases')"
        >{{ $t('views.opportunity.caseManagement') }}</el-button>
        <el-button
          v-if="hasPermission(RoleConst.WORKSPACE_MANAGE.getWorkspaceRole, 'OR')"
          @click="$router.push('/opportunity/settings')"
        >{{ $t('views.opportunity.settings') }}</el-button>
      </div>
    </div>
    <el-row :gutter="16">
      <el-col :span="8">
        <el-card>
          <RequirementInput
            v-model="requirement"
            :loading="creating"
            @submit="onCreate"
          />
        </el-card>
        <el-card class="mt-16">
          <template #header>{{ $t('views.opportunity.history') }}</template>
          <el-empty v-if="history.length === 0" :description="$t('views.opportunity.noHistory')" />
          <el-timeline v-else>
            <el-timeline-item
              v-for="item in history"
              :key="item.id"
              :timestamp="item.create_time"
              @click="openAnalysis(item.id)"
              class="cursor"
              :class="{ 'is-active-history': analysis?.id === item.id }"
            >
              <div>{{ statusLabel(item.status) }}</div>
              <div class="ellipsis-2 color-secondary">{{ item.original_requirement }}</div>
            </el-timeline-item>
          </el-timeline>
        </el-card>
      </el-col>
      <el-col :span="16">
        <el-card v-loading="loading">
          <el-empty v-if="!analysis" :description="$t('views.opportunity.emptyResultHint')" />
          <template v-else>
            <AnalysisProgress
              :status="analysis.status"
              :error="analysis.error_message"
              :progress="analysis.result_snapshot?.progress"
            />
            <CandidateCards
              v-if="candidates.length"
              class="mt-16"
              :candidates="candidates"
              :selected-code="selectedCode"
              @select="selectedCode = $event"
              @open-evidence="openEvidence"
            />
            <ClarificationPanel
              v-if="analysis.status === 'NEED_CLARIFICATION'"
              class="mt-16"
              :questions="analysis.clarification_questions || []"
              :loading="creating"
              @submit="onClarify"
            />
            <AnalysisActions
              v-if="analysis.status !== 'ANALYZING'"
              class="mt-16"
              :analysis="analysis"
              :selected="selectedCode"
              @decision="onDecision"
              @retry="onRetry"
              @export="onExport"
            />
            <RequirementProfilePanel
              v-if="analysis.requirement_profile"
              class="mt-16"
              :profile="analysis.requirement_profile"
              :version="analysis.requirement_profile_version"
              @show-history="requirementHistoryVisible = true"
            />
            <el-collapse v-if="candidates.length" class="mt-16">
              <el-collapse-item :title="$t('views.opportunity.matchDetail')" name="matrix">
                <MatchMatrix
                  :requirements="analysis.requirement_profile?.requirements || []"
                  :candidates="candidates"
                  @open-evidence="openEvidence"
                />
              </el-collapse-item>
            </el-collapse>
            <CaseReferences
              v-if="candidates.length || analysis.result_snapshot?.case_enhancement"
              class="mt-16"
              :candidates="candidates"
              :enhancement="analysis.result_snapshot?.case_enhancement"
              @open-evidence="openEvidence"
            />
            <AuditTimeline
              class="mt-16"
              :logs="analysis.audit_logs || []"
              :report="analysis.report"
            />
          </template>
        </el-card>
      </el-col>
    </el-row>
    <EvidenceDrawer v-model="evidenceVisible" :evidence="activeEvidence" />
    <RequirementHistoryDrawer
      v-model="requirementHistoryVisible"
      :analysis-id="analysis?.id"
    />
  </div>
</template>
<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { hasPermission } from '@/utils/permission'
import { RoleConst } from '@/utils/permission/data'
import { createIdempotencyKey } from '@/utils/id'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import opportunityApi from '@/api/opportunity'
import type { CandidateResult, EvidenceItem, OpportunityAnalysis } from '@/api/type/opportunity'
import RequirementInput from './components/RequirementInput.vue'
import AnalysisProgress from './components/AnalysisProgress.vue'
import RequirementProfilePanel from './components/RequirementProfile.vue'
import ClarificationPanel from './components/ClarificationPanel.vue'
import CandidateCards from './components/CandidateCards.vue'
import MatchMatrix from './components/MatchMatrix.vue'
import EvidenceDrawer from './components/EvidenceDrawer.vue'
import AnalysisActions from './components/AnalysisActions.vue'
import CaseReferences from './components/CaseReferences.vue'
import AuditTimeline from './components/AuditTimeline.vue'
import RequirementHistoryDrawer from './components/RequirementHistoryDrawer.vue'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const requirement = ref('')
const creating = ref(false)
const loading = ref(false)
const analysis = ref<OpportunityAnalysis>()
const history = ref<OpportunityAnalysis[]>([])
const selectedCode = ref('')
const evidenceVisible = ref(false)
const activeEvidence = ref<EvidenceItem[]>([])
const requirementHistoryVisible = ref(false)
let timer: number | undefined
const submitting = ref(false)

const candidates = computed(() =>
  (analysis.value?.result_snapshot?.candidates || [])
    .filter((item) => Number(item.score) > 0)
    .sort((a, b) => (a.rank || 99) - (b.rank || 99)),
)

const statusLabel = (status?: string) => {
  const map: Record<string, string> = {
    ANALYZING: t('views.opportunity.analyzing'),
    NEED_CLARIFICATION: t('views.opportunity.clarification'),
    WAITING_CONFIRMATION: t('views.opportunity.waiting'),
    CONFIRMED: t('views.opportunity.confirmed'),
    FAILED: t('views.opportunity.failed'),
    CLOSED: t('views.opportunity.closed'),
  }
  return map[status || ''] || status
}

const loadHistory = () => {
  opportunityApi.listAnalyses({ current_page: 1, page_size: 10 }).then((res) => {
    history.value = res.data?.records || []
  })
}

const stopPoll = () => {
  if (timer) {
    window.clearInterval(timer)
    timer = undefined
  }
}

const loadAnalysis = (id: string, silent = false) => {
  if (!silent) loading.value = true
  return opportunityApi
    .getAnalysis(id, silent ? undefined : loading)
    .then((res) => {
      analysis.value = res.data
      const scored = (res.data?.result_snapshot?.candidates || []).filter((item: CandidateResult) => Number(item.score) > 0)
      if (!selectedCode.value || !scored.some((item) => item.product_code === selectedCode.value)) {
        selectedCode.value = scored[0]?.product_code || ''
      }
      if (res.data.status === 'ANALYZING') startPoll(id)
      else stopPoll()
    })
}

const startPoll = (id: string) => {
  stopPoll()
  timer = window.setInterval(() => {
    loadAnalysis(id, true)
  }, 1500)
}

const openAnalysis = (id: string) => {
  router.push(`/opportunity/${id}`)
}

const onCreate = async () => {
  if (!requirement.value.trim() || submitting.value) return
  submitting.value = true
  try {
    const settingRes = await opportunityApi.getSetting()
    const setting = settingRes.data || {}
    if (!setting.llm_model_id || !setting.product_knowledge_id) {
      ElMessage.warning(t('views.opportunity.engineRequiredBeforeAnalyze'))
      await router.push('/opportunity/settings?tab=engine')
      return
    }
    const res = await opportunityApi.createAnalysis({
      idempotency_key: createIdempotencyKey(),
      requirement: requirement.value.trim(),
    }, creating)
    loadHistory()
    const id = res.data?.id
    if (!id) {
      ElMessage.error(t('views.opportunity.failed'))
      return
    }
    await router.push(`/opportunity/${id}`)
    await loadAnalysis(id)
  } finally {
    submitting.value = false
  }
}

const onClarify = (answer: string) => {
  if (!analysis.value) return
  opportunityApi.submitClarification(analysis.value.id, answer, creating).then((res) => {
    analysis.value = res.data
    startPoll(res.data.id)
  })
}

const onDecision = (
  action: 'ACCEPT' | 'RESELECT' | 'REJECT' | 'NO_MATCH' | 'CANCEL',
  productCode?: string,
) => {
  if (!analysis.value) return
  ElMessageBox.prompt('请填写本次操作说明（可选）', '商机决策', {
    confirmButtonText: '确认', cancelButtonText: '取消', inputPlaceholder: '例如：进入技术确认或不适配原因',
  }).then(({ value }) => {
    opportunityApi.submitDecision(analysis.value!.id, {
      action, product_code: productCode, reason: value || '',
    }).then((res) => {
      analysis.value = res.data
      loadHistory()
    })
  }).catch(() => undefined)
}

const onExport = () => {
  if (!analysis.value) return
  opportunityApi.exportReport(analysis.value.id, analysis.value.report?.report_no, loading)
}

const onRetry = () => {
  if (!analysis.value) return
  opportunityApi.retryAnalysis(analysis.value.id, creating).then((res) => {
    analysis.value = res.data
    startPoll(res.data.id)
  })
}

const openEvidence = (items: EvidenceItem[]) => {
  activeEvidence.value = items
  evidenceVisible.value = true
}

watch(
  () => route.params.id,
  (id) => {
    const analysisId = Array.isArray(id) ? id[0] : id
    if (typeof analysisId === 'string' && analysisId && analysisId !== 'settings') {
      loadAnalysis(analysisId)
    }
  },
  { immediate: true },
)

loadHistory()
onUnmounted(stopPoll)
</script>
<style scoped>
.cursor {
  cursor: pointer;
}
.ellipsis-2 {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.color-secondary {
  color: var(--el-text-color-secondary);
}
.is-active-history {
  font-weight: 600;
}
</style>
