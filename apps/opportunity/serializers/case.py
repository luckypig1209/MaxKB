# coding=utf-8
"""案例档案、审核流和案例资料绑定。"""
from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone
from rest_framework import serializers

from common.exception.app_exception import AppApiException
from knowledge.models import Document, State, Status, TaskType
from opportunity.models import (
    CaseAccessScope,
    CaseDocumentMapping,
    CaseProductMapping,
    CaseProfile,
    CaseStatus,
    DesensitizationStatus,
    ProductProfile,
    ProductStatus,
    SensitivityLevel,
)
from opportunity.serializers.common import (
    model_time,
    require_case,
    require_department,
    require_knowledge,
)
from opportunity.services.analysis import get_setting
from opportunity.services.case_access import is_case_effective, is_case_retrievable, sanitize_case_value
from opportunity.services.knowledge_metadata import merge_case_bia_meta
from common.utils.shared_resource_auth import filter_authorized_ids


CASE_ACTION_TRANSITIONS = {
    'SUBMIT_REVIEW': ({CaseStatus.DRAFT, CaseStatus.REJECTED}, CaseStatus.PENDING_REVIEW),
    'APPROVE': ({CaseStatus.PENDING_REVIEW}, CaseStatus.APPROVED),
    'REJECT': ({CaseStatus.PENDING_REVIEW}, CaseStatus.REJECTED),
    'PUBLISH': ({CaseStatus.APPROVED, CaseStatus.OFFLINE}, CaseStatus.PUBLISHED),
    'OFFLINE': ({CaseStatus.PUBLISHED}, CaseStatus.OFFLINE),
    'ARCHIVE': ({CaseStatus.APPROVED, CaseStatus.REJECTED, CaseStatus.OFFLINE}, CaseStatus.ARCHIVED),
}
CASE_BINDABLE_STATUSES = {
    CaseStatus.DRAFT, CaseStatus.REJECTED, CaseStatus.APPROVED, CaseStatus.OFFLINE,
}

# A document is considered parsed when its source synchronisation and optional
# tokenisation tasks are no longer waiting/running/failed.  ``n`` (ignored) is
# the normal state for tasks that are not enabled for a document, so it is
# intentionally accepted here.  Embedding success is the readiness signal for
# a source document; publication and recall keep their existing rules.
_CASE_DOCUMENT_BLOCKING_STATES = {
    State.PENDING,
    State.STARTED,
    State.FAILURE,
    State.REVOKE,
    State.REVOKED,
}


def is_case_document_parsed(document) -> bool:
    """Return whether a document is usable as a case source.

    The helper accepts a lightweight object as well as a ``Document`` model so
    that the status contract can be tested without a database.  No document
    content or status metadata is exposed to callers.
    """
    if not getattr(document, 'is_active', False):
        return False
    try:
        if int(getattr(document, 'char_length', 0) or 0) <= 0:
            return False
    except (TypeError, ValueError):
        return False
    status = Status(getattr(document, 'status', '') or '')
    # A parsed document has completed vector preparation in MaxKB's status
    # contract (available case sources are observed as ``nnn2``).  ``nnnn``
    # is the untouched document default and must not be selectable.
    if status[TaskType.EMBEDDING] != State.SUCCESS:
        return False
    return all(status[task_type] not in _CASE_DOCUMENT_BLOCKING_STATES for task_type in (
        TaskType.SYNC,
        TaskType.TOKENIZE,
    ))


class CaseWriteSerializer(serializers.Serializer):
    code = serializers.CharField(required=True, max_length=64)
    name = serializers.CharField(required=True, max_length=128)
    industry = serializers.CharField(required=False, allow_blank=True, default='', max_length=128)
    customer_type = serializers.CharField(required=False, allow_blank=True, default='', max_length=128)
    scenario = serializers.CharField(required=False, allow_blank=True, default='')
    pain_points = serializers.ListField(child=serializers.CharField(), required=False, default=list)
    project_scale = serializers.JSONField(required=False, default=dict)
    implementation_conditions = serializers.ListField(child=serializers.CharField(), required=False, default=list)
    implementation_process = serializers.CharField(required=False, allow_blank=True, default='')
    outcomes = serializers.ListField(child=serializers.CharField(), required=False, default=list)
    applicability_boundary = serializers.CharField(required=False, allow_blank=True, default='')
    sensitivity_level = serializers.ChoiceField(
        choices=SensitivityLevel.choices, required=False, default=SensitivityLevel.INTERNAL,
    )
    access_scope = serializers.ChoiceField(
        choices=CaseAccessScope.choices, required=False, default=CaseAccessScope.WORKSPACE,
    )
    owner_department_id = serializers.UUIDField(required=False, allow_null=True)
    authorized_department_ids = serializers.ListField(
        child=serializers.UUIDField(), required=False, default=list,
    )
    authorized_user_ids = serializers.ListField(
        child=serializers.CharField(max_length=128), required=False, default=list,
    )
    product_codes = serializers.ListField(
        child=serializers.CharField(max_length=64), required=True, allow_empty=False,
    )
    primary_product_code = serializers.CharField(required=False, allow_null=True, allow_blank=True, max_length=64)
    effective_from = serializers.DateTimeField(required=False, allow_null=True)
    effective_to = serializers.DateTimeField(required=False, allow_null=True)
    # New registration binds an existing parsed case document in the same
    # transaction.  ``allow_null`` keeps the legacy edit endpoint backwards
    # compatible when a document is not being replaced.
    document_id = serializers.UUIDField(required=False, allow_null=True)
    document_version = serializers.CharField(required=False, allow_blank=True, default='1.0', max_length=64)
    allow_download = serializers.BooleanField(required=False, default=False)
    meta = serializers.JSONField(required=False)

    def validate(self, attrs):
        effective_from = attrs.get('effective_from')
        effective_to = attrs.get('effective_to')
        if effective_from and effective_to and effective_to <= effective_from:
            raise serializers.ValidationError({'effective_to': '失效时间必须晚于生效时间'})
        primary = attrs.get('primary_product_code')
        if primary and primary not in attrs.get('product_codes', []):
            raise serializers.ValidationError({'primary_product_code': '主产品必须包含在关联产品中'})
        if attrs.get('access_scope') == CaseAccessScope.DEPARTMENT and not (
            attrs.get('owner_department_id') or attrs.get('authorized_department_ids')
        ):
            raise serializers.ValidationError({'authorized_department_ids': '部门范围案例必须配置归属或授权部门'})
        return attrs


class CaseActionSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=tuple(CASE_ACTION_TRANSITIONS.keys()))
    comment = serializers.CharField(required=False, allow_blank=True, default='', max_length=1024)


class CaseDocumentBindingRequest(serializers.Serializer):
    document_version = serializers.CharField(required=False, allow_blank=True, default='1.0', max_length=64)
    allow_download = serializers.BooleanField(required=False, default=False)


def _active_product_mappings(case):
    return QuerySet(CaseProductMapping).select_related('product').filter(case=case, is_active=True).order_by(
        '-is_primary', 'product__code',
    )


def _case_to_dict(case: CaseProfile, sanitize=False, include_access=True):
    products = [
        {
            'id': str(item.product_id),
            'code': item.product.code,
            'name': item.product.name,
            'product_version': item.product_version,
            'is_primary': item.is_primary,
        }
        for item in _active_product_mappings(case)
    ]
    documents = [
        {
            'id': str(item.id),
            'knowledge_id': str(item.knowledge_id),
            'document_id': str(item.document_id),
            'document_version': item.document_version,
            'is_active': item.is_active,
        }
        for item in QuerySet(CaseDocumentMapping).filter(case=case, is_active=True).order_by('create_time')
    ]
    result = {
        'id': str(case.id),
        'workspace_id': case.workspace_id,
        'code': case.code,
        'name': case.name,
        'industry': case.industry,
        'customer_type': case.customer_type,
        'scenario': case.scenario,
        'pain_points': case.pain_points or [],
        'project_scale': case.project_scale or {},
        'implementation_conditions': case.implementation_conditions or [],
        'implementation_process': case.implementation_process,
        'outcomes': case.outcomes or [],
        'applicability_boundary': case.applicability_boundary,
        'status': case.status,
        'desensitization_status': case.desensitization_status,
        'sensitivity_level': case.sensitivity_level,
        'access_scope': case.access_scope,
        'owner_department_id': str(case.owner_department_id) if case.owner_department_id else None,
        'creator_user_id': case.creator_user_id,
        'reviewer_user_id': case.reviewer_user_id,
        'reviewed_at': model_time(case.reviewed_at),
        'review_comment': case.review_comment,
        'effective_from': model_time(case.effective_from),
        'effective_to': model_time(case.effective_to),
        'products': products,
        'documents': documents,
        'meta': case.meta or {},
        'create_time': model_time(case.create_time),
        'update_time': model_time(case.update_time),
    }
    if include_access:
        result['authorized_department_ids'] = [str(item) for item in (case.authorized_department_ids or [])]
        result['authorized_user_ids'] = [str(item) for item in (case.authorized_user_ids or [])]
    if sanitize:
        result = sanitize_case_value(result)
        result.pop('authorized_department_ids', None)
        result.pop('authorized_user_ids', None)
        result.pop('review_comment', None)
    return result


def _sync_product_mappings(case: CaseProfile, product_codes, primary_product_code=None):
    product_codes = list(dict.fromkeys(product_codes or []))
    primary_product_code = primary_product_code or product_codes[0]
    products = list(QuerySet(ProductProfile).filter(
        workspace_id=case.workspace_id,
        code__in=product_codes,
        status=ProductStatus.ACTIVE,
    ))
    if len(products) != len(product_codes):
        existing_codes = {item.code for item in products}
        missing = [code for code in product_codes if code not in existing_codes]
        raise AppApiException(500, f'关联产品不存在或未启用：{",".join(missing)}')
    QuerySet(CaseProductMapping).filter(case=case).exclude(product__code__in=product_codes).update(is_active=False)
    for product in products:
        version = str((product.meta or {}).get('version') or '1.0')
        CaseProductMapping.objects.update_or_create(
            workspace_id=case.workspace_id,
            case=case,
            product=product,
            defaults={
                'product_version': version,
                'is_primary': product.code == primary_product_code,
                'is_active': True,
            },
        )


def _sync_case_documents(case: CaseProfile):
    publish_status = 'published' if case.status == CaseStatus.PUBLISHED else 'offline'
    mappings = QuerySet(CaseDocumentMapping).filter(case=case, is_active=True)
    documents = QuerySet(Document).filter(id__in=[item.document_id for item in mappings])
    for document in documents:
        bia = dict((document.meta or {}).get('bia') or {})
        bia.update({
            'publish_status': publish_status,
            'desensitization_status': case.desensitization_status,
            'sensitivity_level': case.sensitivity_level,
            'access_scope': case.access_scope,
            'effective_from': model_time(case.effective_from),
            'effective_to': model_time(case.effective_to),
        })
        document.meta = {**(document.meta or {}), 'bia': bia}
        document.save(update_fields=['meta', 'update_time'])


def _case_document_version(document):
    """Read only the version field needed by the management picker."""
    return str(((document.meta or {}).get('bia') or {}).get('document_version') or '1.0')


def _validate_case_document(workspace_id, document_id, case=None, user_id=None, for_update=False):
    """Validate a case document while keeping the check inside the caller's transaction.

    ``for_update`` is used by every mutating path.  The row lock and the
    occupied re-check are deliberately in one atomic block so two managers
    cannot bind the same source document to different cases concurrently.
    """
    setting = get_setting(workspace_id)
    if not setting.case_knowledge_id:
        raise AppApiException(500, '请先配置案例知识库')
    knowledge = require_knowledge(workspace_id, setting.case_knowledge_id)
    knowledge_id = str(knowledge.id)
    if user_id is not None:
        authorized = filter_authorized_ids('knowledge', [knowledge_id], workspace_id, user_id=user_id)
        if knowledge_id not in {str(item) for item in authorized}:
            raise AppApiException(403, '无权访问当前案例知识库')

    documents = QuerySet(Document).select_related('knowledge')
    if for_update:
        documents = documents.select_for_update()
    document = documents.filter(id=document_id, is_active=True).first()
    if document is None or str(document.knowledge.workspace_id) != str(workspace_id):
        raise AppApiException(500, '文档不存在或不属于当前工作空间')
    if str(document.knowledge_id) != knowledge_id:
        raise AppApiException(500, '文档必须属于当前案例知识库')
    if not is_case_document_parsed(document):
        raise AppApiException(500, '文档尚未解析完成，不能登记案例')

    occupied = QuerySet(CaseDocumentMapping).filter(
        workspace_id=workspace_id,
        document_id=document.id,
        is_active=True,
    )
    if case is not None:
        occupied = occupied.exclude(case=case)
    if occupied.exists():
        raise AppApiException(500, '该文档已绑定其他案例')
    return document


def _case_document_candidate(document):
    """Return safe metadata for the registration document picker."""
    return {
        'id': str(document.id),
        'name': document.name,
        'knowledge_id': str(document.knowledge_id),
        'status': document.status,
        'parsed': is_case_document_parsed(document),
        'is_bound': False,
        'document_version': _case_document_version(document),
        'update_time': model_time(document.update_time),
    }


def list_available_case_documents(workspace_id, user_id=None, case_id=None):
    """List parsed, active and unoccupied documents in the configured KB."""
    setting = get_setting(workspace_id)
    if not setting.case_knowledge_id:
        return []
    knowledge = require_knowledge(workspace_id, setting.case_knowledge_id)
    knowledge_id = str(knowledge.id)
    authorized = filter_authorized_ids('knowledge', [knowledge_id], workspace_id, user_id=user_id)
    if knowledge_id not in {str(item) for item in authorized}:
        return []

    owned_ids = set()
    if case_id:
        owned_ids = {
            str(item) for item in QuerySet(CaseDocumentMapping).filter(
                workspace_id=workspace_id,
                case_id=case_id,
                is_active=True,
            ).values_list('document_id', flat=True)
        }
    bound_query = QuerySet(CaseDocumentMapping).filter(
        workspace_id=workspace_id,
        knowledge_id=knowledge.id,
        is_active=True,
    )
    bound_ids = {str(item) for item in bound_query.values_list('document_id', flat=True)}
    queryset = QuerySet(Document).filter(
        knowledge_id=knowledge.id,
        is_active=True,
    ).order_by('name', 'id')
    result = []
    for document in queryset:
        document_id = str(document.id)
        if document_id in bound_ids and document_id not in owned_ids:
            # A new registration cannot use another case's source.  An edit
            # may keep its own existing source and will see it as bound.
            continue
        if not is_case_document_parsed(document):
            continue
        item = _case_document_candidate(document)
        item['is_bound'] = document_id in bound_ids
        result.append(item)
    return result


def _bind_case_document(case, document, data, workspace_id):
    """Write the BIA metadata and active mapping for a validated document."""
    product_codes = [item.product.code for item in _active_product_mappings(case)]
    if not product_codes:
        raise AppApiException(500, '案例必须先关联至少一个有效产品')
    reset_review = case.status in (CaseStatus.APPROVED, CaseStatus.OFFLINE)
    if reset_review:
        case.status = CaseStatus.DRAFT
        case.desensitization_status = DesensitizationStatus.PENDING
        case.reviewer_user_id = None
        case.reviewed_at = None
        case.review_comment = ''
        case.save()
        _sync_case_documents(case)

    bia = {
        'schema_version': '1.0',
        'case_code': case.code,
        'case_name': case.name,
        'product_codes': product_codes,
        'industry': case.industry,
        'scenario': case.scenario,
        'document_type': 'case_profile',
        'document_version': data.get('document_version') or '1.0',
        'publish_status': 'draft',
        'desensitization_status': case.desensitization_status,
        'sensitivity_level': case.sensitivity_level,
        'access_scope': case.access_scope,
        'effective_from': model_time(case.effective_from),
        'effective_to': model_time(case.effective_to),
        'allow_download': bool(data.get('allow_download', False)),
    }
    document.meta = merge_case_bia_meta(document.meta or {}, bia)
    document.save(update_fields=['meta', 'update_time'])
    mapping, _ = CaseDocumentMapping.objects.update_or_create(
        workspace_id=workspace_id,
        case=case,
        document_id=document.id,
        defaults={
            'knowledge_id': document.knowledge_id,
            'document_version': bia['document_version'],
            'is_active': True,
        },
    )
    return mapping


class CaseSerializer(serializers.Serializer):
    workspace_id = serializers.CharField(required=True)
    user_id = serializers.CharField(required=False, allow_null=True)
    is_manager = serializers.BooleanField(required=False, default=False)
    # API registrations opt in explicitly; bootstrap and legacy internal
    # callers can still create a draft and bind a document in a later step.
    require_document = serializers.BooleanField(required=False, default=False)

    def list(self, filters=None):
        self.is_valid(raise_exception=True)
        filters = filters or {}
        queryset = QuerySet(CaseProfile).select_related('owner_department').filter(
            workspace_id=self.validated_data['workspace_id'],
        ).order_by('-update_time', 'code')
        if filters.get('status'):
            queryset = queryset.filter(status=filters['status'])
        if filters.get('industry'):
            queryset = queryset.filter(industry__icontains=filters['industry'])
        if filters.get('name'):
            queryset = queryset.filter(name__icontains=filters['name'])
        if self.validated_data.get('is_manager'):
            return [_case_to_dict(item) for item in queryset]
        return [
            _case_to_dict(item, sanitize=True, include_access=False)
            for item in queryset
            if is_case_retrievable(item, user_id=self.validated_data.get('user_id'))
        ]

    def insert(self, instance: dict):
        self.is_valid(raise_exception=True)
        serializer = CaseWriteSerializer(data=instance)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        workspace_id = self.validated_data['workspace_id']
        document_id = data.get('document_id')
        if self.validated_data.get('require_document') and not document_id:
            raise AppApiException(500, '登记案例必须选择已解析的案例文档')
        if QuerySet(CaseProfile).filter(workspace_id=workspace_id, code=data['code']).exists():
            raise AppApiException(500, '案例编码已存在')
        owner_department = require_department(
            workspace_id, department_id=data.get('owner_department_id'),
        ) if data.get('owner_department_id') else None
        with transaction.atomic():
            case = CaseProfile.objects.create(
                workspace_id=workspace_id,
                code=data['code'],
                name=data['name'],
                industry=data.get('industry') or '',
                customer_type=data.get('customer_type') or '',
                scenario=data.get('scenario') or '',
                pain_points=data.get('pain_points') or [],
                project_scale=data.get('project_scale') or {},
                implementation_conditions=data.get('implementation_conditions') or [],
                implementation_process=data.get('implementation_process') or '',
                outcomes=data.get('outcomes') or [],
                applicability_boundary=data.get('applicability_boundary') or '',
                sensitivity_level=data.get('sensitivity_level') or SensitivityLevel.INTERNAL,
                access_scope=data.get('access_scope') or CaseAccessScope.WORKSPACE,
                owner_department=owner_department,
                authorized_department_ids=[str(item) for item in data.get('authorized_department_ids') or []],
                authorized_user_ids=[str(item) for item in data.get('authorized_user_ids') or []],
                creator_user_id=str(self.validated_data.get('user_id')),
                effective_from=data.get('effective_from'),
                effective_to=data.get('effective_to'),
                meta=data.get('meta') or {},
            )
            _sync_product_mappings(case, data['product_codes'], data.get('primary_product_code'))
            if document_id:
                # Lock and re-check occupancy after the case/product rows are
                # created; any failure rolls the complete registration back.
                document = _validate_case_document(
                    workspace_id,
                    document_id,
                    case=case,
                    user_id=self.validated_data.get('user_id'),
                    for_update=True,
                )
                _bind_case_document(case, document, data, workspace_id)
        return _case_to_dict(case)


class CaseOperateSerializer(serializers.Serializer):
    workspace_id = serializers.CharField(required=True)
    case_id = serializers.UUIDField(required=True)
    user_id = serializers.CharField(required=False, allow_null=True)
    is_manager = serializers.BooleanField(required=False, default=False)

    def one(self):
        self.is_valid(raise_exception=True)
        case = require_case(self.validated_data['workspace_id'], case_id=self.validated_data['case_id'],
                            allow_archived=True)
        is_manager = self.validated_data.get('is_manager', False)
        if not is_manager and not is_case_retrievable(case, user_id=self.validated_data.get('user_id')):
            raise AppApiException(403, '无权访问该案例')
        return _case_to_dict(case, sanitize=not is_manager, include_access=is_manager)

    def update(self, instance: dict):
        self.is_valid(raise_exception=True)
        serializer = CaseWriteSerializer(data=instance)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        workspace_id = self.validated_data['workspace_id']
        case = require_case(workspace_id, case_id=self.validated_data['case_id'], allow_archived=True)
        if case.status not in (CaseStatus.DRAFT, CaseStatus.REJECTED, CaseStatus.APPROVED):
            raise AppApiException(500, '当前状态不允许编辑，请先下线或退回案例')
        duplicate = QuerySet(CaseProfile).filter(workspace_id=workspace_id, code=data['code']).exclude(id=case.id)
        if duplicate.exists():
            raise AppApiException(500, '案例编码已存在')
        owner_department = require_department(
            workspace_id, department_id=data.get('owner_department_id'),
        ) if data.get('owner_department_id') else None
        with transaction.atomic():
            for field in (
                'code', 'name', 'industry', 'customer_type', 'scenario', 'pain_points', 'project_scale',
                'implementation_conditions', 'implementation_process', 'outcomes', 'applicability_boundary',
                'sensitivity_level', 'access_scope', 'effective_from', 'effective_to',
            ):
                setattr(case, field, data.get(field))
            case.owner_department = owner_department
            case.authorized_department_ids = [str(item) for item in data.get('authorized_department_ids') or []]
            case.authorized_user_ids = [str(item) for item in data.get('authorized_user_ids') or []]
            case.meta = data.get('meta') if data.get('meta') is not None else case.meta
            if case.status in (CaseStatus.APPROVED, CaseStatus.REJECTED):
                case.status = CaseStatus.DRAFT
                case.desensitization_status = DesensitizationStatus.PENDING
                case.reviewer_user_id = None
                case.reviewed_at = None
                case.review_comment = ''
            case.save()
            _sync_product_mappings(case, data['product_codes'], data.get('primary_product_code'))
            if data.get('document_id'):
                document = _validate_case_document(
                    workspace_id,
                    data['document_id'],
                    case=case,
                    user_id=self.validated_data.get('user_id'),
                    for_update=True,
                )
                _bind_case_document(case, document, data, workspace_id)
        return _case_to_dict(case)

    def action(self, instance: dict):
        self.is_valid(raise_exception=True)
        serializer = CaseActionSerializer(data=instance)
        serializer.is_valid(raise_exception=True)
        action = serializer.validated_data['action']
        comment = serializer.validated_data.get('comment') or ''
        case = require_case(self.validated_data['workspace_id'], case_id=self.validated_data['case_id'],
                            allow_archived=True)
        allowed_statuses, target_status = CASE_ACTION_TRANSITIONS[action]
        if case.status not in allowed_statuses:
            raise AppApiException(500, f'案例状态不允许执行 {action}')
        if action == 'PUBLISH':
            if case.desensitization_status != DesensitizationStatus.PASSED:
                raise AppApiException(500, '案例未通过脱敏审核，不能发布')
            if not _active_product_mappings(case).exists():
                raise AppApiException(500, '案例未关联有效产品，不能发布')
            if not QuerySet(CaseDocumentMapping).filter(case=case, is_active=True).exists():
                raise AppApiException(500, '案例未绑定资料，不能发布')
            if not is_case_effective(case):
                raise AppApiException(500, '案例未处于有效期，不能发布')
        case.status = target_status
        if action == 'SUBMIT_REVIEW':
            case.desensitization_status = DesensitizationStatus.PENDING
            case.reviewer_user_id = None
            case.reviewed_at = None
        elif action == 'APPROVE':
            case.desensitization_status = DesensitizationStatus.PASSED
            case.reviewer_user_id = str(self.validated_data.get('user_id'))
            case.reviewed_at = timezone.now()
        elif action == 'REJECT':
            case.desensitization_status = DesensitizationStatus.REJECTED
            case.reviewer_user_id = str(self.validated_data.get('user_id'))
            case.reviewed_at = timezone.now()
        case.review_comment = comment
        case.save()
        _sync_case_documents(case)
        return _case_to_dict(case)


class CaseDocumentBindingSerializer(serializers.Serializer):
    workspace_id = serializers.CharField(required=True)
    case_id = serializers.UUIDField(required=True)
    document_id = serializers.UUIDField(required=True)

    def bind(self, instance: dict):
        self.is_valid(raise_exception=True)
        request_serializer = CaseDocumentBindingRequest(data=instance)
        request_serializer.is_valid(raise_exception=True)
        data = request_serializer.validated_data
        workspace_id = self.validated_data['workspace_id']
        case = require_case(workspace_id, case_id=self.validated_data['case_id'])
        if case.status not in CASE_BINDABLE_STATUSES:
            raise AppApiException(500, '当前状态不允许绑定资料；已发布案例请先下线')
        with transaction.atomic():
            document = _validate_case_document(
                workspace_id,
                self.validated_data['document_id'],
                case=case,
                for_update=True,
            )
            mapping = _bind_case_document(case, document, data, workspace_id)
        return {
            'mapping_id': str(mapping.id),
            'case_id': str(case.id),
            'document_id': str(document.id),
            'meta': document.meta,
        }
