# coding=utf-8
"""
    @project: MaxKB
    @Author：bia
    @file： common.py
    @date：2026/9/3
    @desc: 序列化公共方法
"""
from django.db.models import QuerySet
from django.utils import timezone

from common.exception.app_exception import AppApiException
from knowledge.models import Document, Knowledge
from models_provider.models import Model
from opportunity.models import CaseProfile, DepartmentProfile, DepartmentStatus, ProductProfile, ProductStatus


def model_time(value):
    """Serialize a stored UTC time as ISO 8601 in the business timezone."""
    if not value:
        return None
    if timezone.is_naive(value):
        value = timezone.make_aware(value, timezone.get_default_timezone())
    return timezone.localtime(value, timezone.get_default_timezone()).isoformat()


def require_model(workspace_id, model_id, model_type=None):
    if not model_id:
        return None
    queryset = QuerySet(Model).filter(id=model_id, workspace_id=workspace_id)
    model = queryset.first()
    if model is None:
        raise AppApiException(500, '模型不存在或不属于当前工作空间')
    if model_type and model.model_type != model_type:
        raise AppApiException(500, f'模型类型必须为 {model_type}')
    return model


def require_knowledge(workspace_id, knowledge_id):
    if not knowledge_id:
        return None
    knowledge = QuerySet(Knowledge).filter(id=knowledge_id, workspace_id=workspace_id).first()
    if knowledge is None:
        raise AppApiException(500, '知识库不存在或不属于当前工作空间')
    return knowledge


def require_document(workspace_id, document_id):
    document = QuerySet(Document).select_related('knowledge').filter(id=document_id).first()
    if document is None or str(document.knowledge.workspace_id) != str(workspace_id):
        raise AppApiException(500, '文档不存在或不属于当前工作空间')
    return document


def require_product(workspace_id, product_id=None, code=None, allow_inactive=False):
    queryset = QuerySet(ProductProfile).filter(workspace_id=workspace_id)
    if product_id:
        queryset = queryset.filter(id=product_id)
    if code:
        queryset = queryset.filter(code=code)
    product = queryset.first()
    if product is None:
        raise AppApiException(500, '产品不存在')
    if not allow_inactive and product.status == ProductStatus.INACTIVE:
        raise AppApiException(500, '产品已停用')
    return product


def require_department(workspace_id, department_id=None, code=None, allow_inactive=False):
    queryset = QuerySet(DepartmentProfile).filter(workspace_id=workspace_id)
    if department_id:
        queryset = queryset.filter(id=department_id)
    if code:
        queryset = queryset.filter(code=code)
    department = queryset.first()
    if department is None:
        raise AppApiException(500, '部门不存在')
    if not allow_inactive and department.status == DepartmentStatus.INACTIVE:
        raise AppApiException(500, '部门已停用')
    return department


def require_case(workspace_id, case_id=None, code=None, allow_archived=False):
    queryset = QuerySet(CaseProfile).filter(workspace_id=workspace_id)
    if case_id:
        queryset = queryset.filter(id=case_id)
    if code:
        queryset = queryset.filter(code=code)
    case = queryset.first()
    if case is None:
        raise AppApiException(500, '案例不存在')
    if not allow_archived and case.status == 'ARCHIVED':
        raise AppApiException(500, '案例已归档')
    return case
