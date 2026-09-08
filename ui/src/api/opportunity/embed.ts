import type { OpportunityAnalysis } from '@/api/type/opportunity'
import { createIdempotencyKey } from '@/utils/id'

type ApiResult<T> = {
  code: number
  message: string
  data: T
}

export type EmbedSession = {
  workspace_id: string
  client_id: string
  session_id: string
  user_id: string
  origin: string
  department_ids: string[]
  scopes: string[]
  expires_at: string
  user: { id: string; username: string; nick_name: string }
}

let accessToken = ''

export class EmbedApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public code?: number,
  ) {
    super(message)
  }
}

const apiBase = `${window.MaxKB?.prefix ? window.MaxKB.prefix : '/admin'}/api/opportunity/embed`

const request = async <T>(path: string, options: RequestInit = {}, token = accessToken): Promise<T> => {
  const response = await fetch(`${apiBase}${path}`, {
    ...options,
    cache: 'no-store',
    credentials: 'omit',
    headers: {
      Accept: 'application/json',
      ...(options.body ? { 'Content-Type': 'application/json' } : {}),
      Authorization: `Bearer ${token}`,
      ...(options.headers || {}),
    },
  })
  const payload = (await response.json().catch(() => ({
    code: response.status, message: '服务响应格式异常', data: null,
  }))) as ApiResult<T>
  if (!response.ok || payload.code !== 200) {
    throw new EmbedApiError(payload.message || `请求失败（${response.status}）`, response.status, payload.code)
  }
  return payload.data
}

export const initializeEmbedSession = async (token: string) => {
  const session = await request<EmbedSession>('/session', {}, token)
  accessToken = token
  return session
}

export const clearEmbedSession = () => {
  accessToken = ''
}

export const listEmbedAnalyses = () =>
  request<{ records: OpportunityAnalysis[] }>('/analyses?current_page=1&page_size=10')

export const createEmbedAnalysis = (requirement: string) =>
  request<{ id: string; status: string }>('/analyses', {
    method: 'POST',
    body: JSON.stringify({ idempotency_key: createIdempotencyKey(), requirement }),
  })

export const getEmbedAnalysis = (id: string) =>
  request<OpportunityAnalysis>(`/analyses/${encodeURIComponent(id)}`)

export const clarifyEmbedAnalysis = (id: string, answer: string) =>
  request<OpportunityAnalysis>(`/analyses/${encodeURIComponent(id)}/clarifications`, {
    method: 'POST', body: JSON.stringify({ answer }),
  })

export const retryEmbedAnalysis = (id: string) =>
  request<OpportunityAnalysis>(`/analyses/${encodeURIComponent(id)}/retry`, {
    method: 'POST', body: JSON.stringify({}),
  })

export const decideEmbedAnalysis = (
  id: string,
  data: { action: string; product_code?: string; reason?: string },
) => request<OpportunityAnalysis>(`/analyses/${encodeURIComponent(id)}/confirm`, {
  method: 'POST', body: JSON.stringify(data),
})

export const exportEmbedReport = async (id: string, reportNo: string) => {
  const response = await fetch(`${apiBase}/analyses/${encodeURIComponent(id)}/report/export`, {
    cache: 'no-store',
    credentials: 'omit',
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  if (!response.ok) throw new EmbedApiError('报告导出失败', response.status)
  const url = URL.createObjectURL(await response.blob())
  const link = document.createElement('a')
  link.href = url
  link.download = `${reportNo || '商机分析报告'}.html`
  link.click()
  URL.revokeObjectURL(url)
}
