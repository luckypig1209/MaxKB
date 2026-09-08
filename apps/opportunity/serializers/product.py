# coding=utf-8
"""
    @project: MaxKB
    @Author：bia
    @file： product.py
    @date：2026/9/3
    @desc: 产品主数据与资料绑定
"""
from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone
from rest_framework import serializers

from common.exception.app_exception import AppApiException
from opportunity.models import (
    MappingRole,
    OpportunityAnalysis,
    ProductDepartmentMapping,
    ProductProfile,
    ProductStatus,
)
from opportunity.serializers.common import (
    model_time,
    require_department,
    require_document,
    require_knowledge,
    require_product,
)
from opportunity.services.analysis import get_setting
from opportunity.services.department import current_owner_queryset, is_mapping_effective, resolve_department
from opportunity.services.knowledge_metadata import merge_bia_meta


class ProductWriteSerializer(serializers.Serializer):
    code = serializers.CharField(required=True, max_length=64)
    name = serializers.CharField(required=True, max_length=128)
    aliases = serializers.ListField(child=serializers.CharField(max_length=128), required=False, default=list)
    product_line = serializers.CharField(required=False, allow_blank=True, default='')
    description = serializers.CharField(required=False, allow_blank=True, default='')
    status = serializers.ChoiceField(choices=ProductStatus.choices, required=False)
    meta = serializers.JSONField(required=False)
    owner_department_id = serializers.UUIDField(required=False, allow_null=True)
    owner_user_id = serializers.CharField(required=False, allow_null=True, allow_blank=True)


class DocumentBindingSerializer(serializers.Serializer):
    schema_version = serializers.CharField(required=False, default='1.0')
    asset_type = serializers.ChoiceField(choices=('product',), required=False, default='product')
    product_code = serializers.CharField(required=True, max_length=64)
    product_name = serializers.CharField(required=False, allow_blank=True)
    product_line = serializers.CharField(required=False, allow_blank=True)
    document_type = serializers.CharField(required=False, allow_blank=True, default='explanation')
    document_version = serializers.CharField(required=False, allow_blank=True, default='1.0')
    publish_status = serializers.ChoiceField(choices=('draft', 'published', 'offline'), required=False,
                                             default='published')
    effective_from = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    effective_to = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    owner_department_code = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    allow_download = serializers.BooleanField(required=False, default=False)


def product_to_dict(product: ProductProfile):
    department = resolve_department(product)
    return {
        'id': str(product.id),
        'workspace_id': product.workspace_id,
        'code': product.code,
        'name': product.name,
        'aliases': product.aliases or [],
        'product_line': product.product_line,
        'description': product.description,
        'status': product.status,
        'meta': product.meta or {},
        'department': department,
        'create_time': model_time(product.create_time),
        'update_time': model_time(product.update_time),
    }


def _ensure_single_owner(product, mapping_id=None):
    queryset = current_owner_queryset(product)
    if mapping_id:
        queryset = queryset.exclude(id=mapping_id)
    effective = [item for item in queryset if is_mapping_effective(item)]
    if effective:
        raise AppApiException(500, '同一产品只能有一条当前有效的主责部门映射')


def _sync_owner_mapping(product: ProductProfile, owner_department_id, owner_user_id):
    if not owner_department_id:
        return
    department = require_department(product.workspace_id, department_id=owner_department_id)
    existing = current_owner_queryset(product).first()
    if existing:
        existing.department = department
        existing.owner_user_id = owner_user_id or None
        existing.is_active = True
        existing.effective_from = existing.effective_from or timezone.now()
        existing.effective_to = None
        existing.save()
        return
    mapping = ProductDepartmentMapping(
        workspace_id=product.workspace_id,
        product=product,
        department=department,
        role=MappingRole.OWNER,
        owner_user_id=owner_user_id or None,
        effective_from=timezone.now(),
        is_active=True,
    )
    mapping.save()
    _ensure_single_owner(product, mapping_id=mapping.id)


class ProductSerializer(serializers.Serializer):
    workspace_id = serializers.CharField(required=True)

    def list(self):
        self.is_valid(raise_exception=True)
        queryset = QuerySet(ProductProfile).filter(workspace_id=self.validated_data['workspace_id']).order_by('code')
        return [product_to_dict(item) for item in queryset]

    def insert(self, instance: dict):
        self.is_valid(raise_exception=True)
        serializer = ProductWriteSerializer(data=instance)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        workspace_id = self.validated_data['workspace_id']
        if QuerySet(ProductProfile).filter(workspace_id=workspace_id, code=data['code']).exists():
            raise AppApiException(500, '产品编码已存在')
        with transaction.atomic():
            product = ProductProfile(
                workspace_id=workspace_id,
                code=data['code'],
                name=data['name'],
                aliases=data.get('aliases') or [],
                product_line=data.get('product_line') or '',
                description=data.get('description') or '',
                status=data.get('status') or ProductStatus.ACTIVE,
                meta=data.get('meta') or {},
            )
            product.save()
            _sync_owner_mapping(product, data.get('owner_department_id'), data.get('owner_user_id'))
        return product_to_dict(product)


class ProductOperateSerializer(serializers.Serializer):
    workspace_id = serializers.CharField(required=True)
    product_id = serializers.UUIDField(required=True)

    def one(self):
        self.is_valid(raise_exception=True)
        product = require_product(self.validated_data['workspace_id'], product_id=self.validated_data['product_id'],
                                  allow_inactive=True)
        return product_to_dict(product)

    def update(self, instance: dict):
        self.is_valid(raise_exception=True)
        serializer = ProductWriteSerializer(data=instance)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        workspace_id = self.validated_data['workspace_id']
        product = require_product(workspace_id, product_id=self.validated_data['product_id'], allow_inactive=True)
        exists = QuerySet(ProductProfile).filter(workspace_id=workspace_id, code=data['code']).exclude(
            id=product.id).exists()
        if exists:
            raise AppApiException(500, '产品编码已存在')
        with transaction.atomic():
            product.code = data['code']
            product.name = data['name']
            product.aliases = data.get('aliases') or []
            product.product_line = data.get('product_line') or ''
            product.description = data.get('description') or ''
            product.status = data.get('status') or product.status
            product.meta = data.get('meta') if data.get('meta') is not None else product.meta
            product.save()
            _sync_owner_mapping(product, data.get('owner_department_id'), data.get('owner_user_id'))
        return product_to_dict(product)

    def delete(self):
        self.is_valid(raise_exception=True)
        workspace_id = self.validated_data['workspace_id']
        product = require_product(workspace_id, product_id=self.validated_data['product_id'], allow_inactive=True)
        referenced = QuerySet(OpportunityAnalysis).filter(
            workspace_id=workspace_id,
            confirmed_product_code=product.code,
        ).exists()
        if referenced:
            product.status = ProductStatus.INACTIVE
            product.save(update_fields=['status', 'update_time'])
            return True
        product.status = ProductStatus.INACTIVE
        product.save(update_fields=['status', 'update_time'])
        return True


class ProductDocumentBindingSerializer(serializers.Serializer):
    workspace_id = serializers.CharField(required=True)
    product_id = serializers.UUIDField(required=True)
    document_id = serializers.UUIDField(required=True)

    def bind(self, instance: dict):
        self.is_valid(raise_exception=True)
        serializer = DocumentBindingSerializer(data=instance)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        workspace_id = self.validated_data['workspace_id']
        product = require_product(workspace_id, product_id=self.validated_data['product_id'])
        document = require_document(workspace_id, self.validated_data['document_id'])
        setting = get_setting(workspace_id)
        if not setting.product_knowledge_id:
            raise AppApiException(500, '请先配置产品知识库')
        require_knowledge(workspace_id, setting.product_knowledge_id)
        if str(document.knowledge_id) != str(setting.product_knowledge_id):
            raise AppApiException(500, '文档必须属于当前产品知识库')
        if data.get('product_code') != product.code:
            raise AppApiException(500, '资料产品编码与产品档案不一致')
        if data.get('asset_type') not in (None, 'product'):
            raise AppApiException(500, '第一阶段仅支持产品资料')
        bia = {
            **data,
            'product_code': product.code,
            'product_name': data.get('product_name') or product.name,
            'product_line': data.get('product_line') or product.product_line,
            'asset_type': 'product',
        }
        document.meta = merge_bia_meta(document.meta or {}, bia)
        document.save(update_fields=['meta', 'update_time'])
        return {
            'document_id': str(document.id),
            'product_id': str(product.id),
            'meta': document.meta,
        }
