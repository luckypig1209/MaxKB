import json
import os
import sys
from pathlib import Path

from django.db import transaction
from django.db.models import QuerySet

from knowledge.models import Document
from opportunity.models import (
    CaseDocumentMapping,
    CaseProfile,
    CaseStatus,
    DepartmentProfile,
    DepartmentStatus,
    ProductProfile,
    ProductStatus,
)
from opportunity.serializers.case import (
    CaseDocumentBindingSerializer,
    CaseOperateSerializer,
    CaseSerializer,
)
from opportunity.serializers.department import DepartmentOperateSerializer, DepartmentSerializer
from opportunity.serializers.product import (
    ProductDocumentBindingSerializer,
    ProductOperateSerializer,
    ProductSerializer,
)
from opportunity.services.analysis import get_setting
from users.models import User


class BootstrapPrerequisiteError(Exception):
    pass


workspace_id = os.environ.get('BIA_WORKSPACE_ID', 'default')
bootstrap_dir = Path(os.environ.get('BIA_BOOTSTRAP_DIR', '/tmp/bia-phase1-bootstrap'))


def load_json(name):
    path = bootstrap_dir / 'phase1' / name
    if not path.is_file():
        raise BootstrapPrerequisiteError(f'初始化数据文件不存在：{path}')
    return json.loads(path.read_text(encoding='utf-8'))


def require_document(knowledge_id, document_name):
    document = QuerySet(Document).select_related('knowledge').filter(
        knowledge__workspace_id=workspace_id,
        knowledge_id=knowledge_id,
        name=document_name,
    ).first()
    if document is None:
        raise BootstrapPrerequisiteError(
            f'知识库缺少文档：{document_name}。请先完成18份资料导入和向量化。'
        )
    return document


def department_payload(item, existing_meta=None):
    # Bootstrap owns the catalog/source fields but must not erase unrelated
    # department metadata added by operators or a previous release.
    meta = dict(existing_meta or {})
    meta['source'] = 'phase1_catalog'
    if item.get('source_name'):
        # Keep the authority's original department spelling for audit/reconciliation.
        meta['source_name'] = item['source_name']
    return {
        'code': item['code'],
        'name': item['name'],
        'status': DepartmentStatus.ACTIVE,
        'meta': meta,
    }


def product_payload(item, department, existing_meta=None):
    # Preserve product extensions (for example product version) while
    # refreshing the catalog-owned support contact and source fields.
    meta = dict(existing_meta or {})
    meta['source'] = 'phase1_catalog'
    if item.get('support'):
        # Support contact data is stored in the restricted product metadata.  The
        # product serializer strips this key for non-manager API readers.
        meta['support'] = item['support']
    return {
        'code': item['code'],
        'name': item['name'],
        'aliases': item.get('aliases') or [],
        'product_line': item.get('product_line') or '',
        'description': item.get('description') or '',
        'status': ProductStatus.ACTIVE,
        'owner_department_id': str(department.id),
        'meta': meta,
    }


def case_payload(item, department):
    return {
        'code': item['code'],
        'name': item['name'],
        'industry': item.get('industry') or '',
        'customer_type': item.get('customer_type') or '',
        'scenario': item.get('scenario') or '',
        'pain_points': item.get('pain_points') or [],
        'project_scale': item.get('project_scale') or {},
        'implementation_conditions': item.get('implementation_conditions') or [],
        'implementation_process': item.get('implementation_process') or '',
        'outcomes': item.get('outcomes') or [],
        'applicability_boundary': item.get('applicability_boundary') or '',
        'product_codes': item.get('product_codes') or [],
        'primary_product_code': item.get('primary_product_code'),
        'owner_department_id': str(department.id),
        'sensitivity_level': 'INTERNAL',
        'access_scope': 'WORKSPACE',
        'authorized_department_ids': [],
        'authorized_user_ids': [],
        'meta': {'source': 'phase1_demo'},
    }


def change_case_status(case, action, user_id, comment):
    CaseOperateSerializer(data={
        'workspace_id': workspace_id,
        'case_id': str(case.id),
        'user_id': user_id,
        'is_manager': True,
    }).action({'action': action, 'comment': comment})
    case.refresh_from_db()


def bootstrap():
    catalog = load_json('PHASE1_CATALOG.json')
    case_items = load_json('PHASE1_CASES.json')
    setting = get_setting(workspace_id)
    if not setting.product_knowledge_id or not setting.case_knowledge_id:
        raise BootstrapPrerequisiteError('请先在商机分析设置中配置产品知识库和案例知识库。')

    admin = QuerySet(User).filter(username='admin').first()
    if admin is None:
        raise BootstrapPrerequisiteError('未找到 admin 用户，无法登记案例创建人和审核人。')
    user_id = str(admin.id)

    stats = {
        'departments_created': 0,
        'products_created': 0,
        'products_total': len(catalog.get('products') or []),
        'products_knowledge_ready': 0,
        'products_knowledge_pending': 0,
        'product_documents_bound': 0,
        'cases_created': 0,
        'case_documents_bound': 0,
        'cases_published': 0,
    }

    with transaction.atomic():
        departments = {}
        for item in catalog.get('departments') or []:
            department = QuerySet(DepartmentProfile).filter(
                workspace_id=workspace_id, code=item['code'],
            ).first()
            if department is None:
                result = DepartmentSerializer(data={'workspace_id': workspace_id}).insert(
                    department_payload(item)
                )
                department = DepartmentProfile.objects.get(id=result['id'])
                stats['departments_created'] += 1
            else:
                DepartmentOperateSerializer(data={
                    'workspace_id': workspace_id,
                    'department_id': str(department.id),
                }).update(department_payload(item, department.meta))
                department.refresh_from_db()
            departments[item['code']] = department

        products = {}
        for item in catalog.get('products') or []:
            department = departments.get(item['department_code'])
            if department is None:
                raise BootstrapPrerequisiteError(f"产品缺少主责部门：{item['code']}")
            product = QuerySet(ProductProfile).filter(
                workspace_id=workspace_id, code=item['code'],
            ).first()
            payload = product_payload(item, department, product.meta if product else None)
            if product is None:
                result = ProductSerializer(data={'workspace_id': workspace_id}).insert(payload)
                product = ProductProfile.objects.get(id=result['id'])
                stats['products_created'] += 1
            else:
                ProductOperateSerializer(data={
                    'workspace_id': workspace_id,
                    'product_id': str(product.id),
                }).update(payload)
                product.refresh_from_db()
            products[item['code']] = product

            document_name = (item.get('document_name') or '').strip()
            if not document_name:
                # A catalog entry may be registered before its product material is
                # imported.  Keep the master data visible, but do not create a
                # binding or make it eligible for retrieval/recommendation.
                stats['products_knowledge_pending'] += 1
                continue

            document = require_document(setting.product_knowledge_id, document_name)
            ProductDocumentBindingSerializer(data={
                'workspace_id': workspace_id,
                'product_id': str(product.id),
                'document_id': str(document.id),
            }).bind({
                'schema_version': '1.0',
                'asset_type': 'product',
                'product_code': product.code,
                'product_name': product.name,
                'product_line': product.product_line,
                'document_type': 'product_profile',
                'document_version': '1.0',
                'publish_status': 'published',
                'owner_department_code': item['department_code'],
                'allow_download': True,
            })
            stats['products_knowledge_ready'] += 1
            stats['product_documents_bound'] += 1

        for item in case_items:
            department = departments.get(item['department_code'])
            if department is None:
                raise BootstrapPrerequisiteError(f"案例缺少主责部门：{item['code']}")
            document = require_document(setting.case_knowledge_id, item['document_name'])
            case = QuerySet(CaseProfile).filter(
                workspace_id=workspace_id, code=item['code'],
            ).first()
            payload = case_payload(item, department)

            if case is None:
                result = CaseSerializer(data={
                    'workspace_id': workspace_id,
                    'user_id': user_id,
                    'is_manager': True,
                    # Bootstrap creates the profile before repairing the
                    # legacy document binding below.
                    'require_document': False,
                }).insert(payload)
                case = CaseProfile.objects.get(id=result['id'])
                stats['cases_created'] += 1
            elif case.status == CaseStatus.ARCHIVED:
                raise BootstrapPrerequisiteError(f'案例已归档，无法自动初始化：{case.code}')
            elif case.status == CaseStatus.OFFLINE:
                # OFFLINE is bindable/publishable but the current domain API
                # intentionally does not allow editing it. Keep the existing
                # profile and repair its binding/lifecycle below.
                pass
            elif case.status != CaseStatus.PUBLISHED:
                if case.status == CaseStatus.PENDING_REVIEW:
                    change_case_status(case, 'APPROVE', user_id, '初始化流程临时完成审核')
                CaseOperateSerializer(data={
                    'workspace_id': workspace_id,
                    'case_id': str(case.id),
                    'user_id': user_id,
                    'is_manager': True,
                }).update(payload)
                case.refresh_from_db()

            mapping = QuerySet(CaseDocumentMapping).filter(
                workspace_id=workspace_id,
                case=case,
                document_id=document.id,
                is_active=True,
            ).first()
            if case.status == CaseStatus.PUBLISHED and mapping is None:
                change_case_status(case, 'OFFLINE', user_id, '初始化流程补充案例资料绑定')

            if case.status != CaseStatus.PUBLISHED:
                CaseDocumentBindingSerializer(data={
                    'workspace_id': workspace_id,
                    'case_id': str(case.id),
                    'document_id': str(document.id),
                }).bind({'document_version': '1.0', 'allow_download': False})
                stats['case_documents_bound'] += 1
                case.refresh_from_db()

                if case.status in (CaseStatus.DRAFT, CaseStatus.REJECTED):
                    change_case_status(case, 'SUBMIT_REVIEW', user_id, '首轮Demo案例提交审核')
                if case.status == CaseStatus.PENDING_REVIEW:
                    change_case_status(case, 'APPROVE', user_id, '资料已脱敏，来源和口径已登记')
                if case.status in (CaseStatus.APPROVED, CaseStatus.OFFLINE):
                    change_case_status(case, 'PUBLISH', user_id, '第一阶段案例库发布')

            if case.status != CaseStatus.PUBLISHED:
                raise BootstrapPrerequisiteError(f'案例未达到发布状态：{case.code}/{case.status}')
            stats['cases_published'] += 1

        active_product_count = QuerySet(ProductProfile).filter(
            workspace_id=workspace_id, status=ProductStatus.ACTIVE,
        ).count()
        published_case_count = QuerySet(CaseProfile).filter(
            workspace_id=workspace_id, status=CaseStatus.PUBLISHED,
        ).count()
        if active_product_count < len(catalog.get('products') or []):
            raise BootstrapPrerequisiteError('启用产品数量不足，初始化结果不完整。')
        if published_case_count < len(case_items):
            raise BootstrapPrerequisiteError('已发布案例数量不足，初始化结果不完整。')

    return {
        'workspace_id': workspace_id,
        'product_knowledge_id': str(setting.product_knowledge_id),
        'case_knowledge_id': str(setting.case_knowledge_id),
        'active_products': active_product_count,
        'published_cases': published_case_count,
        **stats,
    }


try:
    print(json.dumps({'status': 'SUCCESS', 'result': bootstrap()}, ensure_ascii=False))
except BootstrapPrerequisiteError as exc:
    print(json.dumps({'status': 'PREREQUISITE_MISSING', 'message': str(exc)}, ensure_ascii=False))
    raise SystemExit(20)
except Exception as exc:
    print(json.dumps({'status': 'FAILED', 'message': str(exc)}, ensure_ascii=False))
    raise
