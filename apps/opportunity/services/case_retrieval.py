# coding=utf-8
"""候选产品范围内的案例知识检索基础服务。"""
from collections import defaultdict

from django.db.models import QuerySet
from django.utils import timezone

from knowledge.models import Document
from knowledge.services.knowledge_search_service import search_knowledge
from opportunity.models import CaseDocumentMapping, CaseProductMapping, CaseProfile
from opportunity.services.case_access import is_case_retrievable, sanitize_case_value
from opportunity.services.knowledge_metadata import get_bia_meta, is_case_document_retrievable


def retrieve_case_paragraphs(
    workspace_id,
    knowledge_id,
    question,
    product_codes,
    industry=None,
    search_mode='blend',
    top_n=10,
    similarity=0.3,
    user_id=None,
    department_ids=None,
    is_manager=False,
):
    """只返回候选产品关联且通过发布、脱敏、授权和有效期校验的案例片段。"""
    product_codes = {str(item) for item in (product_codes or []) if item}
    if not product_codes or not knowledge_id:
        return []
    expanded_top_n = max(int(top_n or 10), 1) * 4
    raw_hits = search_knowledge(
        workspace_id=workspace_id,
        knowledge_id_list=[str(knowledge_id)],
        question=question,
        search_mode=search_mode or 'blend',
        top_n=expanded_top_n,
        similarity=similarity if similarity is not None else 0.3,
        authorize=True,
    )
    document_ids = {str(hit.get('document_id')) for hit in raw_hits if hit.get('document_id')}
    if not document_ids:
        return []
    documents = {
        str(item.id): item
        for item in QuerySet(Document).filter(id__in=document_ids, knowledge_id=knowledge_id)
    }
    mappings = list(QuerySet(CaseDocumentMapping).select_related('case').filter(
        workspace_id=workspace_id,
        knowledge_id=knowledge_id,
        document_id__in=document_ids,
        is_active=True,
    ))
    case_ids = {item.case_id for item in mappings}
    case_products = defaultdict(set)
    case_product_versions = defaultdict(dict)
    for item in QuerySet(CaseProductMapping).select_related('product').filter(
        workspace_id=workspace_id,
        case_id__in=case_ids,
        product__code__in=product_codes,
        is_active=True,
    ):
        case_products[str(item.case_id)].add(item.product.code)
        case_product_versions[str(item.case_id)][item.product.code] = item.product_version
    cases = {
        str(item.id): item
        for item in QuerySet(CaseProfile).filter(id__in=case_ids, workspace_id=workspace_id)
    }
    mapping_by_document = {str(item.document_id): item for item in mappings}
    now = timezone.now()
    filtered = []
    for hit in raw_hits:
        document_id = str(hit.get('document_id'))
        mapping = mapping_by_document.get(document_id)
        document = documents.get(document_id)
        case = cases.get(str(mapping.case_id)) if mapping else None
        matched_products = case_products.get(str(case.id), set()) if case else set()
        if not document or not case or not matched_products:
            continue
        if not is_case_retrievable(
            case,
            user_id=user_id,
            department_ids=department_ids,
            is_manager=is_manager,
            now=now,
        ):
            continue
        if not is_case_document_retrievable(document, case.code, now):
            continue
        expected_industry = str(industry or '').strip().lower()
        case_industry = str(case.industry or '').strip().lower()
        if expected_industry and case_industry and (
            expected_industry not in case_industry and case_industry not in expected_industry
        ):
            continue
        bia = get_bia_meta(document)
        allow_download = bool(bia.get('allow_download', False)) and (
            is_manager or case.sensitivity_level == 'PUBLIC'
        )
        excerpt = sanitize_case_value(hit.get('content') or '')
        if not allow_download:
            excerpt = excerpt[:240]
        filtered.append({
            'paragraph_id': str(hit.get('id')),
            'knowledge_id': str(hit.get('knowledge_id')),
            'document_id': document_id,
            'document_name': document.name,
            'title': sanitize_case_value(hit.get('title') or ''),
            'content_excerpt': excerpt,
            'similarity': hit.get('similarity') or 0,
            'document_version': mapping.document_version,
            'case_id': str(case.id),
            'case_code': case.code,
            'case_name': sanitize_case_value(case.name),
            'industry': case.industry,
            'scenario': sanitize_case_value(case.scenario),
            'project_scale': sanitize_case_value(case.project_scale or {}),
            'outcomes': sanitize_case_value(case.outcomes or []),
            'applicability_boundary': sanitize_case_value(case.applicability_boundary),
            'product_codes': sorted(matched_products),
            'product_versions': case_product_versions.get(str(case.id), {}),
            'allow_download': allow_download,
        })
        if len(filtered) >= int(top_n or 10):
            break
    return filtered
