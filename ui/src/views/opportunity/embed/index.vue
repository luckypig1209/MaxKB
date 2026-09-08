<template>
  <div class="embed-shell">
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
      <el-button v-if="state === 'ERROR'" @click="announceReady">重新连接</el-button>
    </main>

    <main v-else class="embed-content">
      <el-row :gutter="16">
        <el-col :xs="24" :lg="8">
          <el-card shadow="never">
            <RequirementInput v-model="requirement" :loading="submitting" @submit="onCreate" />
          </el-card>
          <el-card class="mt-16" shadow="never">
            <template #header>最近商机</template>
            <el-empty v-if="history.length === 0" description="暂无分析记录" />
            <el-timeline v-else>
              <el-timeline-item
                v-for="item in history"
                :key="item.id"
                :timestamp="item.create_time"
                class="history-item"
                @click="loadAnalysis(item.id)"
              >
                <div>{{ statusLabel(item.status) }}</div>
                <div class="ellipsis-2 color-secondary">{{ item.original_requirement }}</div>
              </el-timeline-item>
            </el-timeline>
          </el-card>
        </el-col>
        <el-col :xs="24" :lg="16">
          <el-card v-loading="loading" shadow="never">
            <el-empty v-if="!analysis" description="提交需求后将在这里展示匹配结果" />
            <template v-else>
              <AnalysisProgress :status="analysis.status" :error="analysis.error_message" />
              <RequirementProfilePanel
                v-if="analysis.requirement_profile"
                class="mt-16"
                :profile="analysis.requirement_profile"
                :version="analysis.requirement_profile_version"
              />
              <ClarificationPanel
                v-if="analysis.status === 'NEED_CLARIFICATION'"
                class="mt-16"
                :questions="analysis.clarification_questions || []"
                :loading="submitting"
                @submit="onClarify"
              />
              <CandidateCards class="mt-16" :candidates="candidates" @open-evidence="openEvidence" />
              <MatchMatrix
                class="mt-16"
                :requirements="analysis.requirement_profile?.requirements || []"
                :candidates="candidates"
                @open-evidence="openEvidence"
              />
              <CaseReferences
                class="mt-16"
                :candidates="candidates"
                :enhancement="analysis.result_snapshot?.case_enhancement"
                @open-evidence="openEvidence"
              />
              <AnalysisActions
                class="mt-16"
                :analysis="analysis"
                :selected="selectedCode"
                @decision="onDecision"
                @retry="onRetry"
                @export="onExport"
              />
            </template>
          </el-card>
        </el-col>
      </el-row>
    </main>
    <EvidenceDrawer v-model="evidenceVisible" :evidence="activeEvidence" />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { CircleClose, Loading } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRoute } from 'vue-router'
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
let timer: number | undefined
let renewTimer: number | undefined

const candidates = computed<CandidateResult[]>(() => analysis.value?.result_snapshot?.candidates || [])

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
  stopPoll()
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

const stopPoll = () => {
  if (timer) window.clearInterval(timer)
  timer = undefined
}

const loadAnalysis = async (id: string, silent = false) => {
  if (!silent) loading.value = true
  try {
    analysis.value = await getEmbedAnalysis(id)
    selectedCode.value = analysis.value.result_snapshot?.candidates?.[0]?.product_code || ''
    if (analysis.value.status === 'ANALYZING') startPoll(id)
    else stopPoll()
  } catch (error) {
    if (error instanceof EmbedApiError && error.status === 401) requestNewToken()
    else if (!silent) ElMessage.error(error instanceof Error ? error.message : '商机读取失败')
  } finally {
    loading.value = false
  }
}

const startPoll = (id: string) => {
  stopPoll()
  timer = window.setInterval(() => loadAnalysis(id, true), 2000)
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
    startPoll(analysis.value.id)
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

const onRetry = async () => {
  if (!analysis.value) return
  try {
    analysis.value = await retryEmbedAnalysis(analysis.value.id)
    startPoll(analysis.value.id)
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
  stopPoll()
  if (renewTimer) window.clearTimeout(renewTimer)
  clearEmbedSession()
})
</script>

<style scoped>
.embed-shell { min-height: 100vh; background: var(--el-bg-color-page); }
.embed-header { height: 64px; padding: 0 24px; display: flex; align-items: center; justify-content: space-between; background: var(--el-bg-color); border-bottom: 1px solid var(--el-border-color-light); }
.brand { display: flex; align-items: center; gap: 18px; font-size: 18px; font-weight: 600; }
.session-user, .color-secondary { color: var(--el-text-color-secondary); }
.state-panel { min-height: calc(100vh - 64px); display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 12px; text-align: center; }
.state-panel h2, .state-panel p { margin: 0; }
.embed-content { padding: 16px 24px; }
.history-item { cursor: pointer; }
.ellipsis-2 { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
@media (max-width: 1199px) { .embed-content { padding: 12px; } .embed-content :deep(.el-col + .el-col) { margin-top: 16px; } }
</style>
