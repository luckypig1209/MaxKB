# coding=utf-8
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase

from common.exception.app_exception import AppApiException
from knowledge.models import Document, Knowledge, KnowledgeFolder
from opportunity.models import (
    CaseDocumentMapping,
    CaseProfile,
    CaseStatus,
    OpportunitySetting,
    ProductProfile,
    ProductStatus,
)
from opportunity.serializers.case import (
    CaseOperateSerializer,
    CaseSerializer,
    list_available_case_documents,
)
from opportunity.views.case import _is_manager


class CaseRegistrationTests(TestCase):
    workspace_id = 'case-registration'

    def setUp(self):
        folder = KnowledgeFolder.objects.create(
            id=f'{self.workspace_id}-folder', name='案例资料', workspace_id=self.workspace_id,
        )
        self.knowledge = Knowledge.objects.create(
            name='案例知识库', desc='', workspace_id=self.workspace_id, folder=folder,
        )
        OpportunitySetting.objects.create(
            workspace_id=self.workspace_id, case_knowledge_id=self.knowledge.id,
        )
        self.other_knowledge = Knowledge.objects.create(
            name='其他知识库', desc='', workspace_id=self.workspace_id, folder=folder,
        )
        self.product = ProductProfile.objects.create(
            workspace_id=self.workspace_id, code='P1', name='产品一', status=ProductStatus.ACTIVE,
        )
        self.ready_document = Document.objects.create(
            knowledge=self.knowledge, name='ready.md', char_length=10, status='nnn2',
        )
        self.pending_document = Document.objects.create(
            knowledge=self.knowledge, name='pending.md', char_length=10, status='nnn0',
        )
        self.wrong_knowledge_document = Document.objects.create(
            knowledge=self.other_knowledge, name='wrong.md', char_length=10, status='nnn2',
        )

    def registration_payload(self, document_id=None, **overrides):
        payload = {
            'code': 'CASE-UTF8',
            'name': '某省政务统一运维—一期🚀',
            'scenario': '统一运维与告警',
            'product_codes': ['P1'],
            'document_id': str(document_id or self.ready_document.id),
            'document_version': 'v1.2',
            'allow_download': True,
        }
        payload.update(overrides)
        return payload

    def register(self, payload=None, code='CASE-UTF8'):
        data = payload or self.registration_payload()
        data['code'] = code
        return CaseSerializer(data={
            'workspace_id': self.workspace_id,
            'user_id': 'manager-1',
            'is_manager': True,
            'require_document': True,
        }).insert(data)

    def test_registration_rolls_back_profile_and_product_mapping_on_document_failure(self):
        with patch('opportunity.serializers.case._validate_case_document',
                   side_effect=AppApiException(500, 'document rejected')):
            with self.assertRaises(AppApiException):
                self.register(code='CASE-ROLLBACK')
        self.assertFalse(CaseProfile.objects.filter(workspace_id=self.workspace_id, code='CASE-ROLLBACK').exists())
        self.assertFalse(CaseDocumentMapping.objects.filter(workspace_id=self.workspace_id).exists())

    def test_unparsed_wrong_knowledge_and_unauthorized_documents_are_rejected(self):
        with self.assertRaises(AppApiException):
            self.register(self.registration_payload(self.pending_document.id), code='CASE-PENDING')
        with self.assertRaises(AppApiException):
            self.register(self.registration_payload(self.wrong_knowledge_document.id), code='CASE-WRONG-KB')
        with patch('opportunity.serializers.case.filter_authorized_ids', return_value=[]):
            with self.assertRaises(AppApiException):
                self.register(code='CASE-NO-PERMISSION')

    def test_available_documents_excludes_occupied_sources_and_keeps_own_bound_status(self):
        first = self.register(code='CASE-FIRST')
        first_case = CaseProfile.objects.get(id=first['id'])
        available = list_available_case_documents(self.workspace_id, user_id='manager-1')
        self.assertNotIn(str(self.ready_document.id), {item['id'] for item in available})

        own = list_available_case_documents(
            self.workspace_id, user_id='manager-1', case_id=str(first_case.id),
        )
        own_item = next(item for item in own if item['id'] == str(self.ready_document.id))
        self.assertTrue(own_item['is_bound'])

        with self.assertRaises(AppApiException):
            self.register(self.registration_payload(self.ready_document.id), code='CASE-SECOND')

    def test_utf8_create_read_edit_and_publish_preserves_name_and_mapping(self):
        result = self.register()
        self.assertEqual(result['name'], '某省政务统一运维—一期🚀')
        case = CaseProfile.objects.get(id=result['id'])
        self.assertEqual(CaseDocumentMapping.objects.filter(case=case, is_active=True).count(), 1)

        reader = CaseOperateSerializer(data={
            'workspace_id': self.workspace_id, 'case_id': str(case.id),
            'user_id': 'manager-1', 'is_manager': True,
        })
        self.assertEqual(reader.one()['name'], '某省政务统一运维—一期🚀')
        reader.update({
            **self.registration_payload(code='CASE-UTF8'),
            'name': '某省政务统一运维—一期（修订）🚀',
            # The existing mapping is retained when no new document is sent.
            'document_id': None,
        })
        for action in ('SUBMIT_REVIEW', 'APPROVE', 'PUBLISH'):
            CaseOperateSerializer(data={
                'workspace_id': self.workspace_id, 'case_id': str(case.id),
                'user_id': 'manager-1', 'is_manager': True,
            }).action({'action': action})
        case.refresh_from_db()
        self.assertEqual(case.name, '某省政务统一运维—一期（修订）🚀')
        self.assertEqual(case.status, CaseStatus.PUBLISHED)
        self.assertNotIn('�', case.name)
        self.ready_document.refresh_from_db()
        self.assertEqual((self.ready_document.meta.get('bia') or {}).get('publish_status'), 'published')


class CaseDocumentLockContractTests(SimpleTestCase):
    """Keep the document lock and occupied re-check in the same validator."""

    def test_mutating_validation_locks_document_row_before_occupied_check(self):
        document = SimpleNamespace(
            id='document-1', knowledge_id='knowledge-1', is_active=True, char_length=10,
            status='nnn2', meta={}, knowledge=SimpleNamespace(workspace_id='ws-lock'),
        )
        document_query = MagicMock()
        document_query.select_related.return_value = document_query
        document_query.select_for_update.return_value = document_query
        document_query.filter.return_value = document_query
        document_query.first.return_value = document
        mapping_query = MagicMock()
        mapping_query.filter.return_value = mapping_query
        mapping_query.exclude.return_value = mapping_query
        mapping_query.exists.return_value = False

        def query_set(model):
            from knowledge.models import Document as DocumentModel
            return document_query if model is DocumentModel else mapping_query

        with patch('opportunity.serializers.case.get_setting', return_value=SimpleNamespace(case_knowledge_id='knowledge-1')):
            with patch('opportunity.serializers.case.require_knowledge', return_value=SimpleNamespace(id='knowledge-1')):
                with patch('opportunity.serializers.case.filter_authorized_ids', return_value=['knowledge-1']):
                    with patch('opportunity.serializers.case.QuerySet', side_effect=query_set):
                        _validate_case_document_for_test()
        document_query.select_for_update.assert_called_once_with()

    @patch('opportunity.views.case.is_workspace_manage')
    def test_case_management_gate_is_manager_only(self, is_manager):
        request = SimpleNamespace(user=SimpleNamespace(id='user-1'))
        is_manager.return_value = False
        self.assertFalse(_is_manager(request, 'ws-lock'))
        is_manager.return_value = True
        self.assertTrue(_is_manager(request, 'ws-lock'))


def _validate_case_document_for_test():
    # Import lazily so the contract test can patch the module-level QuerySet.
    from opportunity.serializers.case import _validate_case_document

    return _validate_case_document(
        'ws-lock', 'document-1', user_id='manager-1', for_update=True,
    )
