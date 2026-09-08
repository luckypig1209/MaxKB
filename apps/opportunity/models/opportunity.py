# coding=utf-8
"""
    @project: MaxKB
    @Author：bia
    @file： opportunity.py
    @date：2026/9/3
    @desc: 商机智能分析数据模型
"""
import uuid_utils.compat as uuid
from django.db import models

from common.mixins.app_model_mixin import AppModelMixin


class SearchModeChoices(models.TextChoices):
    EMBEDDING = 'embedding', 'embedding'
    KEYWORDS = 'keywords', 'keywords'
    BLEND = 'blend', 'blend'


class DepartmentStatus(models.TextChoices):
    ACTIVE = 'ACTIVE', 'ACTIVE'
    INACTIVE = 'INACTIVE', 'INACTIVE'


class ProductStatus(models.TextChoices):
    DRAFT = 'DRAFT', 'DRAFT'
    ACTIVE = 'ACTIVE', 'ACTIVE'
    INACTIVE = 'INACTIVE', 'INACTIVE'


class CaseStatus(models.TextChoices):
    DRAFT = 'DRAFT', 'DRAFT'
    PENDING_REVIEW = 'PENDING_REVIEW', 'PENDING_REVIEW'
    APPROVED = 'APPROVED', 'APPROVED'
    REJECTED = 'REJECTED', 'REJECTED'
    PUBLISHED = 'PUBLISHED', 'PUBLISHED'
    OFFLINE = 'OFFLINE', 'OFFLINE'
    ARCHIVED = 'ARCHIVED', 'ARCHIVED'


class DesensitizationStatus(models.TextChoices):
    PENDING = 'PENDING', 'PENDING'
    PASSED = 'PASSED', 'PASSED'
    REJECTED = 'REJECTED', 'REJECTED'


class SensitivityLevel(models.TextChoices):
    PUBLIC = 'PUBLIC', 'PUBLIC'
    INTERNAL = 'INTERNAL', 'INTERNAL'
    SENSITIVE = 'SENSITIVE', 'SENSITIVE'


class CaseAccessScope(models.TextChoices):
    WORKSPACE = 'WORKSPACE', 'WORKSPACE'
    DEPARTMENT = 'DEPARTMENT', 'DEPARTMENT'
    PRIVATE = 'PRIVATE', 'PRIVATE'


class MappingRole(models.TextChoices):
    OWNER = 'OWNER', 'OWNER'
    RD = 'RD', 'RD'
    PRESALES = 'PRESALES', 'PRESALES'
    DELIVERY = 'DELIVERY', 'DELIVERY'
    COLLABORATOR = 'COLLABORATOR', 'COLLABORATOR'


class AnalysisStatus(models.TextChoices):
    DRAFT = 'DRAFT', 'DRAFT'
    ANALYZING = 'ANALYZING', 'ANALYZING'
    NEED_CLARIFICATION = 'NEED_CLARIFICATION', 'NEED_CLARIFICATION'
    FAILED = 'FAILED', 'FAILED'
    WAITING_CONFIRMATION = 'WAITING_CONFIRMATION', 'WAITING_CONFIRMATION'
    CONFIRMED = 'CONFIRMED', 'CONFIRMED'
    CLOSED = 'CLOSED', 'CLOSED'


class DecisionAction(models.TextChoices):
    ACCEPT = 'ACCEPT', 'ACCEPT'
    RESELECT = 'RESELECT', 'RESELECT'
    REJECT = 'REJECT', 'REJECT'
    NO_MATCH = 'NO_MATCH', 'NO_MATCH'
    CANCEL = 'CANCEL', 'CANCEL'


class RequirementProfileSource(models.TextChoices):
    INITIAL = 'INITIAL', 'INITIAL'
    CLARIFICATION = 'CLARIFICATION', 'CLARIFICATION'


class OpportunitySetting(AppModelMixin):
    id = models.UUIDField(primary_key=True, max_length=128, default=uuid.uuid7, editable=False, verbose_name="主键id")
    workspace_id = models.CharField(max_length=64, verbose_name="工作空间id", unique=True, db_index=True)
    llm_model_id = models.UUIDField(verbose_name="LLM模型id", null=True, blank=True)
    product_knowledge_id = models.UUIDField(verbose_name="产品知识库id", null=True, blank=True)
    case_knowledge_id = models.UUIDField(verbose_name="案例知识库id", null=True, blank=True)
    rerank_model_id = models.UUIDField(verbose_name="重排模型id", null=True, blank=True)
    search_mode = models.CharField(max_length=32, choices=SearchModeChoices.choices,
                                   default=SearchModeChoices.BLEND, verbose_name="检索模式")
    top_n = models.IntegerField(default=20, verbose_name="召回条数")
    similarity = models.FloatField(default=0.3, verbose_name="相似度阈值")
    max_candidates = models.IntegerField(default=5, verbose_name="最大候选产品数")
    prompt_version = models.CharField(max_length=128, default='requirement-v1/match-v1', verbose_name="提示词版本")
    meta = models.JSONField(default=dict, verbose_name="扩展配置")

    class Meta:
        db_table = "bia_opportunity_setting"


class DepartmentProfile(AppModelMixin):
    id = models.UUIDField(primary_key=True, max_length=128, default=uuid.uuid7, editable=False, verbose_name="主键id")
    workspace_id = models.CharField(max_length=64, verbose_name="工作空间id", db_index=True)
    code = models.CharField(max_length=64, verbose_name="部门编码", db_index=True)
    name = models.CharField(max_length=128, verbose_name="部门名称")
    status = models.CharField(max_length=16, choices=DepartmentStatus.choices,
                              default=DepartmentStatus.ACTIVE, db_index=True)
    meta = models.JSONField(default=dict, verbose_name="扩展信息")

    class Meta:
        db_table = "bia_department_profile"
        constraints = [
            models.UniqueConstraint(fields=['workspace_id', 'code'], name='uniq_bia_department_workspace_code'),
        ]


class ProductProfile(AppModelMixin):
    id = models.UUIDField(primary_key=True, max_length=128, default=uuid.uuid7, editable=False, verbose_name="主键id")
    workspace_id = models.CharField(max_length=64, verbose_name="工作空间id", db_index=True)
    code = models.CharField(max_length=64, verbose_name="产品编码", db_index=True)
    name = models.CharField(max_length=128, verbose_name="产品名称")
    aliases = models.JSONField(default=list, verbose_name="产品别名")
    product_line = models.CharField(max_length=128, default='', blank=True, verbose_name="产品线")
    description = models.TextField(default='', blank=True, verbose_name="产品描述")
    status = models.CharField(max_length=16, choices=ProductStatus.choices,
                              default=ProductStatus.DRAFT, db_index=True)
    meta = models.JSONField(default=dict, verbose_name="扩展信息")

    class Meta:
        db_table = "bia_product_profile"
        constraints = [
            models.UniqueConstraint(fields=['workspace_id', 'code'], name='uniq_bia_product_workspace_code'),
        ]


class ProductDepartmentMapping(AppModelMixin):
    id = models.UUIDField(primary_key=True, max_length=128, default=uuid.uuid7, editable=False, verbose_name="主键id")
    workspace_id = models.CharField(max_length=64, verbose_name="工作空间id", db_index=True)
    product = models.ForeignKey(ProductProfile, on_delete=models.CASCADE, db_constraint=False,
                                related_name='department_mappings', verbose_name="产品")
    department = models.ForeignKey(DepartmentProfile, on_delete=models.CASCADE, db_constraint=False,
                                   related_name='product_mappings', verbose_name="部门")
    role = models.CharField(max_length=32, choices=MappingRole.choices, default=MappingRole.OWNER, db_index=True)
    owner_user_id = models.CharField(max_length=128, null=True, blank=True, verbose_name="负责人用户id")
    effective_from = models.DateTimeField(null=True, blank=True, verbose_name="生效时间")
    effective_to = models.DateTimeField(null=True, blank=True, verbose_name="失效时间")
    is_active = models.BooleanField(default=True, db_index=True)
    meta = models.JSONField(default=dict, verbose_name="扩展信息")

    class Meta:
        db_table = "bia_product_department_mapping"
        indexes = [
            models.Index(fields=['workspace_id', 'product', 'role', 'is_active'],
                         name='idx_bia_pdm_ws_product_role'),
        ]


class CaseProfile(AppModelMixin):
    id = models.UUIDField(primary_key=True, max_length=128, default=uuid.uuid7, editable=False, verbose_name="主键id")
    workspace_id = models.CharField(max_length=64, verbose_name="工作空间id", db_index=True)
    code = models.CharField(max_length=64, verbose_name="案例编码", db_index=True)
    name = models.CharField(max_length=128, verbose_name="案例名称")
    industry = models.CharField(max_length=128, default='', blank=True, verbose_name="行业")
    customer_type = models.CharField(max_length=128, default='', blank=True, verbose_name="客户类型")
    scenario = models.TextField(default='', blank=True, verbose_name="业务场景")
    pain_points = models.JSONField(default=list, verbose_name="客户痛点")
    project_scale = models.JSONField(default=dict, verbose_name="项目规模")
    implementation_conditions = models.JSONField(default=list, verbose_name="实施条件")
    implementation_process = models.TextField(default='', blank=True, verbose_name="实施过程")
    outcomes = models.JSONField(default=list, verbose_name="实施成效")
    applicability_boundary = models.TextField(default='', blank=True, verbose_name="适用边界")
    status = models.CharField(max_length=32, choices=CaseStatus.choices,
                              default=CaseStatus.DRAFT, db_index=True, verbose_name="案例状态")
    desensitization_status = models.CharField(
        max_length=16, choices=DesensitizationStatus.choices,
        default=DesensitizationStatus.PENDING, db_index=True, verbose_name="脱敏状态",
    )
    sensitivity_level = models.CharField(
        max_length=16, choices=SensitivityLevel.choices,
        default=SensitivityLevel.INTERNAL, db_index=True, verbose_name="敏感等级",
    )
    access_scope = models.CharField(
        max_length=16, choices=CaseAccessScope.choices,
        default=CaseAccessScope.WORKSPACE, db_index=True, verbose_name="授权范围",
    )
    owner_department = models.ForeignKey(
        DepartmentProfile, on_delete=models.SET_NULL, null=True, blank=True, db_constraint=False,
        related_name='case_profiles', verbose_name="归属部门",
    )
    authorized_department_ids = models.JSONField(default=list, verbose_name="授权部门id")
    authorized_user_ids = models.JSONField(default=list, verbose_name="授权用户id")
    creator_user_id = models.CharField(max_length=128, verbose_name="创建人", db_index=True)
    reviewer_user_id = models.CharField(max_length=128, null=True, blank=True, verbose_name="审核人")
    reviewed_at = models.DateTimeField(null=True, blank=True, verbose_name="审核时间")
    review_comment = models.CharField(max_length=1024, default='', blank=True, verbose_name="审核意见")
    effective_from = models.DateTimeField(null=True, blank=True, verbose_name="生效时间")
    effective_to = models.DateTimeField(null=True, blank=True, verbose_name="失效时间")
    meta = models.JSONField(default=dict, verbose_name="扩展信息")

    class Meta:
        db_table = "bia_case_profile"
        constraints = [
            models.UniqueConstraint(fields=['workspace_id', 'code'], name='uniq_bia_case_workspace_code'),
        ]
        indexes = [
            models.Index(fields=['workspace_id', 'status', 'industry'], name='idx_bia_case_ws_status_ind'),
            models.Index(fields=['workspace_id', 'effective_from', 'effective_to'], name='idx_bia_case_ws_effective'),
        ]


class CaseProductMapping(AppModelMixin):
    id = models.UUIDField(primary_key=True, max_length=128, default=uuid.uuid7, editable=False, verbose_name="主键id")
    workspace_id = models.CharField(max_length=64, verbose_name="工作空间id", db_index=True)
    case = models.ForeignKey(CaseProfile, on_delete=models.CASCADE, db_constraint=False,
                             related_name='product_mappings', verbose_name="案例")
    product = models.ForeignKey(ProductProfile, on_delete=models.CASCADE, db_constraint=False,
                                related_name='case_mappings', verbose_name="产品")
    product_version = models.CharField(max_length=64, default='1.0', verbose_name="关联产品版本")
    is_primary = models.BooleanField(default=False, db_index=True, verbose_name="是否主产品")
    is_active = models.BooleanField(default=True, db_index=True, verbose_name="是否有效")
    meta = models.JSONField(default=dict, verbose_name="扩展信息")

    class Meta:
        db_table = "bia_case_product_mapping"
        constraints = [
            models.UniqueConstraint(fields=['workspace_id', 'case', 'product'], name='uniq_bia_case_product'),
        ]
        indexes = [
            models.Index(fields=['workspace_id', 'product', 'is_active'], name='idx_bia_cpm_ws_product'),
        ]


class CaseDocumentMapping(AppModelMixin):
    id = models.UUIDField(primary_key=True, max_length=128, default=uuid.uuid7, editable=False, verbose_name="主键id")
    workspace_id = models.CharField(max_length=64, verbose_name="工作空间id", db_index=True)
    case = models.ForeignKey(CaseProfile, on_delete=models.CASCADE, db_constraint=False,
                             related_name='document_mappings', verbose_name="案例")
    knowledge_id = models.UUIDField(verbose_name="案例知识库id", db_index=True)
    document_id = models.UUIDField(verbose_name="案例文档id", db_index=True)
    document_version = models.CharField(max_length=64, default='1.0', verbose_name="文档版本")
    is_active = models.BooleanField(default=True, db_index=True, verbose_name="是否有效")
    meta = models.JSONField(default=dict, verbose_name="扩展信息")

    class Meta:
        db_table = "bia_case_document_mapping"
        constraints = [
            models.UniqueConstraint(fields=['workspace_id', 'case', 'document_id'], name='uniq_bia_case_document'),
        ]
        indexes = [
            models.Index(fields=['workspace_id', 'knowledge_id', 'is_active'], name='idx_bia_cdm_ws_knowledge'),
        ]


class OpportunityAnalysis(AppModelMixin):
    id = models.UUIDField(primary_key=True, max_length=128, default=uuid.uuid7, editable=False, verbose_name="主键id")
    workspace_id = models.CharField(max_length=64, verbose_name="工作空间id", db_index=True)
    user_id = models.CharField(max_length=128, verbose_name="创建人", db_index=True)
    idempotency_key = models.CharField(max_length=128, verbose_name="幂等键")
    status = models.CharField(max_length=32, choices=AnalysisStatus.choices,
                              default=AnalysisStatus.DRAFT, db_index=True)
    original_requirement = models.TextField(verbose_name="原始需求")
    requirement_profile = models.JSONField(default=dict, verbose_name="需求画像")
    clarification_history = models.JSONField(default=list, verbose_name="澄清历史")
    clarification_questions = models.JSONField(default=list, verbose_name="澄清问题")
    result_snapshot = models.JSONField(default=dict, verbose_name="结果快照")
    confirmed_product_code = models.CharField(max_length=64, null=True, blank=True, verbose_name="确认产品编码")
    error_code = models.CharField(max_length=64, null=True, blank=True, verbose_name="错误码")
    error_message = models.CharField(max_length=1024, null=True, blank=True, verbose_name="错误信息")
    runtime_ms = models.IntegerField(default=0, verbose_name="运行耗时毫秒")
    model_snapshot = models.JSONField(default=dict, verbose_name="模型快照")
    knowledge_snapshot = models.JSONField(default=dict, verbose_name="知识快照")
    rule_version = models.CharField(max_length=64, default='scoring-v1', verbose_name="规则版本")

    class Meta:
        db_table = "bia_opportunity_analysis"
        constraints = [
            models.UniqueConstraint(fields=['workspace_id', 'user_id', 'idempotency_key'],
                                    name='uniq_bia_analysis_idempotency'),
        ]
        indexes = [
            models.Index(fields=['workspace_id', 'status', 'create_time'], name='idx_bia_ana_ws_status_time'),
        ]


class RequirementProfileVersion(AppModelMixin):
    id = models.UUIDField(primary_key=True, max_length=128, default=uuid.uuid7, editable=False, verbose_name="主键id")
    workspace_id = models.CharField(max_length=64, verbose_name="工作空间id", db_index=True)
    analysis = models.ForeignKey(
        OpportunityAnalysis, on_delete=models.CASCADE, db_constraint=False,
        related_name='requirement_versions', verbose_name="分析任务",
    )
    version = models.IntegerField(default=1, verbose_name="画像版本")
    source = models.CharField(
        max_length=32, choices=RequirementProfileSource.choices,
        default=RequirementProfileSource.INITIAL, verbose_name="版本来源",
    )
    clarification_round = models.IntegerField(default=0, verbose_name="澄清轮次")
    profile = models.JSONField(default=dict, verbose_name="不可变需求画像快照")
    operator_user_id = models.CharField(max_length=128, verbose_name="操作人")

    class Meta:
        db_table = 'bia_requirement_profile_version'
        constraints = [
            models.UniqueConstraint(fields=['analysis', 'version'], name='uniq_bia_requirement_profile_version'),
        ]
        indexes = [
            models.Index(fields=['workspace_id', 'analysis', 'version'], name='idx_bia_req_profile_ws_ana'),
        ]


class OpportunityEmbedClient(AppModelMixin):
    id = models.UUIDField(primary_key=True, max_length=128, default=uuid.uuid7, editable=False, verbose_name="主键id")
    workspace_id = models.CharField(max_length=64, verbose_name="工作空间id", db_index=True)
    name = models.CharField(max_length=128, verbose_name="接入方名称")
    client_id = models.CharField(max_length=64, unique=True, db_index=True, verbose_name="客户端id")
    secret_digest = models.CharField(max_length=256, verbose_name="客户端密钥摘要")
    allowed_origins = models.JSONField(default=list, verbose_name="允许嵌入来源")
    allowed_scopes = models.JSONField(default=list, verbose_name="允许权限范围")
    token_ttl_seconds = models.IntegerField(default=300, verbose_name="短期令牌有效秒数")
    is_active = models.BooleanField(default=True, db_index=True, verbose_name="是否启用")
    creator_user_id = models.CharField(max_length=128, verbose_name="创建人")
    last_used_at = models.DateTimeField(null=True, blank=True, verbose_name="最后使用时间")
    meta = models.JSONField(default=dict, verbose_name="扩展信息")

    class Meta:
        db_table = 'bia_opportunity_embed_client'
        indexes = [
            models.Index(fields=['workspace_id', 'is_active'], name='idx_bia_embed_client_ws'),
        ]


class OpportunityEmbedSession(AppModelMixin):
    id = models.UUIDField(primary_key=True, max_length=128, default=uuid.uuid7, editable=False, verbose_name="会话id")
    workspace_id = models.CharField(max_length=64, verbose_name="工作空间id", db_index=True)
    client = models.ForeignKey(
        OpportunityEmbedClient, on_delete=models.CASCADE, db_constraint=False,
        related_name='embed_sessions', verbose_name="嵌入客户端",
    )
    user_id = models.CharField(max_length=128, db_index=True, verbose_name="系统用户id")
    origin = models.CharField(max_length=512, verbose_name="嵌入来源")
    department_ids = models.JSONField(default=list, verbose_name="部门范围")
    scopes = models.JSONField(default=list, verbose_name="权限范围")
    expires_at = models.DateTimeField(db_index=True, verbose_name="过期时间")
    revoked_at = models.DateTimeField(null=True, blank=True, db_index=True, verbose_name="撤销时间")
    last_seen_at = models.DateTimeField(null=True, blank=True, verbose_name="最后访问时间")

    class Meta:
        db_table = 'bia_opportunity_embed_session'
        indexes = [
            models.Index(fields=['workspace_id', 'client', 'expires_at'], name='idx_bia_embed_session_ws'),
        ]


class OpportunityReport(AppModelMixin):
    id = models.UUIDField(primary_key=True, max_length=128, default=uuid.uuid7, editable=False, verbose_name="主键id")
    workspace_id = models.CharField(max_length=64, verbose_name="工作空间id", db_index=True)
    analysis = models.ForeignKey(
        OpportunityAnalysis, on_delete=models.CASCADE, db_constraint=False,
        related_name='reports', verbose_name="分析任务",
    )
    report_no = models.CharField(max_length=96, verbose_name="报告编号", db_index=True)
    version = models.IntegerField(default=1, verbose_name="报告版本")
    snapshot = models.JSONField(default=dict, verbose_name="不可变报告快照")
    generated_by = models.CharField(max_length=128, verbose_name="生成人")
    is_current = models.BooleanField(default=True, db_index=True, verbose_name="是否当前版本")

    class Meta:
        db_table = 'bia_opportunity_report'
        constraints = [
            models.UniqueConstraint(fields=['workspace_id', 'report_no'], name='uniq_bia_report_no'),
            models.UniqueConstraint(fields=['analysis', 'version'], name='uniq_bia_report_version'),
        ]
        indexes = [
            models.Index(fields=['workspace_id', 'analysis', 'is_current'], name='idx_bia_report_ws_analysis'),
        ]


class OpportunityFeedback(AppModelMixin):
    id = models.UUIDField(primary_key=True, max_length=128, default=uuid.uuid7, editable=False, verbose_name="主键id")
    workspace_id = models.CharField(max_length=64, verbose_name="工作空间id", db_index=True)
    analysis = models.ForeignKey(
        OpportunityAnalysis, on_delete=models.CASCADE, db_constraint=False,
        related_name='feedback_records', verbose_name="分析任务",
    )
    action = models.CharField(max_length=32, choices=DecisionAction.choices, db_index=True, verbose_name="决策动作")
    product_code = models.CharField(max_length=64, null=True, blank=True, verbose_name="选择产品编码")
    reason = models.CharField(max_length=1024, default='', blank=True, verbose_name="原因")
    operator_user_id = models.CharField(max_length=128, db_index=True, verbose_name="操作人")
    result_snapshot = models.JSONField(default=dict, verbose_name="操作时结果快照")

    class Meta:
        db_table = 'bia_opportunity_feedback'
        indexes = [
            models.Index(fields=['workspace_id', 'analysis', 'create_time'], name='idx_bia_feedback_ws_analysis'),
        ]


class OpportunityAuditLog(AppModelMixin):
    id = models.UUIDField(primary_key=True, max_length=128, default=uuid.uuid7, editable=False, verbose_name="主键id")
    workspace_id = models.CharField(max_length=64, verbose_name="工作空间id", db_index=True)
    analysis = models.ForeignKey(
        OpportunityAnalysis, on_delete=models.CASCADE, db_constraint=False,
        related_name='audit_logs', verbose_name="分析任务",
    )
    action = models.CharField(max_length=64, db_index=True, verbose_name="操作")
    operator_user_id = models.CharField(max_length=128, db_index=True, verbose_name="操作人")
    detail = models.JSONField(default=dict, verbose_name="审计详情")

    class Meta:
        db_table = 'bia_opportunity_audit_log'
        indexes = [
            models.Index(fields=['workspace_id', 'analysis', 'create_time'], name='idx_bia_audit_ws_analysis'),
        ]
