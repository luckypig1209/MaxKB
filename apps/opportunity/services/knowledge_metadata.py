# coding=utf-8
"""
    @project: MaxKB
    @Author：bia
    @file： knowledge_metadata.py
    @date：2026/9/3
    @desc: 产品资料元数据校验
"""
from datetime import datetime
from typing import Optional

from django.utils import timezone
from django.utils.dateparse import parse_datetime, parse_date

BIA_SCHEMA_VERSION = '1.0'
ASSET_TYPE_PRODUCT = 'product'
ASSET_TYPE_CASE = 'case'


def _parse_time(value):
    if value in (None, ''):
        return None
    if isinstance(value, datetime):
        return value
    parsed = parse_datetime(str(value))
    if parsed:
        return parsed
    parsed_date = parse_date(str(value))
    if parsed_date:
        return datetime.combine(parsed_date, datetime.min.time())
    return None


def get_bia_meta(document) -> dict:
    meta = document.meta if isinstance(getattr(document, 'meta', None), dict) else {}
    bia = meta.get('bia') if isinstance(meta.get('bia'), dict) else {}
    return bia


def is_document_retrievable(document, now: Optional[datetime] = None) -> bool:
    if not getattr(document, 'is_active', True):
        return False
    bia = get_bia_meta(document)
    if bia.get('asset_type') != ASSET_TYPE_PRODUCT:
        return False
    if not bia.get('product_code'):
        return False
    if bia.get('publish_status') != 'published':
        return False
    current = now or timezone.now()
    if timezone.is_naive(current):
        current = timezone.make_aware(current, timezone.get_current_timezone())
    effective_from = _parse_time(bia.get('effective_from'))
    effective_to = _parse_time(bia.get('effective_to'))
    if effective_from and timezone.is_naive(effective_from):
        effective_from = timezone.make_aware(effective_from, timezone.get_current_timezone())
    if effective_to and timezone.is_naive(effective_to):
        effective_to = timezone.make_aware(effective_to, timezone.get_current_timezone())
    if effective_from and current < effective_from:
        return False
    if effective_to and current > effective_to:
        return False
    return True


def is_case_document_retrievable(document, case_code: str, now: Optional[datetime] = None) -> bool:
    if not getattr(document, 'is_active', True):
        return False
    bia = get_bia_meta(document)
    if bia.get('asset_type') != ASSET_TYPE_CASE:
        return False
    if not case_code or bia.get('case_code') != case_code:
        return False
    if bia.get('publish_status') != 'published':
        return False
    if bia.get('desensitization_status') != 'PASSED':
        return False
    current = now or timezone.now()
    if timezone.is_naive(current):
        current = timezone.make_aware(current, timezone.get_current_timezone())
    effective_from = _parse_time(bia.get('effective_from'))
    effective_to = _parse_time(bia.get('effective_to'))
    if effective_from and timezone.is_naive(effective_from):
        effective_from = timezone.make_aware(effective_from, timezone.get_current_timezone())
    if effective_to and timezone.is_naive(effective_to):
        effective_to = timezone.make_aware(effective_to, timezone.get_current_timezone())
    if effective_from and current < effective_from:
        return False
    if effective_to and current > effective_to:
        return False
    return True


def merge_bia_meta(existing_meta: dict, bia: dict) -> dict:
    merged = dict(existing_meta or {})
    merged['bia'] = {
        'schema_version': bia.get('schema_version') or BIA_SCHEMA_VERSION,
        'asset_type': bia.get('asset_type') or ASSET_TYPE_PRODUCT,
        'product_code': bia.get('product_code'),
        'product_name': bia.get('product_name'),
        'product_line': bia.get('product_line') or '',
        'document_type': bia.get('document_type') or 'explanation',
        'document_version': bia.get('document_version') or '1.0',
        'publish_status': bia.get('publish_status') or 'published',
        'effective_from': bia.get('effective_from'),
        'effective_to': bia.get('effective_to'),
        'owner_department_code': bia.get('owner_department_code'),
        'allow_download': bool(bia.get('allow_download', False)),
    }
    return merged


def merge_case_bia_meta(existing_meta: dict, bia: dict) -> dict:
    merged = dict(existing_meta or {})
    merged['bia'] = {
        'schema_version': bia.get('schema_version') or BIA_SCHEMA_VERSION,
        'asset_type': ASSET_TYPE_CASE,
        'case_code': bia.get('case_code'),
        'case_name': bia.get('case_name'),
        'product_codes': list(bia.get('product_codes') or []),
        'industry': bia.get('industry') or '',
        'scenario': bia.get('scenario') or '',
        'document_type': bia.get('document_type') or 'case_profile',
        'document_version': bia.get('document_version') or '1.0',
        'publish_status': bia.get('publish_status') or 'draft',
        'desensitization_status': bia.get('desensitization_status') or 'PENDING',
        'sensitivity_level': bia.get('sensitivity_level') or 'INTERNAL',
        'access_scope': bia.get('access_scope') or 'WORKSPACE',
        'effective_from': bia.get('effective_from'),
        'effective_to': bia.get('effective_to'),
        'allow_download': bool(bia.get('allow_download', False)),
    }
    return merged
