# coding=utf-8
from django.test import SimpleTestCase

from opportunity.services.case_enhancement import apply_case_enhancement, run_case_enhancement


def candidate(status='FULL', version='1.0', score=80.0):
    return {
        'product_code': 'P1',
        'product_name': '产品一',
        'product_version': version,
        'score': score,
        'hard_constraint_failed': status == 'NO',
        'score_detail': {'requirement_score': 80, 'evidence_completeness': 80, 'case_score': 0},
        'match_items': [{'requirement_id': 'R1', 'status': status, 'evidence': []}],
        'case_references': [],
    }


def case_hit(version='1.0', similarity=0.8):
    return {
        'case_id': 'C1', 'case_code': 'CASE-001', 'case_name': '案例一',
        'knowledge_id': 'K1', 'document_id': 'D1', 'paragraph_id': 'PG1',
        'document_name': '案例一.md', 'document_version': '1.0', 'title': '场景',
        'content_excerpt': '脱敏后的案例摘要', 'similarity': similarity,
        'industry': '医疗', 'scenario': '统一监控', 'project_scale': {'devices': '1000+'},
        'outcomes': ['告警效率提升'], 'applicability_boundary': '需确认接口',
        'product_codes': ['P1'], 'product_versions': {'P1': version},
    }


class CaseEnhancementTests(SimpleTestCase):
    requirements = [{'id': 'R1', 'priority': 'must'}]

    def test_case_contribution_is_capped_at_ten_points(self):
        result = apply_case_enhancement([candidate()], self.requirements, [case_hit(similarity=1.0)])
        self.assertEqual(result[0]['score_detail']['case_score'], 10.0)
        self.assertEqual(result[0]['score'], 90.0)
        self.assertEqual(len(result[0]['case_references']), 1)

    def test_must_insufficient_is_not_improved_by_case(self):
        result = apply_case_enhancement(
            [candidate(status='INSUFFICIENT')], self.requirements, [case_hit()],
        )
        self.assertEqual(result[0]['score'], 80.0)
        self.assertEqual(result[0]['score_detail']['case_score'], 0.0)
        self.assertEqual(result[0]['score_detail']['case_score_blocked_reason'], 'MUST_INSUFFICIENT')

    def test_product_version_mismatch_is_reference_only(self):
        result = apply_case_enhancement([candidate(version='2.0')], self.requirements, [case_hit(version='1.0')])
        self.assertEqual(result[0]['score'], 80.0)
        self.assertFalse(result[0]['case_references'][0]['version_compatible'])
        self.assertEqual(result[0]['score_detail']['case_score_blocked_reason'], 'PRODUCT_VERSION_MISMATCH')

    def test_case_service_failure_degrades_without_losing_product_result(self):
        original = candidate()

        def failed_retrieve(**_kwargs):
            raise RuntimeError('case service unavailable')

        result, state = run_case_enhancement(
            workspace_id='ws-a', knowledge_id='K1', profile={}, candidates=[original],
            requirements=self.requirements, retrieve_func=failed_retrieve,
        )
        self.assertEqual(state['status'], 'DEGRADED')
        self.assertEqual(result[0]['score'], 80.0)
        self.assertEqual(result[0]['case_references'], [])

    def test_only_candidate_product_codes_are_sent_to_case_search(self):
        captured = {}

        def retrieve(**kwargs):
            captured.update(kwargs)
            return []

        _, state = run_case_enhancement(
            workspace_id='ws-a', knowledge_id='K1', profile={}, candidates=[candidate()],
            requirements=self.requirements, retrieve_func=retrieve,
        )
        self.assertEqual(captured['product_codes'], ['P1'])
        self.assertEqual(state['status'], 'NO_MATCH')
