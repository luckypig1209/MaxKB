# coding=utf-8
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from opportunity.models import AnalysisStatus, OpportunityAnalysis
from opportunity.serializers.analysis import analysis_to_dict
from opportunity.services.progress import (
    FLUSH_INTERVAL_SECONDS,
    PROGRESS_VERSION,
    ProgressTracker,
    evidence_text_metrics,
    maybe_start_new_attempt,
    normalize_progress,
    requirement_text_metrics,
    start_new_attempt,
    strip_progress,
)


class FakeAnalysis:
    def __init__(self, snapshot=None):
        self.id = 'ana-fake'
        self.result_snapshot = snapshot or {}
        self.save_calls = 0
        self.last_update_fields = None

    def save(self, update_fields=None):
        self.save_calls += 1
        self.last_update_fields = update_fields


class ProgressProtocolTests(SimpleTestCase):
    def test_v2_payload_contains_required_fields(self):
        tracker = ProgressTracker(FakeAnalysis())
        tracker.begin('PARSE', '正在把客户需求拆成可匹配的能力项')
        payload = tracker.payload()
        self.assertEqual(payload['version'], PROGRESS_VERSION)
        self.assertEqual(payload['state'], 'RUNNING')
        self.assertEqual(payload['current'], 'PARSE')
        self.assertEqual(payload['index'], 1)
        self.assertEqual(payload['total'], 5)
        self.assertLess(payload['percent'], 100)
        self.assertIn('completed_units', payload)
        self.assertIn('total_units', payload)
        self.assertIn('started_at', payload)
        self.assertIn('last_updated_at', payload)
        self.assertIn('elapsed_ms', payload)
        self.assertEqual(len(payload['steps']), 5)
        self.assertEqual(payload['steps'][0]['status'], 'active')

    def test_percent_uses_real_units_and_never_decreases(self):
        tracker = ProgressTracker(FakeAnalysis())
        tracker.begin('PARSE', 'parse')
        tracker.add_completed(1)
        first = tracker.percent
        self.assertGreater(first, 0)
        tracker.set_totals(total_units=20)
        self.assertGreaterEqual(tracker.percent, first)
        tracker.add_completed(5)
        self.assertGreaterEqual(tracker.percent, first)
        tracker.complete('分析完成')
        self.assertEqual(tracker.percent, 100)
        self.assertEqual(tracker.payload()['current'], 'DONE')
        self.assertEqual(tracker.payload()['state'], 'DONE')
        self.assertTrue(all(step['status'] == 'done' for step in tracker.payload()['steps']))

    def test_waiting_user_marks_parse_done_without_finishing_analysis(self):
        tracker = ProgressTracker(FakeAnalysis())
        tracker.add_completed(1)
        payload = tracker.waiting_user('需求已拆解，请补充下面的关键参数后再继续匹配产品')
        self.assertEqual(payload['state'], 'WAITING_USER')
        self.assertEqual(payload['current'], 'PARSE')
        self.assertEqual(payload['steps'][0]['status'], 'done')
        self.assertEqual(payload['steps'][1]['status'], 'pending')
        self.assertLess(payload['percent'], 100)

    def test_same_stage_flush_is_throttled_unless_forced(self):
        analysis = FakeAnalysis()
        tracker = ProgressTracker(analysis)
        clock = {'t': 0.0}

        with patch('opportunity.services.progress.time.monotonic', side_effect=lambda: clock['t']):
            tracker.begin('RETRIEVE', 'q1')
            first_saves = analysis.save_calls
            clock['t'] = FLUSH_INTERVAL_SECONDS - 0.2
            tracker.detail = 'q2'
            tracker.flush(force=False)
            self.assertEqual(analysis.save_calls, first_saves)
            tracker.flush(force=True)
            self.assertEqual(analysis.save_calls, first_saves + 1)
            clock['t'] = clock['t'] + FLUSH_INTERVAL_SECONDS + 0.05
            tracker.flush(force=False)
            self.assertEqual(analysis.save_calls, first_saves + 2)

    def test_timings_drop_long_text_and_keep_product_code(self):
        tracker = ProgressTracker(FakeAnalysis())
        tracker.record_event(
            'MATCH', 'match_product', 12,
            product_code='YIGUAN',
            excerpt='这段证据正文不应进入进度快照' * 8,
            prompt_chars=128,
        )
        event = tracker.timings[-1]
        self.assertEqual(event['product_code'], 'YIGUAN')
        self.assertEqual(event['prompt_chars'], 128)
        self.assertNotIn('excerpt', event)
        self.assertNotIn('这段证据正文不应进入进度快照', str(event))

    def test_record_event_uses_allowlist_and_drops_short_secrets(self):
        tracker = ProgressTracker(FakeAnalysis())
        tracker.record_event(
            'MATCH', 'match_product', 9,
            product_code='YIGUAN',
            outcome='SUCCESS',
            token='sk-short',
            secret='abc',
            excerpt='短证据',
            query_index=2,
        )
        event = tracker.timings[-1]
        self.assertEqual(event['product_code'], 'YIGUAN')
        self.assertEqual(event['outcome'], 'SUCCESS')
        self.assertEqual(event['query_index'], 2)
        self.assertNotIn('token', event)
        self.assertNotIn('secret', event)
        self.assertNotIn('excerpt', event)

    def test_normalize_legacy_progress_keeps_old_fields(self):
        legacy = {
            'current': 'MATCH',
            'detail': '正在对照产品',
            'index': 3,
            'total': 5,
            'steps': [
                {'key': 'PARSE', 'label': '解析客户需求', 'status': 'done'},
                {'key': 'RETRIEVE', 'label': '检索产品知识库', 'status': 'done'},
                {'key': 'MATCH', 'label': '对照产品资料匹配', 'status': 'active'},
                {'key': 'CASE', 'label': '检索相似案例', 'status': 'pending'},
                {'key': 'RANK', 'label': '评分排序并生成结论', 'status': 'pending'},
            ],
        }
        payload = normalize_progress(legacy)
        self.assertEqual(payload['version'], 1)
        self.assertEqual(payload['state'], 'RUNNING')
        self.assertEqual(payload['current'], 'MATCH')
        self.assertEqual(payload['detail'], '正在对照产品')
        self.assertGreater(payload['percent'], 0)
        self.assertLess(payload['percent'], 100)
        self.assertEqual(payload['completed_units'], 2)
        self.assertEqual(payload['total_units'], 5)

    def test_normalize_legacy_clarification_is_waiting_user(self):
        payload = normalize_progress({
            'current': 'PARSE',
            'detail': '需求已拆解，请补充下面的关键参数后再继续匹配产品',
            'index': 1,
            'total': 5,
            'steps': [
                {'key': 'PARSE', 'label': '解析客户需求', 'status': 'done'},
                {'key': 'RETRIEVE', 'label': '检索产品知识库', 'status': 'pending'},
            ],
        })
        self.assertEqual(payload['state'], 'WAITING_USER')
        self.assertEqual(payload['current'], 'PARSE')
        self.assertEqual(payload['completed_units'], 1)
        self.assertEqual(payload['total_units'], 5)
        self.assertLess(payload['percent'], 100)

    def test_normalize_legacy_done_uses_full_units(self):
        payload = normalize_progress({
            'current': 'DONE',
            'detail': '分析完成',
            'index': 5,
            'total': 5,
            'steps': [
                {'key': 'PARSE', 'label': '解析客户需求', 'status': 'done'},
                {'key': 'RETRIEVE', 'label': '检索产品知识库', 'status': 'done'},
                {'key': 'MATCH', 'label': '对照产品资料匹配', 'status': 'done'},
                {'key': 'CASE', 'label': '检索相似案例', 'status': 'done'},
                {'key': 'RANK', 'label': '评分排序并生成结论', 'status': 'done'},
            ],
        })
        self.assertEqual(payload['state'], 'DONE')
        self.assertEqual(payload['percent'], 100)
        self.assertEqual(payload['completed_units'], 5)
        self.assertEqual(payload['total_units'], 5)

    def test_strip_progress_leaves_business_fields(self):
        snapshot = {
            'candidates': [{'product_code': 'P1', 'score': 90}],
            'excluded': [],
            'summary': '已完成产品事实匹配',
            'progress': {'version': 2, 'timings': [{'stage': 'PARSE'}]},
        }
        stripped = strip_progress(snapshot)
        self.assertNotIn('progress', stripped)
        self.assertEqual(stripped['candidates'][0]['product_code'], 'P1')
        self.assertIn('progress', snapshot)

    def test_text_metrics_count_chars_not_payload(self):
        req = requirement_text_metrics([{'id': 'R-001', 'description': '统一监控'}])
        ev = evidence_text_metrics([
            {'paragraph_id': 'p1', 'title': '能力', 'content_excerpt': '支持统一监控'},
            {'paragraph_id': 'p1', 'title': '能力', 'content_excerpt': '重复片段'},
        ])
        self.assertEqual(req['requirement_count'], 1)
        self.assertGreater(req['requirement_chars'], 0)
        self.assertEqual(ev['evidence_count'], 2)
        self.assertEqual(ev['unique_paragraphs'], 1)
        self.assertGreater(ev['evidence_chars'], 0)


class ProgressSerializerCompatTests(TestCase):
    def test_detail_normalizes_legacy_progress_without_writing_back(self):
        analysis = OpportunityAnalysis.objects.create(
            workspace_id='ws-a',
            user_id='u1',
            idempotency_key='progress-legacy',
            status=AnalysisStatus.ANALYZING,
            original_requirement='需要统一监控',
            result_snapshot={
                'candidates': [],
                'progress': {
                    'current': 'PARSE',
                    'detail': '正在把客户需求拆成可匹配的能力项',
                    'index': 1,
                    'total': 5,
                    'steps': [{'key': 'PARSE', 'label': '解析客户需求', 'status': 'active'}],
                },
            },
        )
        detail = analysis_to_dict(analysis)
        self.assertEqual(detail['result_snapshot']['progress']['version'], 1)
        self.assertEqual(detail['result_snapshot']['progress']['state'], 'RUNNING')
        analysis.refresh_from_db()
        self.assertNotIn('version', analysis.result_snapshot['progress'])
        self.assertNotIn('state', analysis.result_snapshot['progress'])


class ProgressConcurrencyAndAttemptTests(TestCase):
    def test_flush_does_not_overwrite_cancel_decision(self):
        analysis = OpportunityAnalysis.objects.create(
            workspace_id='ws-a',
            user_id='u1',
            idempotency_key='progress-cancel-race',
            status=AnalysisStatus.ANALYZING,
            original_requirement='需要统一监控',
            result_snapshot={'candidates': [], 'progress': {'version': 2, 'state': 'RUNNING', 'current': 'RETRIEVE'}},
        )
        stale = OpportunityAnalysis.objects.get(id=analysis.id)
        tracker = ProgressTracker(stale)
        from opportunity.models import DecisionAction
        from opportunity.services.analysis import confirm_analysis
        confirm_analysis(analysis, DecisionAction.CANCEL, reason='客户撤回', user_id='u1')
        tracker.detail = '正在执行第 2/8 条知识检索'
        tracker.flush(force=True)
        analysis.refresh_from_db()
        self.assertEqual(analysis.status, AnalysisStatus.CLOSED)
        self.assertEqual(analysis.result_snapshot['decision']['action'], 'CANCEL')
        self.assertEqual(analysis.result_snapshot['progress']['state'], 'CANCELLED')
        self.assertNotEqual(analysis.result_snapshot['progress']['state'], 'RUNNING')
        self.assertNotEqual(analysis.result_snapshot['progress']['state'], 'DONE')

    def test_stale_flush_keeps_cancelled_detail_and_timestamp(self):
        analysis = OpportunityAnalysis.objects.create(
            workspace_id='ws-a',
            user_id='u1',
            idempotency_key='progress-cancel-copy',
            status=AnalysisStatus.ANALYZING,
            original_requirement='需要统一监控',
            result_snapshot={'candidates': [], 'progress': {'version': 2, 'state': 'RUNNING', 'current': 'MATCH'}},
        )
        stale = OpportunityAnalysis.objects.get(id=analysis.id)
        tracker = ProgressTracker(stale)
        from opportunity.models import DecisionAction
        from opportunity.services.analysis import confirm_analysis
        confirm_analysis(analysis, DecisionAction.CANCEL, reason='客户撤回', user_id='u1')
        analysis.refresh_from_db()
        cancelled = analysis.result_snapshot['progress']
        detail = cancelled['detail']
        last_updated = cancelled['last_updated_at']
        self.assertEqual(detail, '分析已取消')
        tracker.detail = '正在执行第 2/8 条知识检索'
        tracker.flush(force=True)
        analysis.refresh_from_db()
        progress = analysis.result_snapshot['progress']
        self.assertEqual(analysis.status, AnalysisStatus.CLOSED)
        self.assertEqual(analysis.result_snapshot['decision']['action'], 'CANCEL')
        self.assertEqual(progress['state'], 'CANCELLED')
        self.assertEqual(progress['detail'], '分析已取消')
        self.assertEqual(progress['last_updated_at'], last_updated)
        self.assertNotEqual(progress['detail'], '正在执行第 2/8 条知识检索')

    def test_clarification_and_retry_start_new_attempt(self):
        analysis = OpportunityAnalysis.objects.create(
            workspace_id='ws-a',
            user_id='u1',
            idempotency_key='progress-attempt',
            status=AnalysisStatus.NEED_CLARIFICATION,
            original_requirement='需要统一监控',
            result_snapshot={
                'candidates': [],
                'progress': {
                    'version': 2,
                    'attempt': 1,
                    'state': 'WAITING_USER',
                    'current': 'PARSE',
                    'percent': 40,
                    'completed_units': 1,
                    'started_at': '2026-09-17T01:00:00+00:00',
                    'elapsed_ms': 120000,
                    'timings': [{'stage': 'PARSE', 'name': 'extract_requirement', 'duration_ms': 80}],
                    'counters': {'queries_done': 0, 'products_matched': 0},
                },
            },
        )
        start_new_attempt(analysis)
        analysis.refresh_from_db()
        progress = analysis.result_snapshot['progress']
        self.assertEqual(progress['attempt'], 2)
        self.assertEqual(progress['percent'], 0)
        self.assertEqual(progress['elapsed_ms'], 0)
        self.assertEqual(progress['timings'], [])
        self.assertEqual(progress['attempt_history'][0]['attempt'], 1)
        self.assertEqual(progress['attempt_history'][0]['elapsed_ms'], 120000)
        self.assertNotEqual(progress['started_at'], '2026-09-17T01:00:00+00:00')

        analysis.result_snapshot['progress'].update({
            'state': 'FAILED', 'percent': 70, 'elapsed_ms': 90000, 'timings': [{'name': 'retrieve_query'}],
        })
        analysis.status = AnalysisStatus.FAILED
        analysis.save()
        from opportunity.services.analysis import retry_analysis
        with patch('opportunity.tasks.analyze_opportunity.delay'):
            retry_analysis(analysis)
        analysis.refresh_from_db()
        self.assertEqual(analysis.result_snapshot['progress']['attempt'], 3)
        self.assertEqual(analysis.result_snapshot['progress']['percent'], 0)
        self.assertEqual(analysis.result_snapshot['progress']['timings'], [])

    def test_running_attempt_is_not_reset_on_duplicate_delivery(self):
        analysis = OpportunityAnalysis.objects.create(
            workspace_id='ws-a',
            user_id='u1',
            idempotency_key='progress-duplicate',
            status=AnalysisStatus.ANALYZING,
            original_requirement='需要统一监控',
            result_snapshot={
                'progress': {
                    'version': 2,
                    'attempt': 1,
                    'state': 'RUNNING',
                    'current': 'MATCH',
                    'percent': 56,
                    'completed_units': 8,
                    'started_at': '2026-09-17T02:00:00+00:00',
                    'timings': [{'name': 'retrieve_query', 'duration_ms': 10}],
                },
            },
        )
        maybe_start_new_attempt(analysis)
        tracker = ProgressTracker(analysis)
        self.assertEqual(tracker.attempt, 1)
        self.assertEqual(tracker.percent, 56)
        self.assertEqual(len(tracker.timings), 1)
        self.assertEqual(analysis.result_snapshot['progress']['attempt'], 1)
