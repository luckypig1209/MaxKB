# coding=utf-8
"""案例有效性、授权和服务端脱敏。"""
import re
from typing import Iterable, Optional

from django.db.models import Q, QuerySet
from django.utils import timezone

from opportunity.models import (
    CaseAccessScope,
    CaseProfile,
    CaseStatus,
    DesensitizationStatus,
    SensitivityLevel,
)


PHONE_PATTERN = re.compile(r'(?<!\d)1[3-9]\d{9}(?!\d)')
ID_CARD_PATTERN = re.compile(r'(?<![0-9A-Za-z])\d{17}[0-9Xx](?![0-9A-Za-z])')
EMAIL_PATTERN = re.compile(r'(?<![\w.-])[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}(?![\w.-])')


def _string_ids(values: Optional[Iterable]) -> set[str]:
    return {str(item) for item in (values or []) if item not in (None, '')}


def is_case_effective(case: CaseProfile, now=None) -> bool:
    current = now or timezone.now()
    if case.effective_from and current < case.effective_from:
        return False
    if case.effective_to and current > case.effective_to:
        return False
    return True


def has_explicit_case_access(case: CaseProfile, user_id=None, department_ids=None) -> bool:
    user_id = str(user_id) if user_id else None
    departments = _string_ids(department_ids)
    authorized_users = _string_ids(case.authorized_user_ids)
    authorized_departments = _string_ids(case.authorized_department_ids)
    owner_department_id = str(case.owner_department_id) if case.owner_department_id else None
    if user_id and (user_id == str(case.creator_user_id) or user_id in authorized_users):
        return True
    if departments.intersection(authorized_departments):
        return True
    return bool(owner_department_id and owner_department_id in departments)


def is_case_retrievable(case: CaseProfile, user_id=None, department_ids=None, is_manager=False, now=None) -> bool:
    if case.status != CaseStatus.PUBLISHED:
        return False
    if case.desensitization_status != DesensitizationStatus.PASSED:
        return False
    if not is_case_effective(case, now):
        return False
    if is_manager:
        return True
    explicit_access = has_explicit_case_access(case, user_id, department_ids)
    if case.sensitivity_level == SensitivityLevel.SENSITIVE and not explicit_access:
        return False
    if case.access_scope == CaseAccessScope.WORKSPACE:
        return True
    return explicit_access


def eligible_case_queryset(workspace_id, now=None):
    current = now or timezone.now()
    return QuerySet(CaseProfile).filter(
        workspace_id=workspace_id,
        status=CaseStatus.PUBLISHED,
        desensitization_status=DesensitizationStatus.PASSED,
    ).filter(
        Q(effective_from__isnull=True) | Q(effective_from__lte=current),
        Q(effective_to__isnull=True) | Q(effective_to__gte=current),
    )


def redact_sensitive_text(value: str) -> str:
    if not isinstance(value, str) or not value:
        return value
    value = PHONE_PATTERN.sub('1**********', value)
    value = ID_CARD_PATTERN.sub('******************', value)
    return EMAIL_PATTERN.sub('***@***', value)


def sanitize_case_value(value):
    if isinstance(value, str):
        return redact_sensitive_text(value)
    if isinstance(value, list):
        return [sanitize_case_value(item) for item in value]
    if isinstance(value, dict):
        return {key: sanitize_case_value(item) for key, item in value.items()}
    return value
