import { Result } from '@/request/Result'
import { get, post, put, del, exportFile } from '@/request/index'
import type { Ref } from 'vue'
import useStore from '@/stores'
import type {
  DepartmentProfile,
  CaseProfile,
  OpportunityAnalysis,
  OpportunitySetting,
  OpportunityEmbedClient,
  ProductProfile,
  OpportunityRecord,
  OpportunityFollowUpStatus,
  CaseDocumentCandidate,
} from '@/api/type/opportunity'

const prefix: any = { _value: '/workspace/' }
Object.defineProperty(prefix, 'value', {
  get: function () {
    const { user } = useStore()
    return this._value + user.getWorkspaceId() + '/opportunity'
  },
})

const getSetting = (loading?: Ref<boolean>) => get(`${prefix.value}/setting`, {}, loading)
const updateSetting = (data: Partial<OpportunitySetting>, loading?: Ref<boolean>) =>
  put(`${prefix.value}/setting`, data, undefined, loading)

const listDepartments = (loading?: Ref<boolean>) => get(`${prefix.value}/departments`, {}, loading)
const createDepartment = (data: Partial<DepartmentProfile>, loading?: Ref<boolean>) =>
  post(`${prefix.value}/departments`, data, undefined, loading)
const updateDepartment = (id: string, data: Partial<DepartmentProfile>, loading?: Ref<boolean>) =>
  put(`${prefix.value}/departments/${id}`, data, undefined, loading)
const deleteDepartment = (id: string, loading?: Ref<boolean>) =>
  del(`${prefix.value}/departments/${id}`, undefined, {}, loading)

const listProducts = (params?: Record<string, unknown>, loading?: Ref<boolean>) =>
  get(`${prefix.value}/products`, params || {}, loading)
const createProduct = (data: Partial<ProductProfile>, loading?: Ref<boolean>) =>
  post(`${prefix.value}/products`, data, undefined, loading)
const updateProduct = (id: string, data: Partial<ProductProfile>, loading?: Ref<boolean>) =>
  put(`${prefix.value}/products/${id}`, data, undefined, loading)
const deleteProduct = (id: string, loading?: Ref<boolean>) =>
  del(`${prefix.value}/products/${id}`, undefined, {}, loading)
const bindProductDocument = (
  productId: string,
  documentId: string,
  data: Record<string, unknown>,
  loading?: Ref<boolean>,
) => put(`${prefix.value}/products/${productId}/documents/${documentId}/binding`, data, undefined, loading)

const listCases = (params?: Record<string, unknown>, loading?: Ref<boolean>) =>
  get(`${prefix.value}/cases`, params, loading)
const listAvailableCaseDocuments = (
  params?: { case_id?: string },
  loading?: Ref<boolean>,
): Promise<Result<CaseDocumentCandidate[]>> =>
  get(`${prefix.value}/cases/available-documents`, params || {}, loading)
type CaseWritePayload = Partial<CaseProfile> & {
  product_codes: string[]
  document_id?: string
  document_version?: string
  allow_download?: boolean
}
const createCase = (data: CaseWritePayload, loading?: Ref<boolean>) =>
  post(`${prefix.value}/cases`, data, undefined, loading)
const getCase = (id: string, loading?: Ref<boolean>): Promise<Result<CaseProfile>> =>
  get(`${prefix.value}/cases/${id}`, {}, loading)
const updateCase = (
  id: string,
  data: CaseWritePayload,
  loading?: Ref<boolean>,
) => put(`${prefix.value}/cases/${id}`, data, undefined, loading)
const changeCaseStatus = (
  id: string,
  data: { action: 'SUBMIT_REVIEW' | 'APPROVE' | 'REJECT' | 'PUBLISH' | 'OFFLINE' | 'ARCHIVE'; comment?: string },
  loading?: Ref<boolean>,
) => put(`${prefix.value}/cases/${id}/action`, data, undefined, loading)
const bindCaseDocument = (
  caseId: string,
  documentId: string,
  data: { document_version?: string; allow_download?: boolean },
  loading?: Ref<boolean>,
) => put(`${prefix.value}/cases/${caseId}/documents/${documentId}/binding`, data, undefined, loading)

const listAnalyses = (params?: Record<string, unknown>, loading?: Ref<boolean>) =>
  get(`${prefix.value}/analyses`, params, loading)
const createAnalysis = (data: { idempotency_key: string; requirement: string }, loading?: Ref<boolean>) =>
  post(`${prefix.value}/analyses`, data, undefined, loading)
const getAnalysis = (id: string, loading?: Ref<boolean>): Promise<Result<OpportunityAnalysis>> =>
  get(`${prefix.value}/analyses/${id}`, {}, loading)
const submitClarification = (id: string, answer: string, loading?: Ref<boolean>) =>
  post(`${prefix.value}/analyses/${id}/clarifications`, { answer }, undefined, loading)
const getRequirementVersions = (id: string, loading?: Ref<boolean>) =>
  get(`${prefix.value}/analyses/${id}/requirements/versions`, {}, loading)
const retryAnalysis = (id: string, loading?: Ref<boolean>) =>
  post(`${prefix.value}/analyses/${id}/retry`, {}, undefined, loading)
const confirmAnalysis = (
  id: string,
  data: { action: 'CONFIRM' | 'CLOSE'; product_code?: string; reason?: string },
  loading?: Ref<boolean>,
) => post(`${prefix.value}/analyses/${id}/confirm`, data, undefined, loading)
const submitDecision = (
  id: string,
  data: {
    action: 'ACCEPT' | 'RESELECT' | 'REJECT' | 'NO_MATCH' | 'CANCEL'
    product_code?: string
    reason?: string
  },
  loading?: Ref<boolean>,
) => post(`${prefix.value}/analyses/${id}/confirm`, data, undefined, loading)
const getReport = (id: string, loading?: Ref<boolean>) =>
  get(`${prefix.value}/analyses/${id}/report`, {}, loading)
const exportReport = (id: string, reportNo?: string, loading?: Ref<boolean>) =>
  exportFile(`${reportNo || '商机分析报告'}.html`, `${prefix.value}/analyses/${id}/report/export`, {}, loading)

const listOpportunityRecords = (params?: Record<string, unknown>, loading?: Ref<boolean>) =>
  get(`${prefix.value}/records`, params, loading)
const getOpportunityRecord = (id: string, loading?: Ref<boolean>): Promise<Result<OpportunityRecord>> =>
  get(`${prefix.value}/records/${id}`, {}, loading)
const updateOpportunityRecordStatus = (
  id: string,
  data: { status: OpportunityFollowUpStatus; note?: string },
  loading?: Ref<boolean>,
) => put(`${prefix.value}/records/${id}/status`, data, undefined, loading)

const listEmbedClients = (loading?: Ref<boolean>): Promise<Result<OpportunityEmbedClient[]>> =>
  get(`${prefix.value}/embed/clients`, {}, loading)
const createEmbedClient = (data: Partial<OpportunityEmbedClient>, loading?: Ref<boolean>) =>
  post(`${prefix.value}/embed/clients`, data, undefined, loading)
const updateEmbedClient = (id: string, data: Partial<OpportunityEmbedClient>, loading?: Ref<boolean>) =>
  put(`${prefix.value}/embed/clients/${id}`, data, undefined, loading)
const disableEmbedClient = (id: string, loading?: Ref<boolean>) =>
  del(`${prefix.value}/embed/clients/${id}`, undefined, {}, loading)
const rotateEmbedClientSecret = (id: string, loading?: Ref<boolean>) =>
  post(`${prefix.value}/embed/clients/${id}/rotate-secret`, {}, undefined, loading)

export default {
  getSetting,
  updateSetting,
  listDepartments,
  createDepartment,
  updateDepartment,
  deleteDepartment,
  listProducts,
  createProduct,
  updateProduct,
  deleteProduct,
  bindProductDocument,
  listCases,
  listAvailableCaseDocuments,
  createCase,
  getCase,
  updateCase,
  changeCaseStatus,
  bindCaseDocument,
  listAnalyses,
  createAnalysis,
  getAnalysis,
  submitClarification,
  getRequirementVersions,
  retryAnalysis,
  confirmAnalysis,
  submitDecision,
  getReport,
  exportReport,
  listOpportunityRecords,
  getOpportunityRecord,
  updateOpportunityRecordStatus,
  listEmbedClients,
  createEmbedClient,
  updateEmbedClient,
  disableEmbedClient,
  rotateEmbedClientSecret,
}
