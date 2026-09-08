# coding=utf-8
from django.test import SimpleTestCase

from opportunity.models import AnalysisStatus
from opportunity.services.scoring import (
    apply_ranking,
    calculate_evidence_completeness,
    calculate_requirement_score,
    calculate_total_score,
    hard_constraint_failed,
    recommendation_level,
)
from opportunity.services.state_machine import can_transit
from opportunity.services.knowledge_metadata import is_document_retrievable
from opportunity.services.json_utils import extract_json_object


class DummyDocument:
    def __init__(self, is_active=True, meta=None):
        self.is_active = is_active
        self.meta = meta or {}


class ScoringTests(SimpleTestCase):
    def setUp(self):
        self.requirements = [
            {'id': 'R-001', 'priority': 'must'},
            {'id': 'R-002', 'priority': 'should'},
            {'id': 'R-003', 'priority': 'nice_to_have'},
        ]

    def test_must_no_is_hard_constraint(self):
        items = [
            {'requirement_id': 'R-001', 'status': 'NO', 'evidence': []},
            {'requirement_id': 'R-002', 'status': 'FULL', 'evidence': [{'paragraph_id': 'p1'}]},
            {'requirement_id': 'R-003', 'status': 'FULL', 'evidence': [{'paragraph_id': 'p2'}]},
        ]
        self.assertTrue(hard_constraint_failed(self.requirements, items))
        self.assertEqual(recommendation_level(self.requirements, items, True), 'NOT_RECOMMENDED')

    def test_insufficient_does_not_score(self):
        items = [
            {'requirement_id': 'R-001', 'status': 'INSUFFICIENT', 'evidence': []},
            {'requirement_id': 'R-002', 'status': 'INSUFFICIENT', 'evidence': []},
            {'requirement_id': 'R-003', 'status': 'INSUFFICIENT', 'evidence': []},
        ]
        self.assertEqual(calculate_requirement_score(self.requirements, items), 0.0)

    def test_duplicate_evidence_not_double_counted_in_completeness(self):
        items = [
            {'requirement_id': 'R-001', 'status': 'FULL', 'evidence': [{'paragraph_id': 'p1'}]},
            {'requirement_id': 'R-002', 'status': 'PARTIAL', 'evidence': [{'paragraph_id': 'p1'}]},
            {'requirement_id': 'R-003', 'status': 'INSUFFICIENT', 'evidence': []},
        ]
        self.assertEqual(calculate_evidence_completeness(items), 66.7)

    def test_total_score_formula(self):
        self.assertEqual(calculate_total_score(80, 100), 82.0)

    def test_stable_sort(self):
        candidates = [
            {'product_code': 'B', 'score': 80, 'score_detail': {'evidence_completeness': 100}, 'hard_constraint_failed': False},
            {'product_code': 'A', 'score': 80, 'score_detail': {'evidence_completeness': 100}, 'hard_constraint_failed': False},
            {'product_code': 'C', 'score': 90, 'score_detail': {'evidence_completeness': 50}, 'hard_constraint_failed': True},
        ]
        top, excluded = apply_ranking(candidates, max_candidates=3)
        self.assertEqual([item['product_code'] for item in top], ['A', 'B'])
        self.assertEqual(excluded[0]['product_code'], 'C')

    def test_zero_score_not_shown_in_top(self):
        candidates = [
            {'product_code': 'YIGUAN', 'score': 63.1, 'hard_constraint_failed': False},
            {'product_code': 'YISHI', 'score': 62.9, 'hard_constraint_failed': False},
            {'product_code': 'YIJU', 'score': 0, 'hard_constraint_failed': False},
        ]
        top, excluded = apply_ranking(candidates, max_candidates=3)
        self.assertEqual([item['product_code'] for item in top], ['YIGUAN', 'YISHI'])
        self.assertEqual(excluded[0]['product_code'], 'YIJU')
        self.assertEqual(excluded[0].get('exclude_reason'), 'ZERO_SCORE')
        self.assertIsNone(excluded[0].get('rank'))

    def test_partial_cannot_be_recommended(self):
        items = [
            {'requirement_id': 'R-001', 'status': 'FULL', 'evidence': [{'paragraph_id': 'p1'}]},
            {'requirement_id': 'R-002', 'status': 'PARTIAL', 'evidence': [{'paragraph_id': 'p2'}]},
            {'requirement_id': 'R-003', 'status': 'FULL', 'evidence': [{'paragraph_id': 'p3'}]},
        ]
        self.assertEqual(recommendation_level(self.requirements, items, False), 'TECHNICAL_CONFIRMATION')


class StateMachineTests(SimpleTestCase):
    def test_allowed_and_illegal(self):
        self.assertTrue(can_transit(AnalysisStatus.ANALYZING, AnalysisStatus.NEED_CLARIFICATION))
        self.assertTrue(can_transit(AnalysisStatus.NEED_CLARIFICATION, AnalysisStatus.ANALYZING))
        self.assertTrue(can_transit(AnalysisStatus.FAILED, AnalysisStatus.ANALYZING))
        self.assertTrue(can_transit(AnalysisStatus.WAITING_CONFIRMATION, AnalysisStatus.CONFIRMED))
        self.assertFalse(can_transit(AnalysisStatus.CONFIRMED, AnalysisStatus.ANALYZING))
        self.assertFalse(can_transit(AnalysisStatus.WAITING_CONFIRMATION, AnalysisStatus.NEED_CLARIFICATION))


class MetadataTests(SimpleTestCase):
    def test_unpublished_and_inactive_not_retrievable(self):
        published = DummyDocument(meta={'bia': {
            'asset_type': 'product', 'product_code': 'YIGUAN', 'publish_status': 'published'
        }})
        draft = DummyDocument(meta={'bia': {
            'asset_type': 'product', 'product_code': 'YIGUAN', 'publish_status': 'draft'
        }})
        inactive = DummyDocument(is_active=False, meta={'bia': {
            'asset_type': 'product', 'product_code': 'YIGUAN', 'publish_status': 'published'
        }})
        missing_code = DummyDocument(meta={'bia': {'asset_type': 'product', 'publish_status': 'published'}})
        self.assertTrue(is_document_retrievable(published))
        self.assertFalse(is_document_retrievable(draft))
        self.assertFalse(is_document_retrievable(inactive))
        self.assertFalse(is_document_retrievable(missing_code))


class JsonUtilsTests(SimpleTestCase):
    def test_parse_markdown_json(self):
        text = '```json\n{"schema_version": "1.0", "ok": true}\n```'
        self.assertEqual(extract_json_object(text)['ok'], True)
