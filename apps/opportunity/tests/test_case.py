# coding=utf-8
from datetime import timedelta
from types import SimpleNamespace

from django.db import IntegrityError, transaction
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from opportunity.models import (
    CaseAccessScope,
    CaseProductMapping,
    CaseProfile,
    CaseStatus,
    DesensitizationStatus,
    OpportunitySetting,
    ProductProfile,
    ProductStatus,
    SensitivityLevel,
)
from opportunity.serializers.case import (
    CASE_ACTION_TRANSITIONS,
    CASE_BINDABLE_STATUSES,
    CaseOperateSerializer,
    CaseWriteSerializer,
)
from opportunity.services.case_access import is_case_retrievable, sanitize_case_value
from opportunity.services.knowledge_metadata import is_case_document_retrievable


def build_case(**overrides):
    data = {
        'status': CaseStatus.PUBLISHED,
        'desensitization_status': DesensitizationStatus.PASSED,
        'sensitivity_level': SensitivityLevel.INTERNAL,
        'access_scope': CaseAccessScope.WORKSPACE,
        'effective_from': None,
        'effective_to': None,
        'creator_user_id': 'creator',
        'authorized_user_ids': [],
        'authorized_department_ids': [],
        'owner_department_id': None,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


class CaseAccessTests(SimpleTestCase):
    def test_only_published_desensitized_and_effective_case_is_retrievable(self):
        self.assertTrue(is_case_retrievable(build_case(), user_id='user-a'))
        self.assertFalse(is_case_retrievable(build_case(status=CaseStatus.APPROVED), user_id='user-a'))
        self.assertFalse(is_case_retrievable(
            build_case(desensitization_status=DesensitizationStatus.PENDING), user_id='user-a',
        ))
        self.assertFalse(is_case_retrievable(
            build_case(effective_to=timezone.now() - timedelta(seconds=1)), user_id='user-a',
        ))

    def test_sensitive_and_department_cases_require_explicit_access(self):
        sensitive = build_case(
            sensitivity_level=SensitivityLevel.SENSITIVE,
            authorized_user_ids=['user-a'],
        )
        self.assertTrue(is_case_retrievable(sensitive, user_id='user-a'))
        self.assertFalse(is_case_retrievable(sensitive, user_id='user-b'))
        department = build_case(
            access_scope=CaseAccessScope.DEPARTMENT,
            authorized_department_ids=['dept-a'],
        )
        self.assertTrue(is_case_retrievable(department, user_id='user-b', department_ids=['dept-a']))
        self.assertFalse(is_case_retrievable(department, user_id='user-b', department_ids=['dept-b']))

    def test_server_side_redaction(self):
        data = {
            'phone': '联系人电话 13912345678',
            'id_card': '证件 320101199001011234',
            'nested': ['邮箱 demo@example.com'],
        }
        sanitized = sanitize_case_value(data)
        self.assertNotIn('13912345678', sanitized['phone'])
        self.assertNotIn('320101199001011234', sanitized['id_card'])
        self.assertNotIn('demo@example.com', sanitized['nested'][0])

    def test_case_document_requires_published_and_desensitized_metadata(self):
        published = SimpleNamespace(is_active=True, meta={'bia': {
            'asset_type': 'case', 'case_code': 'CASE-001', 'publish_status': 'published',
            'desensitization_status': 'PASSED',
        }})
        pending = SimpleNamespace(is_active=True, meta={'bia': {
            'asset_type': 'case', 'case_code': 'CASE-001', 'publish_status': 'published',
            'desensitization_status': 'PENDING',
        }})
        self.assertTrue(is_case_document_retrievable(published, 'CASE-001'))
        self.assertFalse(is_case_document_retrievable(pending, 'CASE-001'))

    def test_write_schema_rejects_invalid_primary_and_department_scope(self):
        invalid_primary = CaseWriteSerializer(data={
            'code': 'CASE-001', 'name': '案例', 'product_codes': ['P1'], 'primary_product_code': 'P2',
        })
        self.assertFalse(invalid_primary.is_valid())
        invalid_scope = CaseWriteSerializer(data={
            'code': 'CASE-001', 'name': '案例', 'product_codes': ['P1'], 'access_scope': 'DEPARTMENT',
        })
        self.assertFalse(invalid_scope.is_valid())

    def test_review_transition_contract(self):
        self.assertIn(CaseStatus.DRAFT, CASE_ACTION_TRANSITIONS['SUBMIT_REVIEW'][0])
        self.assertEqual(CASE_ACTION_TRANSITIONS['APPROVE'][1], CaseStatus.APPROVED)
        self.assertEqual(CASE_ACTION_TRANSITIONS['PUBLISH'][1], CaseStatus.PUBLISHED)
        self.assertNotIn(CaseStatus.DRAFT, CASE_ACTION_TRANSITIONS['PUBLISH'][0])
        self.assertNotIn(CaseStatus.PUBLISHED, CASE_BINDABLE_STATUSES)
        self.assertIn(CaseStatus.OFFLINE, CASE_BINDABLE_STATUSES)


class CaseModelTests(TestCase):
    def test_case_code_unique_in_workspace(self):
        CaseProfile.objects.create(workspace_id='ws-a', code='CASE-001', name='案例A', creator_user_id='u1')
        CaseProfile.objects.create(workspace_id='ws-b', code='CASE-001', name='案例B', creator_user_id='u1')
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CaseProfile.objects.create(
                    workspace_id='ws-a', code='CASE-001', name='重复案例', creator_user_id='u1',
                )

    def test_case_product_snapshot_and_unique_mapping(self):
        case = CaseProfile.objects.create(
            workspace_id='ws-a', code='CASE-001', name='案例A', creator_user_id='u1',
        )
        product = ProductProfile.objects.create(
            workspace_id='ws-a', code='P1', name='产品一', status=ProductStatus.ACTIVE,
        )
        mapping = CaseProductMapping.objects.create(
            workspace_id='ws-a', case=case, product=product, product_version='v1', is_primary=True,
        )
        self.assertEqual(mapping.product_version, 'v1')
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CaseProductMapping.objects.create(workspace_id='ws-a', case=case, product=product)

    def test_setting_has_independent_case_knowledge(self):
        setting = OpportunitySetting.objects.create(workspace_id='ws-a')
        self.assertIsNone(setting.case_knowledge_id)

    def test_editing_approved_case_resets_review(self):
        product = ProductProfile.objects.create(
            workspace_id='ws-a', code='P1', name='产品一', status=ProductStatus.ACTIVE,
        )
        case = CaseProfile.objects.create(
            workspace_id='ws-a', code='CASE-001', name='案例A', creator_user_id='u1',
            status=CaseStatus.APPROVED, desensitization_status=DesensitizationStatus.PASSED,
            reviewer_user_id='reviewer', reviewed_at=timezone.now(),
        )
        CaseProductMapping.objects.create(workspace_id='ws-a', case=case, product=product)
        CaseOperateSerializer(data={
            'workspace_id': 'ws-a', 'case_id': str(case.id), 'user_id': 'u1', 'is_manager': True,
        }).update({'code': 'CASE-001', 'name': '案例A（修订）', 'product_codes': ['P1']})
        case.refresh_from_db()
        self.assertEqual(case.status, CaseStatus.DRAFT)
        self.assertEqual(case.desensitization_status, DesensitizationStatus.PENDING)
        self.assertIsNone(case.reviewer_user_id)
        self.assertIsNone(case.reviewed_at)
