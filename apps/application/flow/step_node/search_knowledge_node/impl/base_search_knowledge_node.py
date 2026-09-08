# coding=utf-8
"""
    @project: maxkb
    @Author：虎
    @file： base_search_dataset_node.py
    @date：2024/6/4 11:56
    @desc:
"""
from typing import List, Dict

from django.db.models import QuerySet

from application.flow.i_step_node import NodeResult
from application.flow.step_node.search_knowledge_node.i_search_knowledge_node import ISearchKnowledgeStepNode
from knowledge.models import Document
from knowledge.services.knowledge_search_service import (
    list_paragraph,
    reset_paragraph,
    reset_title,
    search_knowledge,
)


def get_none_result(question):
    return NodeResult(
        {'paragraph_list': [], 'is_hit_handling_method': [], 'question': question, 'data': '',
         'directly_return': ''}, {})


class BaseSearchKnowledgeNode(ISearchKnowledgeStepNode):
    def save_context(self, details, workflow_manage):
        result = details.get('paragraph_list', [])
        knowledge_setting = self.node_params_serializer.data.get('knowledge_setting')
        directly_return = '\n'.join(
            [f"{paragraph.get('title', '')}:{paragraph.get('content')}" for paragraph in result if
             paragraph.get('is_hit_handling_method')])
        self.context['paragraph_list'] = result
        self.context['question'] = details.get('question')
        self.context['run_time'] = details.get('run_time')
        self.context['is_hit_handling_method_list'] = [row for row in result if row.get('is_hit_handling_method')]
        self.context['data'] = '\n'.join(
            [f"{paragraph.get('title', '')}:{paragraph.get('content')}" for paragraph in
             result])[0:knowledge_setting.get('max_paragraph_char_number', 5000)]
        self.context['directly_return'] = directly_return
        self.context['exception_message'] = details.get('err_message')

    def get_reference_content(self, fields: List[str]):
        return self.workflow_manage.get_reference_field(fields[0], fields[1:]) if fields else None

    def execute(self, knowledge_id_list, knowledge_setting, question, show_knowledge, search_scope_type,
                search_scope_source,
                search_scope_reference,
                exclude_paragraph_id_list=None,
                **kwargs) -> NodeResult:
        self.context['question'] = question
        self.context['show_knowledge'] = show_knowledge

        document_id_list = None
        if search_scope_type == 'referencing':  # 引用上一步知识库/文档
            if search_scope_source == 'knowledge':  # 知识库
                knowledge_id_list = self.get_reference_content(search_scope_reference)
            else:  # 文档
                document_id_list = self.get_reference_content(search_scope_reference)
                knowledge_id_list = [str(k) for k in QuerySet(Document).filter(
                    id__in=document_id_list
                ).values_list(
                    'knowledge_id', flat=True
                ).distinct()]

        workspace_id = self.workflow_manage.get_body().get('workspace_id')
        result = search_knowledge(
            workspace_id=workspace_id,
            knowledge_id_list=knowledge_id_list,
            question=question,
            search_mode=knowledge_setting.get('search_mode'),
            top_n=knowledge_setting.get('top_n'),
            similarity=knowledge_setting.get('similarity'),
            document_id_list=document_id_list,
            exclude_paragraph_id_list=exclude_paragraph_id_list,
            chat_user_type=self.workflow_manage.get_body().get('chat_user_type'),
            chat_user_id=self.workflow_manage.get_body().get('chat_user_id'),
            authorize=True,
        )
        if not result:
            return get_none_result(question)
        return NodeResult({'paragraph_list': result,
                           'is_hit_handling_method_list': [row for row in result if row.get('is_hit_handling_method')],
                           'data': '\n'.join(
                               [f"{reset_title(paragraph.get('title', ''))}{paragraph.get('content')}" for paragraph in
                                result])[0:knowledge_setting.get('max_paragraph_char_number', 5000)],
                           'directly_return': '\n'.join(
                               [paragraph.get('content') for paragraph in
                                result if
                                paragraph.get('is_hit_handling_method')]),
                           'question': question},

                          {})

    @staticmethod
    def reset_paragraph(paragraph: Dict, embedding_list: List):
        return reset_paragraph(paragraph, embedding_list)

    @staticmethod
    def list_paragraph(embedding_list: List, vector):
        return list_paragraph(embedding_list, vector)

    def get_details(self, index: int, **kwargs):
        return {
            'name': self.node.properties.get('stepName'),
            'show_knowledge': self.context.get('show_knowledge'),
            'question': self.context.get('question'),
            "index": index,
            'run_time': self.context.get('run_time'),
            'paragraph_list': self.context.get('paragraph_list'),
            'type': self.node.type,
            'status': self.status,
            'err_message': self.err_message,
            'enableException': self.node.properties.get('enableException'),
        }
