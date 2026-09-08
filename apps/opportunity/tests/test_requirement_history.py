# coding=utf-8
from django.test import TestCase

from common.exception.app_exception import AppApiException
from opportunity.models import AnalysisStatus, OpportunityAnalysis, RequirementProfileSource
from opportunity.serializers.analysis import AnalysisOperateSerializer, analysis_to_dict
from opportunity.services.requirement_history import save_requirement_profile_version


def profile(description='统一监控'):
    return {
        'schema_version': '1.0',
        'customer_context': {'industry': '医疗', 'customer_type': None, 'region': None},
        'business_scenarios': ['医疗资源监控'],
        'pain_points': ['故障发现晚'],
        'requirements': [{
            'id': 'R-001',
            'description': description,
            'priority': 'must',
            'category': 'core_function',
            'source_text': description,
        }],
        'constraints': [],
        'excluded_conditions': [],
        'missing_information': [],
        'clarification_questions': [],
    }


def analysis(user_id='u1'):
    return OpportunityAnalysis.objects.create(
        workspace_id='ws-a',
        user_id=user_id,
        idempotency_key=f'profile-{user_id}',
        status=AnalysisStatus.ANALYZING,
        original_requirement='需要统一监控',
    )


class RequirementProfileHistoryTests(TestCase):
    def test_changed_profile_creates_immutable_incrementing_versions(self):
        item = analysis()
        first, created = save_requirement_profile_version(
            item, profile(), RequirementProfileSource.INITIAL, 'u1',
        )
        second, second_created = save_requirement_profile_version(
            item, profile('统一监控并支持国产化'), RequirementProfileSource.CLARIFICATION, 'u1',
        )
        first.refresh_from_db()
        item.refresh_from_db()
        self.assertTrue(created)
        self.assertTrue(second_created)
        self.assertEqual(first.version, 1)
        self.assertEqual(first.profile['requirements'][0]['description'], '统一监控')
        self.assertEqual(second.version, 2)
        self.assertEqual(second.source, RequirementProfileSource.CLARIFICATION)
        self.assertEqual(item.requirement_profile, second.profile)

    def test_same_profile_retry_reuses_latest_version(self):
        item = analysis()
        first, _ = save_requirement_profile_version(item, profile(), RequirementProfileSource.INITIAL, 'u1')
        second, created = save_requirement_profile_version(item, profile(), RequirementProfileSource.INITIAL, 'u1')
        self.assertFalse(created)
        self.assertEqual(first.id, second.id)
        self.assertEqual(item.requirement_versions.count(), 1)

    def test_detail_and_version_query_expose_current_version(self):
        item = analysis()
        save_requirement_profile_version(item, profile(), RequirementProfileSource.INITIAL, 'u1')
        item.refresh_from_db()
        detail = analysis_to_dict(item)
        serializer = AnalysisOperateSerializer(data={
            'workspace_id': 'ws-a', 'analysis_id': str(item.id),
            'user_id': 'u1', 'is_manager': False,
        })
        versions = serializer.requirement_versions()
        self.assertEqual(detail['requirement_profile_version'], 1)
        self.assertEqual(versions[0]['version'], 1)
        self.assertEqual(versions[0]['profile']['requirements'][0]['id'], 'R-001')

    def test_regular_user_cannot_query_another_users_versions(self):
        item = analysis(user_id='u2')
        save_requirement_profile_version(item, profile(), RequirementProfileSource.INITIAL, 'u2')
        serializer = AnalysisOperateSerializer(data={
            'workspace_id': 'ws-a', 'analysis_id': str(item.id),
            'user_id': 'u1', 'is_manager': False,
        })
        with self.assertRaises(AppApiException):
            serializer.requirement_versions()
