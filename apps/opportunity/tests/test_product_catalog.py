import uuid
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from knowledge.models import Document, Knowledge, KnowledgeFolder
from opportunity.models import OpportunitySetting, ProductProfile, ProductStatus
from opportunity.serializers.product import _matches_product_filters, _visible_meta
from opportunity.services.candidate_aggregation import aggregate_by_product
from opportunity.services.knowledge_retrieval import retrieve_product_paragraphs
from opportunity.views.product import _can_view_product_support


class ProductCatalogPrivacyTests(SimpleTestCase):
    def test_non_manager_metadata_removes_support_contacts(self):
        meta = {
            'source': 'phase1_catalog',
            'support': {'manager': '张永强', 'phone': '17768141106'},
            'phone': '17768141106',
            'version': '1.0',
        }
        visible = _visible_meta(meta, include_support=False)
        self.assertNotIn('support', visible)
        self.assertNotIn('phone', visible)
        self.assertEqual(visible['version'], '1.0')

    def test_manager_metadata_retains_support_contacts(self):
        support = {'manager': '张永强', 'phone': '17768141106'}
        self.assertEqual(_visible_meta({'support': support}, include_support=True)['support'], support)

    def test_unknown_readiness_filter_does_not_match_pending(self):
        product = SimpleNamespace(
            code='PENDING', name='待补资料产品', aliases=['待补'], product_line='产品线',
        )
        department = {
            'owner_department_code': 'DEPT',
            'owner_department_name': '部门',
        }
        self.assertFalse(_matches_product_filters(product, department, {'knowledge_status': 'unexpected'}, False))
        self.assertTrue(_matches_product_filters(product, department, {'knowledge_status': 'PENDING'}, False))

    @patch('opportunity.views.product.is_workspace_manage')
    def test_product_api_gate_only_allows_workspace_manager_support(self, is_manager):
        request = SimpleNamespace(user=SimpleNamespace(id='user-1'))
        is_manager.return_value = False
        self.assertFalse(_can_view_product_support(request, 'workspace-1'))
        is_manager.return_value = True
        self.assertTrue(_can_view_product_support(request, 'workspace-1'))


class ProductReadinessRetrievalTests(TestCase):
    workspace_id = 'catalog-readiness'

    def setUp(self):
        folder = KnowledgeFolder.objects.create(id=f'{self.workspace_id}-folder', name='产品资料',
                                                 workspace_id=self.workspace_id)
        self.knowledge = Knowledge.objects.create(
            name='产品资料', desc='', workspace_id=self.workspace_id, folder=folder,
        )
        OpportunitySetting.objects.create(
            workspace_id=self.workspace_id,
            product_knowledge_id=self.knowledge.id,
        )
        self.ready_product = ProductProfile.objects.create(
            workspace_id=self.workspace_id, code='READY', name='资料已就绪', status=ProductStatus.ACTIVE,
        )
        self.pending_product = ProductProfile.objects.create(
            workspace_id=self.workspace_id, code='PENDING', name='资料未就绪', status=ProductStatus.ACTIVE,
        )
        self.ready_document = Document.objects.create(
            knowledge=self.knowledge,
            name='ready.md',
            char_length=10,
            meta={'bia': {
                'asset_type': 'product', 'product_code': 'READY', 'publish_status': 'published',
                'document_version': '1.0',
            }},
        )
        self.pending_document = Document.objects.create(
            knowledge=self.knowledge,
            name='pending.md',
            char_length=10,
            meta={},
        )

    @patch('opportunity.services.knowledge_retrieval.search_knowledge')
    def test_unbound_product_hit_is_filtered_before_candidate_aggregation(self, search):
        search.return_value = [
            {
                'id': str(uuid.uuid4()), 'knowledge_id': str(self.knowledge.id),
                'document_id': str(self.pending_document.id), 'content': 'pending',
                'title': 'pending', 'similarity': 0.99,
            },
            {
                'id': str(uuid.uuid4()), 'knowledge_id': str(self.knowledge.id),
                'document_id': str(self.ready_document.id), 'content': 'ready',
                'title': 'ready', 'similarity': 0.80,
            },
        ]
        hits = retrieve_product_paragraphs(
            self.workspace_id, self.knowledge.id, '产品资料', 'blend', 20, 0.3,
        )
        self.assertEqual([item['product_code'] for item in hits], ['READY'])
        candidates = aggregate_by_product(self.workspace_id, hits)
        self.assertEqual(set(candidates), {'READY'})
