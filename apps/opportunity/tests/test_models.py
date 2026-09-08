# coding=utf-8
from unittest.mock import patch

from django.db import IntegrityError, transaction
from django.test import TestCase

from opportunity.models import (
    AnalysisStatus,
    DepartmentProfile,
    OpportunityAnalysis,
    OpportunitySetting,
    ProductDepartmentMapping,
    ProductProfile,
    MappingRole,
    ProductStatus,
)
from opportunity.services.department import resolve_department
from opportunity.serializers.requirement import normalize_requirement_profile
from opportunity.services.analysis import create_analysis


class ModelConstraintTests(TestCase):
    def test_setting_default_and_unique_workspace(self):
        OpportunitySetting.objects.create(workspace_id='ws-a')
        setting = OpportunitySetting.objects.get(workspace_id='ws-a')
        self.assertEqual(setting.search_mode, 'blend')
        self.assertEqual(setting.top_n, 20)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                OpportunitySetting.objects.create(workspace_id='ws-a')

    def test_product_code_unique_per_workspace(self):
        ProductProfile.objects.create(workspace_id='ws-a', code='YIGUAN', name='翼观', status=ProductStatus.ACTIVE)
        ProductProfile.objects.create(workspace_id='ws-b', code='YIGUAN', name='翼观B', status=ProductStatus.ACTIVE)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ProductProfile.objects.create(workspace_id='ws-a', code='YIGUAN', name='重复')

    def test_json_default_not_shared(self):
        a = ProductProfile.objects.create(workspace_id='ws-a', code='A', name='A')
        b = ProductProfile.objects.create(workspace_id='ws-a', code='B', name='B')
        a.aliases.append('one')
        a.save()
        b.refresh_from_db()
        self.assertEqual(b.aliases, [])

    def test_analysis_idempotency(self):
        OpportunityAnalysis.objects.create(
            workspace_id='ws-a', user_id='u1', idempotency_key='k1',
            original_requirement='need monitor', status=AnalysisStatus.ANALYZING,
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                OpportunityAnalysis.objects.create(
                    workspace_id='ws-a', user_id='u1', idempotency_key='k1',
                    original_requirement='need monitor',
                )
        OpportunityAnalysis.objects.create(
            workspace_id='ws-a', user_id='u2', idempotency_key='k1',
            original_requirement='need monitor',
        )

    @patch('opportunity.tasks.analyze_opportunity.delay')
    def test_create_analysis_idempotency_only_dispatches_once(self, delay):
        first = create_analysis('ws-a', 'u1', 'create-once', '需要统一监控')
        second = create_analysis('ws-a', 'u1', 'create-once', '不同文本也不得创建第二条')
        self.assertEqual(first.id, second.id)
        self.assertEqual(OpportunityAnalysis.objects.filter(idempotency_key='create-once').count(), 1)
        delay.assert_called_once_with(str(first.id))

    def test_department_unresolved_when_missing_owner(self):
        product = ProductProfile.objects.create(workspace_id='ws-a', code='YIGUAN', name='翼观',
                                                status=ProductStatus.ACTIVE)
        result = resolve_department(product)
        self.assertEqual(result['status'], 'UNRESOLVED')
        self.assertIsNone(result['owner_department_code'])

    def test_department_resolved_from_mapping(self):
        product = ProductProfile.objects.create(workspace_id='ws-a', code='YIGUAN', name='翼观',
                                                status=ProductStatus.ACTIVE)
        department = DepartmentProfile.objects.create(workspace_id='ws-a', code='DEPT-001', name='监控产品部')
        ProductDepartmentMapping.objects.create(
            workspace_id='ws-a', product=product, department=department, role=MappingRole.OWNER, is_active=True,
        )
        result = resolve_department(product)
        self.assertEqual(result['status'], 'RESOLVED')
        self.assertEqual(result['owner_department_name'], '监控产品部')


class RequirementSchemaTests(TestCase):
    def test_normalize_and_reject_illegal_enum(self):
        data = normalize_requirement_profile({
            'requirements': [{
                'id': 'R-001',
                'description': '统一监控',
                'priority': 'must',
                'category': 'core_function',
                'source_text': '需要统一监控',
            }],
            'missing_information': None,
        })
        self.assertEqual(data['missing_information'], [])
        with self.assertRaises(Exception):
            normalize_requirement_profile({
                'requirements': [{
                    'id': 'R-001',
                    'description': '统一监控',
                    'priority': 'maybe',
                    'category': 'core_function',
                    'source_text': '需要统一监控',
                }]
            })
