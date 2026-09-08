# coding=utf-8
from django.test import TestCase

from models_provider.models import Model
from opportunity.serializers.setting import SettingOperateSerializer


class OpportunitySettingValidationTests(TestCase):
    def create_model(self, model_type):
        return Model.objects.create(
            workspace_id='ws-a',
            name=f'{model_type}-model',
            model_type=model_type,
            model_name='test-model',
            provider='test',
            credential='{}',
        )

    def test_rejects_embedding_model_as_llm(self):
        embedding = self.create_model('EMBEDDING')
        with self.assertRaises(Exception):
            SettingOperateSerializer(data={'workspace_id': 'ws-a'}).update({
                'llm_model_id': str(embedding.id),
            })

    def test_accepts_expected_llm_and_reranker_types(self):
        llm = self.create_model('LLM')
        reranker = self.create_model('RERANKER')
        result = SettingOperateSerializer(data={'workspace_id': 'ws-a'}).update({
            'llm_model_id': str(llm.id),
            'rerank_model_id': str(reranker.id),
        })
        self.assertEqual(result['llm_model_id'], str(llm.id))
        self.assertEqual(result['rerank_model_id'], str(reranker.id))
