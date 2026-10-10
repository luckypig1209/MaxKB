<template>
  <div class="embed-shell hx-tool-page">
    <header class="embed-header">
      <div class="brand">
        <LogoFull height="34px" />
        <span>商机智能分析</span>
      </div>
      <div v-if="session" class="session-user">{{ session.user.nick_name || session.user.username }}</div>
    </header>

    <main v-if="state !== 'READY'" class="state-panel">
      <el-icon v-if="state !== 'ERROR'" class="is-loading" :size="36"><Loading /></el-icon>
      <el-icon v-else color="var(--el-color-danger)" :size="40"><CircleClose /></el-icon>
      <h2>{{ state === 'ERROR' ? '暂时无法进入商机分析' : '正在建立安全会话' }}</h2>
      <p>{{ errorMessage || '请稍候，系统正在验证业务身份与访问范围。' }}</p>
      <el-button v-if="state === 'ERROR'" type="primary" @click="announceReady">重新连接</el-button>
    </main>

    <main v-else class="embed-content">
      <div class="hx-workspace">
        <aside>
          <section class="hx-panel">
            <h3 class="hx-panel__title">开始分析</h3>
            <RequirementInput v-model="requirement" :loading="submitting" :primary="!analysis" @submit="onCreate" />
          </section>
          <section class="hx-panel">
            <h3 class="hx-panel__title">最近商机</h3>
            <div v-if="history.length === 0" class="hx-empty">暂无分析记录</div>
            <div v-else class="history-list">
              <button
                v-for="item in history"
                :key="item.id"
                type="button"
                class="hx-rcard"
                :class="{ 'is-on': analysis?.id === item.id }"
                @click="loadAnalysis(item.id)"
              >
                <div class="flex-between">
                  <span class="hx-tag">{{ statusLabel(item.status) }}</span>
                </div>
                <p class="ellipsis-2 history-text">{{ item.original_requirement }}</p>
              </button>
            </div>
          </section>
        </aside>
        <section class="hx-panel" v-loading="loading">
          <div v-if="!analysis" class="hx-empty">提交需求后将在这里展示匹配结果</div>
          <template v-else>
              <AnalysisProgress
                :status="analysis.status"
                :error="analysis.error_message"
                :progress="analysis.result_snapshot?.progress"
                :cancelling="cancelling"
                @cancel="onCancelInFlight"
              />
              <RequirementProfilePanel
                v-if="analysis.requirement_profile"
                class="mt-16"
                :profile="analysis.requirement_profile"
                :version="analysis.requirement_profile_version"
                :pending-recommendation="analysis.status === 'ANALYZING'"
              />
              <ClarificationPanel
                v-if="analysis.status === 'NEED_CLARIFICATION'"
                class="mt-16"
                :questions="analysis.clarification_questions || []"
                :loading="submitting"
                @submit="onClarify"
              />
              <CandidateCards
                v-if="showCandidates"
                class="mt-16"
                :candidates="candidates"
                :selected-code="selectedCode"
                @select="selectedCode = $event"
                @open-evidence="openEvidence"
              />
              <MatchMatrix
                v-if="showCandidates"
                class="mt-16"
                :requirements="analysis.requirement_profile?.requirements || []"
                :candidates="candidates"
                @open-evidence="openEvidence"
              />
              <CaseReferences
                v-if="showCandidates || (analysis.result_snapshot?.case_enhancement && analysis.status !== 'ANALYZING')"
                class="mt-16"
                :candidates="candidates"
                :enhancement="analysis.result_snapshot?.case_enhancement"
                @open-evidence="openEvidence"
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
          </template>
        </section>
      </div>
    </main>
    <EvidenceDrawer v-model="evidenceVisible" :evidence="activeEvidence" />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { CircleClose, Loading } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import LogoFull from '@/components/logo/LogoFull.vue'
import type { CandidateResult, EvidenceItem, OpportunityAnalysis } from '@/api/type/opportunity'
import {
  clarifyEmbedAnalysis,
  clearEmbedSession,
  createEmbedAnalysis,
  decideEmbedAnalysis,
  exportEmbedReport,
  getEmbedAnalysis,
  initializeEmbedSession,
  listEmbedAnalyses,
  retryEmbedAnalysis,
  type EmbedSession,
  EmbedApiError,
} from '@/api/opportunity/embed'
import { shouldRefreshHistory, useAnalysisPolling } from '../composables/useAnalysisPolling'
import AnalysisActions from '../components/AnalysisActions.vue'
import AnalysisProgress from '../components/AnalysisProgress.vue'
import CandidateCards from '../components/CandidateCards.vue'
import CaseReferences from '../components/CaseReferences.vue'
import ClarificationPanel from '../components/ClarificationPanel.vue'
import EvidenceDrawer from '../components/EvidenceDrawer.vue'
import MatchMatrix from '../components/MatchMatrix.vue'
import RequirementInput from '../components/RequirementInput.vue'
import RequirementProfilePanel from '../components/RequirementProfile.vue'

type InitMessage = {
  type: 'BIA_EMBED_INIT'
  version: 1
  clientId: string
  accessToken: string
}

const { t } = useI18n()
const route = useRoute()
const clientId = String(route.params.clientId || '')
const state = ref<'WAITING' | 'VERIFYING' | 'READY' | 'ERROR'>('WAITING')
const errorMessage = ref('')
const trustedOrigin = ref('')
const session = ref<EmbedSession>()
const requirement = ref('')
const submitting = ref(false)
const loading = ref(false)
const analysis = ref<OpportunityAnalysis>()
const history = ref<OpportunityAnalysis[]>([])
const selectedCode = ref('')
const evidenceVisible = ref(false)
const activeEvidence = ref<EvidenceItem[]>([])
const cancelling = ref(false)
let renewTimer: number | undefined

const applyAnalysis = (data: OpportunityAnalysis) => {
  analysis.value = data
  const scored = (data.result_snapshot?.candidates || []).filter((item) => Number(item.score) > 0)
  if (!selectedCode.value || !scored.some((item) => item.product_code === selectedCode.value)) {
    selectedCode.value = scored[0]?.product_code || ''
  }
}

const poller = useAnalysisPolling<OpportunityAnalysis>({
  fetch: (id) => getEmbedAnalysis(id),
  onUpdate: (data) => {
    const previous = analysis.value?.status
    applyAnalysis(data)
    if (shouldRefreshHistory(previous, data.status)) {
      history.value = history.value.map((item) => (
        item.id === data.id ? { ...item, status: data.status } : item
      ))
      loadHistory()
    }
  },
  onError: (error) => {
    if (error instanceof EmbedApiError && error.status === 401) requestNewToken()
  },
})

const candidates = computed<CandidateResult[]>(() =>
  (analysis.value?.result_snapshot?.candidates || [])
    .filter((item) => Number(item.score) > 0)
    .sort((a, b) => (a.rank || 99) - (b.rank || 99)),
)
const showCandidates = computed(
  () => Boolean(candidates.value.length && analysis.value?.status !== 'ANALYZING'),
)

const postParent = (message: Record<string, unknown>, targetOrigin = '*') => {
  if (window.parent !== window) window.parent.postMessage(message, targetOrigin)
}

const announceReady = () => {
  clearEmbedSession()
  state.value = 'WAITING'
  errorMessage.value = ''
  postParent({ type: 'BIA_EMBED_READY', version: 1, clientId })
}

const requestNewToken = () => {
  clearEmbedSession()
  poller.stop()
  state.value = 'WAITING'
  errorMessage.value = ''
  if (trustedOrigin.value) {
    postParent({ type: 'BIA_EMBED_TOKEN_REQUIRED', version: 1, clientId }, trustedOrigin.value)
  } else {
    announceReady()
  }
}

const scheduleRenewal = (expiresAt: string) => {
  if (renewTimer) window.clearTimeout(renewTimer)
  const delay = Math.max(1000, new Date(expiresAt).getTime() - Date.now() - 30000)
  renewTimer = window.setTimeout(requestNewToken, delay)
}

const handleMessage = async (event: MessageEvent<InitMessage>) => {
  const message = event.data
  if (
    event.source !== window.parent ||
    !message ||
    message.type !== 'BIA_EMBED_INIT' ||
    message.version !== 1 ||
    message.clientId !== clientId ||
    typeof message.accessToken !== 'string' ||
    !message.accessToken
  ) return
  state.value = 'VERIFYING'
  try {
    const verified = await initializeEmbedSession(message.accessToken)
    if (verified.client_id !== clientId || verified.origin !== event.origin) {
      throw new Error('嵌入来源与令牌授权范围不一致')
    }
    trustedOrigin.value = event.origin
    session.value = verified
    state.value = 'READY'
    scheduleRenewal(verified.expires_at)
    await loadHistory()
    postParent({ type: 'BIA_EMBED_AUTHENTICATED', version: 1, clientId }, trustedOrigin.value)
  } catch (error) {
    clearEmbedSession()
    state.value = 'ERROR'
    errorMessage.value = error instanceof Error ? error.message : '安全会话验证失败'
  }
}

const statusLabel = (status?: string) => ({
  ANALYZING: '分析中', NEED_CLARIFICATION: '等待补充', WAITING_CONFIRMATION: '等待确认',
  CONFIRMED: '已确认', FAILED: '分析失败', CLOSED: '已关闭',
})[status || ''] || status || ''

const loadHistory = async () => {
  const data = await listEmbedAnalyses()
  history.value = data.records || []
}

const loadAnalysis = async (id: string, silent = false) => {
  if (!silent) loading.value = true
  try {
    await poller.load(id)
  } catch (error) {
    if (error instanceof EmbedApiError && error.status === 401) requestNewToken()
    else if (!silent) ElMessage.error(error instanceof Error ? error.message : '商机读取失败')
  } finally {
    if (!silent) loading.value = false
  }
}

const notifyChanged = () => {
  if (!analysis.value || !trustedOrigin.value) return
  postParent({
    type: 'BIA_EMBED_ANALYSIS_CHANGED', version: 1, clientId,
    analysisId: analysis.value.id, status: analysis.value.status,
  }, trustedOrigin.value)
}

const onCreate = async () => {
  if (!requirement.value.trim() || submitting.value) return
  submitting.value = true
  try {
    const created = await createEmbedAnalysis(requirement.value.trim())
    requirement.value = ''
    await loadAnalysis(created.id)
    await loadHistory()
    notifyChanged()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '商机创建失败')
  } finally {
    submitting.value = false
  }
}

const onClarify = async (answer: string) => {
  if (!analysis.value) return
  submitting.value = true
  try {
    analysis.value = await clarifyEmbedAnalysis(analysis.value.id, answer)
    if (poller.shouldKeepPolling(analysis.value.status)) poller.start(analysis.value.id)
    notifyChanged()
  } finally {
    submitting.value = false
  }
}

const onDecision = async (action: string, productCode?: string) => {
  if (!analysis.value) return
  try {
    const { value } = await ElMessageBox.prompt('请填写本次操作说明（可选）', '商机决策', {
      confirmButtonText: '确认', cancelButtonText: '取消', inputPlaceholder: '例如：进入技术确认或不适配原因',
    })
    analysis.value = await decideEmbedAnalysis(analysis.value.id, {
      action, product_code: productCode, reason: value || '',
    })
    await loadHistory()
    notifyChanged()
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') {
      ElMessage.error(error instanceof Error ? error.message : '商机决策失败')
    }
  }
}

const onCancelInFlight = async () => {
  if (!analysis.value || cancelling.value) return
  cancelling.value = true
  try {
    await ElMessageBox.confirm(
      t('views.opportunity.cancelInFlightHint'),
      t('views.opportunity.cancelAnalysis'),
      {
        confirmButtonText: t('views.opportunity.confirmCancel'),
        cancelButtonText: t('views.opportunity.keepRunning'),
        type: 'warning',
      },
    )
    analysis.value = await decideEmbedAnalysis(analysis.value.id, { action: 'CANCEL', reason: '' })
    poller.stop()
    await loadHistory()
    notifyChanged()
    ElMessage.success(t('views.opportunity.cancelled'))
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') {
      ElMessage.error(error instanceof Error ? error.message : '商机决策失败')
    }
  } finally {
    cancelling.value = false
  }
}

const onRetry = async () => {
  if (!analysis.value) return
  try {
    analysis.value = await retryEmbedAnalysis(analysis.value.id)
    if (poller.shouldKeepPolling(analysis.value.status)) poller.start(analysis.value.id)
    notifyChanged()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '重试失败')
  }
}

const onExport = async () => {
  if (!analysis.value?.report) return
  try {
    await exportEmbedReport(analysis.value.id, analysis.value.report.report_no)
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '报告导出失败')
  }
}

const openEvidence = (items: EvidenceItem[]) => {
  activeEvidence.value = items
  evidenceVisible.value = true
}

onMounted(() => {
  window.addEventListener('message', handleMessage)
  announceReady()
})
onUnmounted(() => {
  window.removeEventListener('message', handleMessage)
  poller.stop()
  if (renewTimer) window.clearTimeout(renewTimer)
  clearEmbedSession()
})
</script>

<style scoped>
.embed-shell {
  min-height: 100vh;
  width: 100%;
  min-width: 0;
  max-width: 100%;
  box-sizing: border-box;
  background: var(--canvas);
}
.embed-header {
  height: 64px;
  padding: 0 24px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  min-width: 0;
  max-width: 100%;
  box-sizing: border-box;
  background: var(--surface);
  border-bottom: 1px solid var(--line);
}
.brand { display: flex; align-items: center; gap: 12px; min-width: 0; flex-shrink: 1; font-size: 16px; font-weight: 700; color: var(--ink); }
.session-user { color: var(--muted); min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.state-panel { min-height: calc(100vh - 64px); display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 12px; text-align: center; }
.state-panel h2, .state-panel p { margin: 0; }
.embed-content {
  padding: 24px 24px 80px;
  width: 100%;
  min-width: 0;
  max-width: 100%;
  box-sizing: border-box;
}
.history-list { display: grid; gap: 10px; min-width: 0; max-width: 100%; }
.history-text { margin: 8px 0 0; color: var(--ink2); font-size: 12.5px; line-height: 1.5; }
.ellipsis-2 { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
@media (max-width: 1199px) { .embed-content { padding: 0 12px 40px; } }
@media (max-width: 1023px) {
  .embed-header { height: 56px; padding: 0 12px; }
  .brand { gap: 8px; }
}
</style>
