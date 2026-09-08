# coding=utf-8
"""
    @project: MaxKB
    @Author：bia
    @file： department.py
    @date：2026/9/3
    @desc: 产品部门主数据查询
"""
from django.db.models import Q, QuerySet
from django.utils import timezone

from opportunity.models import DepartmentStatus, MappingRole, ProductDepartmentMapping, ProductProfile


def is_mapping_effective(mapping, now=None) -> bool:
    if not mapping.is_active:
        return False
    current = now or timezone.now()
    if mapping.effective_from and current < mapping.effective_from:
        return False
    if mapping.effective_to and current > mapping.effective_to:
        return False
    if mapping.department_id and mapping.department.status != DepartmentStatus.ACTIVE:
        return False
    return True


def current_owner_queryset(product: ProductProfile, now=None):
    current = now or timezone.now()
    queryset = QuerySet(ProductDepartmentMapping).filter(
        workspace_id=product.workspace_id,
        product_id=product.id,
        role=MappingRole.OWNER,
        is_active=True,
    ).filter(
        Q(effective_from__isnull=True) | Q(effective_from__lte=current)
    ).filter(
        Q(effective_to__isnull=True) | Q(effective_to__gte=current)
    ).select_related('department')
    return queryset


def resolve_department(product: ProductProfile, now=None) -> dict:
    current = now or timezone.now()
    owners = [item for item in current_owner_queryset(product, current) if is_mapping_effective(item, current)]
    supports = QuerySet(ProductDepartmentMapping).filter(
        workspace_id=product.workspace_id,
        product_id=product.id,
        is_active=True,
    ).exclude(role=MappingRole.OWNER).select_related('department')
    support_departments = []
    for mapping in supports:
        if not is_mapping_effective(mapping, current):
            continue
        support_departments.append({
            'role': mapping.role,
            'department_code': mapping.department.code,
            'department_name': mapping.department.name,
            'owner_user_id': mapping.owner_user_id,
        })
    if len(owners) != 1:
        return {
            'status': 'UNRESOLVED',
            'owner_department_code': None,
            'owner_department_name': None,
            'owner_user_id': None,
            'support_departments': support_departments,
        }
    owner = owners[0]
    return {
        'status': 'RESOLVED',
        'owner_department_code': owner.department.code,
        'owner_department_name': owner.department.name,
        'owner_user_id': owner.owner_user_id,
        'support_departments': support_departments,
    }
