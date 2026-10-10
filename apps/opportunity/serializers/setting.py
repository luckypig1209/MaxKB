# coding=utf-8
"""
    @project: MaxKB
    @Author：bia
    @file： setting.py
    @date：2026/9/3
    @desc: 商机分析配置
"""
from rest_framework import serializers

from models_provider.base_model_provider import ModelTypeConst
from opportunity.models import SearchModeChoices
from opportunity.serializers.common import model_time, require_knowledge, require_model
from opportunity.services.analysis import get_setting
from opportunity.services.embed_security import is_opportunity_embed_enabled


class OpportunitySettingSerializer(serializers.Serializer):
    llm_model_id = serializers.UUIDField(required=False, allow_null=True)
    product_knowledge_id = serializers.UUIDField(required=False, allow_null=True)
    case_knowledge_id = serializers.UUIDField(required=False, allow_null=True)
    rerank_model_id = serializers.UUIDField(required=False, allow_null=True)
    search_mode = serializers.ChoiceField(choices=SearchModeChoices.choices, required=False)
    top_n = serializers.IntegerField(required=False, min_value=1, max_value=100)
    similarity = serializers.FloatField(required=False, min_value=0, max_value=1)
    max_candidates = serializers.IntegerField(required=False, min_value=1, max_value=10)
    prompt_version = serializers.CharField(required=False, allow_blank=True)
    meta = serializers.JSONField(required=False)


def setting_to_dict(setting):
    return {
        'id': str(setting.id),
        'workspace_id': setting.workspace_id,
        'llm_model_id': str(setting.llm_model_id) if setting.llm_model_id else None,
        'product_knowledge_id': str(setting.product_knowledge_id) if setting.product_knowledge_id else None,
        'case_knowledge_id': str(setting.case_knowledge_id) if setting.case_knowledge_id else None,
        'rerank_model_id': str(setting.rerank_model_id) if setting.rerank_model_id else None,
        'search_mode': setting.search_mode,
        'top_n': setting.top_n,
        'similarity': setting.similarity,
        'max_candidates': setting.max_candidates,
        'prompt_version': setting.prompt_version,
        'meta': setting.meta or {},
        # The admin UI uses this runtime value to hide the opt-in embed tab;
        # it is deliberately read-only and never persists in workspace data.
        'embed_enabled': is_opportunity_embed_enabled(),
        'create_time': model_time(setting.create_time),
        'update_time': model_time(setting.update_time),
    }


class SettingOperateSerializer(serializers.Serializer):
    workspace_id = serializers.CharField(required=True)

    def one(self):
        self.is_valid(raise_exception=True)
        return setting_to_dict(get_setting(self.validated_data['workspace_id']))

    def update(self, instance: dict):
        self.is_valid(raise_exception=True)
        serializer = OpportunitySettingSerializer(data=instance)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        workspace_id = self.validated_data['workspace_id']
        require_model(workspace_id, data.get('llm_model_id'), ModelTypeConst.LLM.name)
        require_model(workspace_id, data.get('rerank_model_id'), ModelTypeConst.RERANKER.name)
        require_knowledge(workspace_id, data.get('product_knowledge_id'))
        require_knowledge(workspace_id, data.get('case_knowledge_id'))
        setting = get_setting(workspace_id)
        for field, value in data.items():
            setattr(setting, field, value)
        setting.save()
        return setting_to_dict(setting)
