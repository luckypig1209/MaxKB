# coding=utf-8
import json
import uuid
from pathlib import Path
from unittest.mock import patch

from django.test import TestCase

from common.exception.app_exception import AppApiException
from opportunity.models import (
    AnalysisStatus,
    DecisionAction,
    OpportunityAnalysis,
    OpportunityReport,
    OpportunitySetting,
    ProductProfile,
    ProductStatus,
)
from opportunity.services.analysis import _execute, confirm_analysis, create_analysis, run_analysis
from opportunity.services.progress import ProgressTracker, strip_progress
from opportunity.services.report import create_report_snapshot


SECRET_REQUIREMENT = '机密客户需求：全院统一监控且包含密钥 sk-not-a-real-key'
GOLDEN = json.loads(
    (Path(__file__).parent / 'fixtures' / 'vc206a_golden_snapshots.json').read_text(encoding='utf-8'),
)


SECRET_REQUIREMENT = '机密客户需求：全院统一监控且包含密钥 sk-not-a-real-key'


def profile_ok():
    return {
        'schema_version': '1.0',
        'customer_context': {'industry': '医疗', 'customer_type': None, 'region': None},
        'business_scenarios': ['医疗资源监控'],
        'pain_points': ['故障发现晚'],
        'requirements': [{
            'id': 'R-001',
            'description': '统一监控',
            'priority': 'must',
            'category': 'core_function',
            'source_text': '统一监控',
        }],
        'constraints': [],
        'excluded_conditions': [],
        'missing_information': [],
        'clarification_questions': [],
    }


def profile_need_clarification():
    data = profile_ok()
    data['clarification_questions'] = ['请补充接入设备数量']
    data['missing_information'] = ['设备规模']
    return data


def evidence_hit(product_code, paragraph_id, excerpt='支持统一监控能力', similarity=0.9):
    return {
        'paragraph_id': paragraph_id,
        'knowledge_id': 'k1',
        'document_id': 'd1',
        'document_name': f'{product_code}.md',
        'title': '能力说明',
        'content_excerpt': excerpt,
        'similarity': similarity,
        'document_version': '1.0',
        'product_code': product_code,
        'product_name': product_code,
        'allow_download': True,
    }


def match_full(_workspace_id, _llm_model_id, product, requirements, evidence_hits):
    evidence = [{
        'paragraph_id': evidence_hits[0]['paragraph_id'],
        'title': evidence_hits[0]['title'],
        'content_excerpt': evidence_hits[0]['content_excerpt'],
        'similarity': evidence_hits[0]['similarity'],
    }] if evidence_hits else []
    return [{
        'requirement_id': requirements[0]['id'],
        'status': 'FULL',
        'reason': '产品资料覆盖该需求',
        'evidence': evidence,
    }]


class AnalysisProgressRegressionTests(TestCase):
    workspace_id = 'ws-progress'

    def setUp(self):
        OpportunitySetting.objects.create(
            workspace_id=self.workspace_id,
            llm_model_id=uuid.uuid4(),
            product_knowledge_id=uuid.uuid4(),
            max_candidates=5,
        )
        ProductProfile.objects.create(
            workspace_id=self.workspace_id, code='P1', name='产品一', status=ProductStatus.ACTIVE,
        )
        ProductProfile.objects.create(
            workspace_id=self.workspace_id, code='P2', name='产品二', status=ProductStatus.ACTIVE,
        )

    def _analysis(self, key='progress-ok', requirement=SECRET_REQUIREMENT):
        return OpportunityAnalysis.objects.create(
            workspace_id=self.workspace_id,
            user_id='u1',
            idempotency_key=key,
            status=AnalysisStatus.ANALYZING,
            original_requirement=requirement,
        )

    def _run_success(self, analysis):
        retrieve_calls = []

        def retrieve(**kwargs):
            retrieve_calls.append(kwargs['question'])
            return [
                evidence_hit('P2', 'pg-p2'),
                evidence_hit('P1', 'pg-p1'),
            ]

        with patch('opportunity.services.requirement_extraction.extract_requirement_profile', return_value=profile_ok()), \
                patch('opportunity.services.analysis.retrieve_product_paragraphs', side_effect=retrieve), \
                patch('opportunity.services.analysis.match_product', side_effect=match_full):
            _execute(analysis)
        analysis.refresh_from_db()
        return analysis, retrieve_calls

    def test_mock_analysis_keeps_business_snapshot_and_records_timings(self):
        first, first_queries = self._run_success(self._analysis('progress-a'))
        second, second_queries = self._run_success(self._analysis('progress-b'))
        self.assertEqual(first_queries, second_queries)
        self.assertEqual(first_queries, [
            SECRET_REQUIREMENT,
            '统一监控',
            '医疗资源监控',
            '故障发现晚',
        ])
        self.assertEqual(strip_progress(first.result_snapshot), GOLDEN['success'])
        self.assertEqual(strip_progress(second.result_snapshot), GOLDEN['success'])
        self.assertEqual(
            [item['product_code'] for item in first.result_snapshot['candidates']],
            ['P1', 'P2'],
        )
        self.assertEqual(first.result_snapshot['candidates'][0]['score'], 100.0)
        self.assertEqual(first.result_snapshot['summary'], '已完成产品事实匹配')
        progress = first.result_snapshot['progress']
        self.assertEqual(progress['version'], 2)
        self.assertEqual(progress['state'], 'DONE')
        self.assertEqual(progress['percent'], 100)
        names = [item['name'] for item in progress['timings']]
        self.assertIn('extract_requirement', names)
        self.assertIn('retrieve_query', names)
        self.assertIn('match_product', names)
        self.assertIn('run_case_enhancement', names)
        self.assertIn('rank_candidates', names)
        self.assertGreaterEqual(progress['counters']['queries_done'], 2)
        self.assertEqual(progress['counters']['products_found'], 2)
        self.assertEqual(progress['counters']['products_matched'], 2)
        self.assertEqual(progress['counters']['match_model_calls'], 2)
        self.assertGreater(progress['counters']['requirement_chars'], 0)
        match_events = [item for item in progress['timings'] if item['name'] == 'match_product']
        self.assertTrue(all('prompt_chars' in item for item in match_events))
        self.assertTrue(all('content_excerpt' not in item for item in progress['timings']))
        serialized = str(progress)
        self.assertNotIn(SECRET_REQUIREMENT, serialized)
        self.assertNotIn('sk-not-a-real-key', serialized)

    def test_duplicate_queries_reuse_first_raw_query_with_attempt_metrics(self):
        profile = profile_ok()
        profile['requirements'][0]['description'] = 'Unified monitoring'
        profile['business_scenarios'] = [' unified   monitoring ']
        profile['pain_points'] = []
        analysis = self._analysis('progress-query-dedupe', requirement='Unified Monitoring')
        retrieve_calls = []

        def retrieve(**kwargs):
            retrieve_calls.append(kwargs['question'])
            return [evidence_hit('P1', 'pg-p1'), evidence_hit('P2', 'pg-p2')]

        with patch('opportunity.services.requirement_extraction.extract_requirement_profile', return_value=profile), \
                patch('opportunity.services.analysis.retrieve_product_paragraphs', side_effect=retrieve), \
                patch('opportunity.services.analysis.match_product', side_effect=match_full):
            _execute(analysis)
        analysis.refresh_from_db()

        # Every normalized duplicate uses the first raw query text; only one
        # backend search is made while the snapshot keeps the same evidence.
        self.assertEqual(retrieve_calls, ['Unified Monitoring'])
        counters = analysis.result_snapshot['progress']['counters']
        self.assertEqual(counters['raw_query_count'], 3)
        self.assertEqual(counters['unique_query_count'], 1)
        self.assertEqual(counters['cache_hit_count'], 2)
        self.assertEqual(counters['raw_evidence_count'], 6)
        self.assertEqual(counters['unique_paragraph_count'], 2)
        self.assertEqual(strip_progress(analysis.result_snapshot), GOLDEN['success'])

    def test_duplicate_paragraph_keeps_first_source_across_query_batches(self):
        profile = profile_ok()
        analysis = self._analysis('progress-evidence-first')
        retrieve_calls = []
        match_evidence = []

        def retrieve(**kwargs):
            retrieve_calls.append(kwargs['question'])
            if len(retrieve_calls) == 1:
                return [
                    evidence_hit('P1', 'pg-shared', excerpt='first source', similarity=0.2),
                    evidence_hit('P1', 'pg-first', excerpt='first other', similarity=0.9),
                ]
            return [
                evidence_hit('P1', 'pg-shared', excerpt='later source', similarity=0.99),
                evidence_hit('P1', 'pg-later', excerpt='later other', similarity=0.9),
            ]

        def match(_workspace_id, _llm_model_id, _product, _requirements, evidence):
            match_evidence.append([(item['paragraph_id'], item['content_excerpt']) for item in evidence])
            return match_full(_workspace_id, _llm_model_id, _product, _requirements, evidence)

        with patch('opportunity.services.requirement_extraction.extract_requirement_profile', return_value=profile), \
                patch('opportunity.services.analysis.retrieve_product_paragraphs', side_effect=retrieve), \
                patch('opportunity.services.analysis.match_product', side_effect=match):
            _execute(analysis)

        self.assertEqual(retrieve_calls, [
            SECRET_REQUIREMENT,
            '统一监控',
            '医疗资源监控',
            '故障发现晚',
        ])
        self.assertTrue(match_evidence)
        p1_evidence = next(
            item for item in match_evidence
            if any(paragraph_id == 'pg-shared' for paragraph_id, _ in item)
        )
        self.assertIn(('pg-shared', 'first source'), p1_evidence)
        self.assertNotIn(('pg-shared', 'later source'), p1_evidence)

    def test_clarification_progress_is_waiting_user(self):
        analysis = self._analysis('progress-clarify')
        with patch(
            'opportunity.services.requirement_extraction.extract_requirement_profile',
            return_value=profile_need_clarification(),
        ):
            _execute(analysis)
        analysis.refresh_from_db()
        self.assertEqual(analysis.status, AnalysisStatus.NEED_CLARIFICATION)
        progress = analysis.result_snapshot['progress']
        self.assertEqual(progress['state'], 'WAITING_USER')
        self.assertEqual(progress['current'], 'PARSE')
        self.assertEqual(analysis.result_snapshot['candidates'], [])
        self.assertEqual(strip_progress(analysis.result_snapshot), GOLDEN['clarification'])
        self.assertTrue(any(item['name'] == 'extract_requirement' for item in progress['timings']))

    def test_failed_analysis_keeps_timings(self):
        analysis = self._analysis('progress-fail')
        with patch(
            'opportunity.services.requirement_extraction.extract_requirement_profile',
            side_effect=AppApiException(500, '模型调用失败'),
        ):
            run_analysis(str(analysis.id))
        analysis.refresh_from_db()
        self.assertEqual(analysis.status, AnalysisStatus.FAILED)
        progress = analysis.result_snapshot['progress']
        self.assertEqual(progress['state'], 'FAILED')
        self.assertTrue(any(item['name'] == 'extract_requirement' for item in progress['timings']))
        self.assertGreaterEqual(progress['elapsed_ms'], 0)

    def test_timing_logs_do_not_contain_requirement_or_evidence(self):
        analysis = self._analysis('progress-log')
        with patch('opportunity.services.progress.logger.info') as info:
            self._run_success(analysis)
        joined = ' '.join(str(call.args) + str(call.kwargs) for call in info.call_args_list)
        self.assertIn('opportunity_timing', joined)
        self.assertIn(str(analysis.id), joined)
        self.assertNotIn(SECRET_REQUIREMENT, joined)
        self.assertNotIn('支持统一监控能力', joined)
        self.assertNotIn('sk-not-a-real-key', joined)

    def test_no_candidates_matches_golden(self):
        analysis = self._analysis('progress-empty')
        with patch('opportunity.services.requirement_extraction.extract_requirement_profile', return_value=profile_ok()), \
                patch('opportunity.services.analysis.retrieve_product_paragraphs', return_value=[]), \
                patch('opportunity.services.analysis.match_product', side_effect=match_full):
            _execute(analysis)
        analysis.refresh_from_db()
        self.assertEqual(strip_progress(analysis.result_snapshot), GOLDEN['no_candidates'])

    def test_case_degraded_matches_golden(self):
        setting = OpportunitySetting.objects.get(workspace_id=self.workspace_id)
        setting.case_knowledge_id = uuid.uuid4()
        setting.save(update_fields=['case_knowledge_id', 'update_time'])
        analysis = self._analysis('progress-degraded')
        with patch('opportunity.services.requirement_extraction.extract_requirement_profile', return_value=profile_ok()), \
                patch('opportunity.services.analysis.retrieve_product_paragraphs', side_effect=lambda **kwargs: [
                    evidence_hit('P2', 'pg-p2'), evidence_hit('P1', 'pg-p1'),
                ]), \
                patch('opportunity.services.analysis.match_product', side_effect=match_full), \
                patch('opportunity.services.case_enhancement.retrieve_case_paragraphs', side_effect=RuntimeError('case down')):
            _execute(analysis)
        analysis.refresh_from_db()
        self.assertEqual(strip_progress(analysis.result_snapshot), GOLDEN['case_degraded'])

    def test_done_is_written_after_report(self):
        analysis = self._analysis('progress-report-order')
        seen = {}

        def delayed_report(item, user_id=None):
            seen['state'] = ((item.result_snapshot or {}).get('progress') or {}).get('state')
            seen['status'] = item.status
            seen['percent'] = ((item.result_snapshot or {}).get('progress') or {}).get('percent')
            return create_report_snapshot(item, user_id)

        with patch('opportunity.services.requirement_extraction.extract_requirement_profile', return_value=profile_ok()), \
                patch('opportunity.services.analysis.retrieve_product_paragraphs', return_value=[
                    evidence_hit('P2', 'pg-p2'), evidence_hit('P1', 'pg-p1'),
                ]), \
                patch('opportunity.services.analysis.match_product', side_effect=match_full), \
                patch('opportunity.services.analysis.create_report_snapshot', side_effect=delayed_report):
            _execute(analysis)
        analysis.refresh_from_db()
        self.assertEqual(seen['state'], 'DONE')
        self.assertEqual(seen['status'], AnalysisStatus.WAITING_CONFIRMATION)
        self.assertEqual(seen['percent'], 100)
        self.assertEqual(analysis.result_snapshot['progress']['state'], 'DONE')
        self.assertEqual(analysis.status, AnalysisStatus.WAITING_CONFIRMATION)
        report = OpportunityReport.objects.get(analysis=analysis, is_current=True)
        self.assertEqual(report.snapshot['status'], AnalysisStatus.WAITING_CONFIRMATION)
        self.assertEqual(report.snapshot['result']['progress']['state'], 'DONE')
        self.assertEqual(report.snapshot['result']['progress']['percent'], 100)
        self.assertEqual(report.snapshot['result']['candidates'], analysis.result_snapshot['candidates'])
        self.assertEqual(report.snapshot['result']['summary'], analysis.result_snapshot['summary'])
        self.assertEqual(strip_progress(analysis.result_snapshot), GOLDEN['success'])

    def test_report_failure_never_exposes_done(self):
        analysis = self._analysis('progress-report-fail')
        with patch('opportunity.services.requirement_extraction.extract_requirement_profile', return_value=profile_ok()), \
                patch('opportunity.services.analysis.retrieve_product_paragraphs', return_value=[
                    evidence_hit('P2', 'pg-p2'), evidence_hit('P1', 'pg-p1'),
                ]), \
                patch('opportunity.services.analysis.match_product', side_effect=match_full), \
                patch('opportunity.services.analysis.create_report_snapshot', side_effect=RuntimeError('report boom')):
            run_analysis(str(analysis.id))
        analysis.refresh_from_db()
        self.assertEqual(analysis.status, AnalysisStatus.FAILED)
        self.assertNotEqual(analysis.result_snapshot['progress']['state'], 'DONE')
        self.assertEqual(analysis.result_snapshot['progress']['state'], 'FAILED')
        self.assertFalse(OpportunityReport.objects.filter(analysis=analysis).exists())

    def test_retrieve_failure_records_timing_without_completed_unit(self):
        analysis = self._analysis('progress-retrieve-fail')
        with patch('opportunity.services.requirement_extraction.extract_requirement_profile', return_value=profile_ok()), \
                patch('opportunity.services.analysis.retrieve_product_paragraphs', side_effect=RuntimeError('search down')):
            run_analysis(str(analysis.id))
        analysis.refresh_from_db()
        progress = analysis.result_snapshot['progress']
        events = [item for item in progress['timings'] if item['name'] == 'retrieve_query']
        self.assertTrue(events)
        self.assertEqual(events[0]['outcome'], 'FAILED')
        self.assertGreaterEqual(progress['counters']['query_attempts'], 1)
        self.assertEqual(progress['counters']['queries_done'], 0)

    def test_match_failure_counts_attempt_not_success(self):
        analysis = self._analysis('progress-match-fail')
        with patch('opportunity.services.requirement_extraction.extract_requirement_profile', return_value=profile_ok()), \
                patch('opportunity.services.analysis.retrieve_product_paragraphs', return_value=[
                    evidence_hit('P1', 'pg-p1'),
                ]), \
                patch('opportunity.services.analysis.match_product', side_effect=RuntimeError('match down')):
            run_analysis(str(analysis.id))
        analysis.refresh_from_db()
        progress = analysis.result_snapshot['progress']
        events = [item for item in progress['timings'] if item['name'] == 'match_product']
        self.assertTrue(events)
        self.assertEqual(events[0]['outcome'], 'FAILED')
        self.assertGreaterEqual(progress['counters']['match_model_attempts'], 1)
        self.assertEqual(progress['counters']['products_matched'], 0)
        self.assertEqual(progress['counters']['match_model_calls'], 0)

    @patch('opportunity.tasks.analyze_opportunity.delay')
    def test_create_analysis_writes_parse_without_worker(self, _delay):
        analysis = create_analysis(self.workspace_id, 'u1', 'create-parse', '需要统一监控')
        analysis.refresh_from_db()
        progress = analysis.result_snapshot['progress']
        self.assertEqual(analysis.status, AnalysisStatus.ANALYZING)
        self.assertEqual(progress['current'], 'PARSE')
        self.assertEqual(progress['state'], 'RUNNING')
        self.assertEqual(progress['percent'], 0)

    def test_profile_is_readable_before_retrieve_finishes(self):
        analysis = self._analysis('progress-profile-early')
        seen = {}

        def retrieve(**kwargs):
            analysis.refresh_from_db()
            seen['profile'] = analysis.requirement_profile
            seen['current'] = ((analysis.result_snapshot or {}).get('progress') or {}).get('current')
            return []

        with patch('opportunity.services.requirement_extraction.extract_requirement_profile', return_value=profile_ok()), \
                patch('opportunity.services.analysis.retrieve_product_paragraphs', side_effect=retrieve), \
                patch('opportunity.services.analysis.match_product', side_effect=match_full):
            _execute(analysis)
        self.assertEqual(seen['profile']['requirements'][0]['id'], 'R-001')
        self.assertEqual(seen['current'], 'RETRIEVE')

    def test_retrieve_and_match_progress_exposes_xy_counters(self):
        analysis = self._analysis('progress-xy')
        retrieve_details = []
        match_details = []

        def retrieve(**kwargs):
            analysis.refresh_from_db()
            retrieve_details.append(analysis.result_snapshot['progress']['detail'])
            return [evidence_hit('P2', 'pg-p2'), evidence_hit('P1', 'pg-p1')]

        def match(workspace_id, llm_model_id, product, requirements, evidence):
            analysis.refresh_from_db()
            match_details.append(analysis.result_snapshot['progress']['detail'])
            return match_full(workspace_id, llm_model_id, product, requirements, evidence)

        with patch('opportunity.services.requirement_extraction.extract_requirement_profile', return_value=profile_ok()), \
                patch('opportunity.services.analysis.retrieve_product_paragraphs', side_effect=retrieve), \
                patch('opportunity.services.analysis.match_product', side_effect=match):
            _execute(analysis)
        self.assertTrue(any('1/' in item for item in retrieve_details))
        self.assertTrue(any('2/' in item for item in retrieve_details))
        self.assertTrue(any('1/' in item and '核验' in item for item in match_details))
        self.assertTrue(any('2/' in item and '核验' in item for item in match_details))
        analysis.refresh_from_db()
        counters = analysis.result_snapshot['progress']['counters']
        self.assertGreaterEqual(counters['queries_done'], 2)
        self.assertEqual(counters['products_matched'], 2)

    def test_cancel_during_retrieve_stops_later_units(self):
        analysis = self._analysis('progress-cancel-retrieve')
        retrieve_calls = []
        match_mock = patch('opportunity.services.analysis.match_product')
        match = match_mock.start()
        self.addCleanup(match_mock.stop)

        def retrieve(**kwargs):
            retrieve_calls.append(kwargs['question'])
            if len(retrieve_calls) == 1:
                confirm_analysis(analysis, DecisionAction.CANCEL, reason='stop', user_id='u1')
            return [evidence_hit('P1', 'pg-p1')]

        with patch('opportunity.services.requirement_extraction.extract_requirement_profile', return_value=profile_ok()), \
                patch('opportunity.services.analysis.retrieve_product_paragraphs', side_effect=retrieve):
            _execute(analysis)
        analysis.refresh_from_db()
        self.assertEqual(len(retrieve_calls), 1)
        match.assert_not_called()
        self.assertEqual(analysis.status, AnalysisStatus.CLOSED)
        self.assertEqual(analysis.result_snapshot['progress']['state'], 'CANCELLED')
        self.assertEqual(analysis.result_snapshot['decision']['action'], 'CANCEL')
        statuses = [item.snapshot.get('status') for item in OpportunityReport.objects.filter(analysis=analysis)]
        self.assertNotIn(AnalysisStatus.WAITING_CONFIRMATION, statuses)

    def test_cancel_during_match_stops_later_units(self):
        analysis = self._analysis('progress-cancel-match')
        match_calls = []

        def match(workspace_id, llm_model_id, product, requirements, evidence):
            match_calls.append(product.code)
            if len(match_calls) == 1:
                confirm_analysis(analysis, DecisionAction.CANCEL, reason='stop', user_id='u1')
            return match_full(workspace_id, llm_model_id, product, requirements, evidence)

        with patch('opportunity.services.requirement_extraction.extract_requirement_profile', return_value=profile_ok()), \
                patch('opportunity.services.analysis.retrieve_product_paragraphs', return_value=[
                    evidence_hit('P2', 'pg-p2'), evidence_hit('P1', 'pg-p1'),
                ]), \
                patch('opportunity.services.analysis.match_product', side_effect=match):
            _execute(analysis)
        analysis.refresh_from_db()
        self.assertEqual(len(match_calls), 1)
        self.assertEqual(analysis.status, AnalysisStatus.CLOSED)
        self.assertEqual(analysis.result_snapshot['progress']['state'], 'CANCELLED')

    def test_cancel_before_final_transaction_skips_success_report(self):
        analysis = self._analysis('progress-cancel-final')
        from opportunity.services import analysis as analysis_mod
        real_finalize = analysis_mod._finalize_success

        def wrapped(item, tracker, snapshot_fields):
            confirm_analysis(item, DecisionAction.CANCEL, reason='stop', user_id='u1')
            return real_finalize(item, tracker, snapshot_fields)

        with patch('opportunity.services.requirement_extraction.extract_requirement_profile', return_value=profile_ok()), \
                patch('opportunity.services.analysis.retrieve_product_paragraphs', return_value=[
                    evidence_hit('P2', 'pg-p2'), evidence_hit('P1', 'pg-p1'),
                ]), \
                patch('opportunity.services.analysis.match_product', side_effect=match_full), \
                patch.object(analysis_mod, '_finalize_success', side_effect=wrapped):
            _execute(analysis)
        analysis.refresh_from_db()
        self.assertEqual(analysis.status, AnalysisStatus.CLOSED)
        self.assertEqual(analysis.result_snapshot['progress']['state'], 'CANCELLED')
        statuses = [item.snapshot.get('status') for item in OpportunityReport.objects.filter(analysis=analysis)]
        self.assertNotIn(AnalysisStatus.WAITING_CONFIRMATION, statuses)

    def test_case_status_details_are_flushed_before_rank(self):
        analysis = self._analysis('progress-case-status')
        seen = []
        real_begin = ProgressTracker.begin

        def wrapped(self, stage, detail, force=True):
            if stage == 'RANK':
                seen.append(self.detail)
            return real_begin(self, stage, detail, force=force)

        with patch('opportunity.services.requirement_extraction.extract_requirement_profile', return_value=profile_ok()), \
                patch('opportunity.services.analysis.retrieve_product_paragraphs', return_value=[
                    evidence_hit('P2', 'pg-p2'), evidence_hit('P1', 'pg-p1'),
                ]), \
                patch('opportunity.services.analysis.match_product', side_effect=match_full), \
                patch.object(ProgressTracker, 'begin', wrapped):
            _execute(analysis)
        analysis.refresh_from_db()
        self.assertTrue(any('未配置案例知识库' in item for item in seen))
        self.assertEqual(analysis.result_snapshot['case_enhancement']['status'], 'NOT_CONFIGURED')

    def test_case_degraded_detail_is_observable(self):
        setting = OpportunitySetting.objects.get(workspace_id=self.workspace_id)
        setting.case_knowledge_id = uuid.uuid4()
        setting.save(update_fields=['case_knowledge_id', 'update_time'])
        analysis = self._analysis('progress-case-degraded-detail')
        seen = []
        real_begin = ProgressTracker.begin

        def wrapped(self, stage, detail, force=True):
            if stage == 'RANK':
                seen.append(self.detail)
            return real_begin(self, stage, detail, force=force)

        with patch('opportunity.services.requirement_extraction.extract_requirement_profile', return_value=profile_ok()), \
                patch('opportunity.services.analysis.retrieve_product_paragraphs', return_value=[
                    evidence_hit('P2', 'pg-p2'), evidence_hit('P1', 'pg-p1'),
                ]), \
                patch('opportunity.services.analysis.match_product', side_effect=match_full), \
                patch('opportunity.services.case_enhancement.retrieve_case_paragraphs', side_effect=RuntimeError('case down')), \
                patch.object(ProgressTracker, 'begin', wrapped):
            _execute(analysis)
        self.assertTrue(any('已降级' in item for item in seen))
        analysis.refresh_from_db()
        self.assertEqual(analysis.result_snapshot['case_enhancement']['status'], 'DEGRADED')
