# coding=utf-8
"""
    @project: MaxKB
    @Author：bia
    @file： knowledge_search_service.py
    @date：2026/9/3
    @desc: 可复用知识检索服务
"""
import os
from typing import Dict, List, Optional

from django.db import connection
from django.db.models import QuerySet

from common.config.embedding_config import VectorStore
from common.constants.permission_constants import RoleConstants
from common.database_model_manage.database_model_manage import DatabaseModelManage
from common.db.search import native_search
from common.utils.common import get_file_content
from common.utils.shared_resource_auth import filter_authorized_ids
from knowledge.models import Document, Knowledge, Paragraph, SearchMode
from maxkb.conf import PROJECT_DIR
from models_provider.tools import get_model_instance_by_model_workspace_id


def get_embedding_id(dataset_id_list):
    dataset_list = QuerySet(Knowledge).filter(id__in=dataset_id_list)
    if len(set([dataset.embedding_model_id for dataset in dataset_list])) > 1:
        raise Exception("关联知识库的向量模型不一致，无法召回分段。")
    if len(dataset_list) == 0:
        raise Exception("知识库设置错误,请重新设置知识库")
    return dataset_list[0].embedding_model_id


def reset_title(title):
    if title is None or len(title.strip()) == 0:
        return ""
    return f"#### {title}\n"


def reset_meta(meta):
    if not meta:
        return {'allow_download': False}
    if not meta.get('allow_download', False):
        return {'allow_download': False}
    return meta


def list_paragraph(embedding_list: List, vector):
    paragraph_id_list = [row.get('paragraph_id') for row in embedding_list]
    if paragraph_id_list is None or len(paragraph_id_list) == 0:
        return []
    paragraph_list = native_search(
        QuerySet(Paragraph).filter(id__in=paragraph_id_list),
        get_file_content(
            os.path.join(PROJECT_DIR, "apps", "application", 'sql',
                         'list_knowledge_paragraph_by_paragraph_id.sql')
        ),
        with_table_name=True,
    )
    if len(paragraph_list) != len(paragraph_id_list):
        exist_paragraph_list = [row.get('id') for row in paragraph_list]
        for paragraph_id in paragraph_id_list:
            if paragraph_id not in exist_paragraph_list:
                vector.delete_by_paragraph_id(paragraph_id)
    return paragraph_list


def reset_paragraph(paragraph: Dict, embedding_list: List):
    filter_embedding_list = [
        embedding for embedding in embedding_list
        if str(embedding.get('paragraph_id')) == str(paragraph.get('id'))
    ]
    if filter_embedding_list:
        find_embedding = filter_embedding_list[-1]
        return {
            **paragraph,
            'similarity': find_embedding.get('similarity'),
            'is_hit_handling_method': find_embedding.get('similarity') > paragraph.get(
                'directly_return_similarity') and paragraph.get('hit_handling_method') == 'directly_return',
            'update_time': paragraph.get('update_time').strftime("%Y-%m-%d %H:%M:%S"),
            'create_time': paragraph.get('create_time').strftime("%Y-%m-%d %H:%M:%S"),
            'id': str(paragraph.get('id')),
            'knowledge_id': str(paragraph.get('knowledge_id')),
            'document_id': str(paragraph.get('document_id')),
            'meta': reset_meta(paragraph.get('meta')),
        }
    return paragraph


def search_knowledge(
    workspace_id: str,
    knowledge_id_list: List[str],
    question: str,
    search_mode: str = 'blend',
    top_n: int = 20,
    similarity: float = 0.3,
    document_id_list: Optional[List[str]] = None,
    exclude_paragraph_id_list: Optional[List[str]] = None,
    chat_user_type: Optional[str] = None,
    chat_user_id: Optional[str] = None,
    authorize: bool = True,
):
    knowledge_id_list = [str(item) for item in (knowledge_id_list or []) if item]
    if authorize:
        get_knowledge_list_of_authorized = DatabaseModelManage.get_model('get_knowledge_list_of_authorized')
        if get_knowledge_list_of_authorized is not None and RoleConstants.CHAT_USER.value.name == chat_user_type:
            knowledge_id_list = get_knowledge_list_of_authorized(chat_user_id, knowledge_id_list)
        knowledge_id_list = filter_authorized_ids('knowledge', knowledge_id_list, workspace_id)
    if not knowledge_id_list:
        return []
    model_id = get_embedding_id(knowledge_id_list)
    embedding_model = get_model_instance_by_model_workspace_id(model_id, workspace_id)
    embedding_value = embedding_model.embed_query(question)
    vector = VectorStore.get_embedding_vector()
    exclude_document_id_list = [
        str(document.id) for document in QuerySet(Document).filter(
            knowledge_id__in=knowledge_id_list,
            is_active=False,
        )
    ]
    embedding_list = vector.query(
        question,
        embedding_value,
        knowledge_id_list,
        document_id_list,
        exclude_document_id_list,
        exclude_paragraph_id_list,
        True,
        top_n,
        similarity,
        SearchMode(search_mode),
    )
    connection.close()
    if embedding_list is None:
        return []
    paragraph_list = list_paragraph(embedding_list, vector)
    result = [reset_paragraph(paragraph, embedding_list) for paragraph in paragraph_list]
    return sorted(result, key=lambda item: item.get('similarity') or 0, reverse=True)
