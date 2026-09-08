# coding=utf-8
"""
    @project: MaxKB
    @Author：bia
    @file： knowledge_retrieval.py
    @date：2026/9/3
    @desc: 商机产品知识召回
"""
from django.db.models import QuerySet
from django.utils import timezone

from knowledge.models import Document
from knowledge.services.knowledge_search_service import search_knowledge
from opportunity.models import ProductProfile, ProductStatus
from opportunity.services.knowledge_metadata import get_bia_meta, is_document_retrievable


def retrieve_product_paragraphs(workspace_id, knowledge_id, question, search_mode, top_n, similarity):
    expanded_top_n = max(int(top_n or 20), 1) * 3
    raw_hits = search_knowledge(
        workspace_id=workspace_id,
        knowledge_id_list=[str(knowledge_id)],
        question=question,
        search_mode=search_mode or 'blend',
        top_n=expanded_top_n,
        similarity=similarity if similarity is not None else 0.3,
        authorize=True,
    )
    now = timezone.now()
    document_ids = list({hit.get('document_id') for hit in raw_hits if hit.get('document_id')})
    documents = {
        str(item.id): item
        for item in QuerySet(Document).filter(id__in=document_ids, knowledge_id=knowledge_id)
    }
    products = {
        item.code: item
        for item in QuerySet(ProductProfile).filter(workspace_id=workspace_id, status=ProductStatus.ACTIVE)
    }
    filtered = []
    for hit in raw_hits:
        document = documents.get(str(hit.get('document_id')))
        if document is None or not is_document_retrievable(document, now):
            continue
        bia = get_bia_meta(document)
        product_code = bia.get('product_code')
        product = products.get(product_code)
        if product is None:
            continue
        allow_download = bool(bia.get('allow_download', False))
        excerpt = hit.get('content') or ''
        if not allow_download:
            excerpt = excerpt[:240]
        filtered.append({
            'paragraph_id': str(hit.get('id')),
            'knowledge_id': str(hit.get('knowledge_id')),
            'document_id': str(hit.get('document_id')),
            'document_name': document.name,
            'title': hit.get('title') or '',
            'content_excerpt': excerpt,
            'similarity': hit.get('similarity') or 0,
            'document_version': bia.get('document_version') or '1.0',
            'product_code': product.code,
            'product_name': product.name,
            'allow_download': allow_download,
        })
        if len(filtered) >= int(top_n or 20):
            break
    return filtered
