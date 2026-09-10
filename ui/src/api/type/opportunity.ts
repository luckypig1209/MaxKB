export type SearchMode = 'embedding' | 'keywords' | 'blend'
export type AnalysisStatus =
  | 'DRAFT'
  | 'ANALYZING'
  | 'NEED_CLARIFICATION'
  | 'FAILED'
  | 'WAITING_CONFIRMATION'
  | 'CONFIRMED'
  | 'CLOSED'
export type OpportunityFollowUpStatus = 'PENDING' | 'FOLLOWING' | 'TRANSFERRED' | 'CLOSED'
export type MatchStatus = 'FULL' | 'PARTIAL' | 'NO' | 'INSUFFICIENT'
export type RecommendationLevel = 'RECOMMENDED' | 'TECHNICAL_CONFIRMATION' | 'NOT_RECOMMENDED'

export interface OpportunitySetting {
  id?: string
  workspace_id?: string
  llm_model_id?: string | null
  product_knowledge_id?: string | null
  case_knowledge_id?: string | null
  rerank_model_id?: string | null
  search_mode: SearchMode
  top_n: number
  similarity: number
  max_candidates: number
  prompt_version?: string
}

export interface OpportunityEmbedClient {
  id: string
  name: string
  client_id: string
  embed_path?: string
  allowed_origins: string[]
  allowed_scopes: string[]
  token_ttl_seconds: number
  is_active: boolean
  active_session_count: number
  last_used_at?: string | null
  create_time?: string
  client_secret?: string
}

export type CaseStatus =
  | 'DRAFT'
  | 'PENDING_REVIEW'
  | 'APPROVED'
  | 'REJECTED'
  | 'PUBLISHED'
  | 'OFFLINE'
  | 'ARCHIVED'
export type DesensitizationStatus = 'PENDING' | 'PASSED' | 'REJECTED'
export type SensitivityLevel = 'PUBLIC' | 'INTERNAL' | 'SENSITIVE'
export type CaseAccessScope = 'WORKSPACE' | 'DEPARTMENT' | 'PRIVATE'

export interface CaseProductReference {
  id: string
  code: string
  name: string
  product_version: string
  is_primary: boolean
}

export interface CaseDocumentReference {
  id: string
  knowledge_id: string
  document_id: string
  document_version: string
  is_active: boolean
}

export interface CaseProfile {
  id: string
  code: string
  name: string
  industry: string
  customer_type: string
  scenario: string
  pain_points: string[]
  project_scale: Record<string, unknown>
  implementation_conditions: string[]
  implementation_process: string
  outcomes: string[]
  applicability_boundary: string
  status: CaseStatus
  desensitization_status: DesensitizationStatus
  sensitivity_level: SensitivityLevel
  access_scope: CaseAccessScope
  owner_department_id?: string | null
  authorized_department_ids?: string[]
  authorized_user_ids?: string[]
  products: CaseProductReference[]
  documents: CaseDocumentReference[]
  effective_from?: string | null
  effective_to?: string | null
  review_comment?: string
  create_time?: string
  update_time?: string
}

export interface DepartmentProfile {
  id: string
  code: string
  name: string
  status: 'ACTIVE' | 'INACTIVE'
}

export interface ProductDepartment {
  status: 'RESOLVED' | 'UNRESOLVED'
  owner_department_code?: string | null
  owner_department_name?: string | null
  owner_user_id?: string | null
  support_departments?: Array<Record<string, string>>
}

export interface ProductProfile {
  id: string
  code: string
  name: string
  aliases: string[]
  product_line: string
  description: string
  status: 'DRAFT' | 'ACTIVE' | 'INACTIVE'
  department: ProductDepartment
  owner_department_id?: string
}

export interface RequirementItem {
  id: string
  description: string
  priority: 'must' | 'should' | 'nice_to_have'
  category: string
  source_text: string
}

export interface RequirementProfile {
  schema_version: string
  customer_context?: Record<string, string | null>
  business_scenarios: string[]
  pain_points: string[]
  requirements: RequirementItem[]
  constraints: string[]
  excluded_conditions: string[]
  missing_information: string[]
  clarification_questions: string[]
}

export interface RequirementProfileVersion {
  id: string
  version: number
  source: 'INITIAL' | 'CLARIFICATION'
  clarification_round: number
  operator_user_id: string
  profile: RequirementProfile
  create_time?: string
}

export interface EvidenceItem {
  knowledge_id: string
  document_id: string
  paragraph_id: string
  document_name: string
  title: string
  content_excerpt: string
  similarity: number
  document_version: string
}

export interface MatchItem {
  requirement_id: string
  status: MatchStatus
  reason: string
  evidence: EvidenceItem[]
}

export interface CandidateResult {
  product_code: string
  product_name: string
  product_version?: string
  rank: number | null
  score: number
  recommendation_level: RecommendationLevel
  hard_constraint_failed: boolean
  score_detail: {
    requirement_score: number
    evidence_completeness: number
    case_score: number
    product_score?: number
    case_weight?: number
    case_score_blocked_reason?: string
  }
  match_items: MatchItem[]
  risks: string[]
  missing_information: string[]
  department: ProductDepartment
  case_references: CaseReference[]
}

export interface CaseReference {
  case_id: string
  case_code: string
  case_name: string
  industry: string
  scenario: string
  project_scale: Record<string, unknown>
  outcomes: string[]
  applicability_boundary: string
  product_version: string
  version_compatible: boolean
  similarity: number
  evidence: EvidenceItem[]
}

export interface OpportunityAnalysis {
  id: string
  status: AnalysisStatus
  original_requirement: string
  requirement_profile?: RequirementProfile
  requirement_profile_version?: number | null
  clarification_questions?: string[]
  clarification_history?: Array<{ answer: string }>
    result_snapshot?: {
    candidates?: CandidateResult[]
    excluded?: CandidateResult[]
    summary?: string
    case_references?: Array<CaseReference & { product_code: string }>
    case_enhancement?: {
      status: 'NOT_CONFIGURED' | 'SKIPPED' | 'NO_MATCH' | 'APPLIED' | 'DEGRADED'
      count: number
      warning?: string | null
    }
    progress?: {
      current: string
      detail?: string
      index: number
      total: number
      steps: Array<{ key: string; label: string; status: 'done' | 'active' | 'pending' }>
    }
  }
  confirmed_product_code?: string | null
  report?: {
    id: string
    report_no: string
    version: number
    create_time?: string
  } | null
  feedback?: Array<{
    id: string
    action: 'ACCEPT' | 'RESELECT' | 'REJECT' | 'NO_MATCH' | 'CANCEL'
    product_code?: string | null
    reason: string
    operator_user_id: string
    create_time?: string
  }>
  audit_logs?: Array<{
    id: string
    action: string
    operator_user_id: string
    detail: Record<string, unknown>
    create_time?: string
  }>
  error_code?: string | null
  error_message?: string | null
  create_time?: string
  update_time?: string
}

export interface OpportunityRecord {
  id: string
  workspace_id: string
  analysis_id: string
  owner_user_id: string
  decision_action: 'ACCEPT' | 'RESELECT'
  product_code: string
  product_name: string
  department_code: string
  department_name: string
  status: OpportunityFollowUpStatus
  accepted_at?: string
  latest_note: string
  original_requirement: string
  create_time?: string
  update_time?: string
  decision_snapshot?: Record<string, unknown>
  requirement_profile?: RequirementProfile
  candidate?: CandidateResult
  cases?: CaseReference[]
  evidence?: EvidenceItem[]
  report?: { id: string; report_no: string; version: number; create_time?: string } | null
}
