# coding=utf-8
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from common.exception.app_exception import AppApiException
from opportunity.models import (
    AnalysisStatus,
    DecisionAction,
    OpportunityAnalysis,
    OpportunityAuditLog,
    OpportunityFeedback,
    OpportunityReport,
)
from opportunity.serializers.analysis import AnalysisOperateSerializer, AnalysisSerializer
from opportunity.services.analysis import confirm_analysis
from opportunity.services.report import create_report_snapshot, render_report_html


def create_analysis(user_id='u1', status=AnalysisStatus.WAITING_CONFIRMATION):
    return OpportunityAnalysis.objects.create(
        workspace_id='ws-a', user_id=user_id, idempotency_key=f'key-{user_id}-{status}',
        original_requirement='<script>alert(1)</script> 需要统一监控', status=status,
        result_snapshot={
            'summary': '已完成产品事实匹配',
            'candidates': [{
                'product_code': 'P1', 'product_name': '翼观', 'score': 88,
                'department': {'owner_department_name': '云网运营部'},
                'case_references': [{'case_name': '医疗监控案例'}],
            }],
        },
    )


class OpportunityReportTests(TestCase):
    def test_report_numbers_are_unique_for_analyses_created_together(self):
        first = create_analysis(user_id='same-time-1')
        second = create_analysis(user_id='same-time-2')
        first_report = create_report_snapshot(first, 'same-time-1')
        second_report = create_report_snapshot(second, 'same-time-2')
        self.assertNotEqual(first_report.report_no, second_report.report_no)

    def test_report_versions_are_immutable_and_only_latest_is_current(self):
        analysis = create_analysis()
        first = create_report_snapshot(analysis, 'u1')
        analysis.result_snapshot = {**analysis.result_snapshot, 'summary': '第二版'}
        analysis.save()
        second = create_report_snapshot(analysis, 'u1')
        first.refresh_from_db()
        self.assertEqual(first.version, 1)
        self.assertFalse(first.is_current)
        self.assertEqual(first.snapshot['result']['summary'], '已完成产品事实匹配')
        self.assertEqual(second.version, 2)
        self.assertTrue(second.is_current)

    def test_accept_decision_creates_feedback_audit_and_report(self):
        analysis = create_analysis()
        confirm_analysis(analysis, DecisionAction.ACCEPT, product_code='P1', reason='进入技术确认', user_id='u1')
        analysis.refresh_from_db()
        self.assertEqual(analysis.status, AnalysisStatus.CONFIRMED)
        self.assertEqual(analysis.confirmed_product_code, 'P1')
        self.assertTrue(OpportunityFeedback.objects.filter(analysis=analysis, action='ACCEPT').exists())
        self.assertTrue(OpportunityAuditLog.objects.filter(analysis=analysis, action='DECISION_ACCEPT').exists())
        self.assertTrue(OpportunityReport.objects.filter(analysis=analysis, is_current=True).exists())

    def test_second_decision_is_rejected_even_with_stale_instance(self):
        analysis = create_analysis()
        stale = OpportunityAnalysis.objects.get(id=analysis.id)
        confirm_analysis(analysis, DecisionAction.ACCEPT, product_code='P1', user_id='u1')
        with self.assertRaises(AppApiException):
            confirm_analysis(stale, DecisionAction.REJECT, reason='重复操作', user_id='u1')
        self.assertEqual(OpportunityFeedback.objects.filter(analysis=analysis).count(), 1)

    def test_cancel_running_analysis_is_allowed(self):
        analysis = create_analysis(status=AnalysisStatus.ANALYZING)
        confirm_analysis(analysis, DecisionAction.CANCEL, reason='客户撤回', user_id='u1')
        analysis.refresh_from_db()
        self.assertEqual(analysis.status, AnalysisStatus.CLOSED)
        self.assertEqual(analysis.result_snapshot['decision']['action'], 'CANCEL')

    def test_report_html_escapes_user_content(self):
        report = create_report_snapshot(create_analysis(), 'u1')
        html = render_report_html(report)
        self.assertNotIn('<script>alert(1)</script>', html)
        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;', html)
        self.assertIn('首选推荐', html)
        self.assertIn('翼观', html)

    def test_report_html_hides_zero_score_products(self):
        analysis = create_analysis()
        analysis.result_snapshot['candidates'] = [
            {'product_code': 'P1', 'product_name': '翼观', 'score': 63.1, 'rank': 1,
             'recommendation_level': 'TECHNICAL_CONFIRMATION',
             'department': {'owner_department_name': '智能云网'}, 'match_items': [], 'case_references': []},
            {'product_code': 'P2', 'product_name': '翼聚视频汇聚平台', 'score': 0, 'rank': 3,
             'department': {'owner_department_name': '智慧城市'}, 'match_items': [], 'case_references': []},
        ]
        analysis.save()
        html = render_report_html(create_report_snapshot(analysis, 'u1'))
        self.assertIn('翼观', html)
        self.assertNotIn('翼聚视频汇聚平台', html)


class OpportunityAccessTests(TestCase):
    def test_regular_user_lists_only_own_analyses(self):
        own = create_analysis(user_id='u1')
        create_analysis(user_id='u2')
        result = AnalysisSerializer(data={
            'workspace_id': 'ws-a', 'user_id': 'u1', 'is_manager': False,
        }).list({}, 1, 20)
        self.assertEqual(result['total'], 1)
        self.assertEqual(str(result['records'][0]['id']), str(own.id))

    def test_regular_user_cannot_open_another_users_analysis(self):
        analysis = create_analysis(user_id='u2')
        serializer = AnalysisOperateSerializer(data={
            'workspace_id': 'ws-a', 'analysis_id': str(analysis.id),
            'user_id': 'u1', 'is_manager': False,
        })
        with self.assertRaises(AppApiException):
            serializer.one()

    def test_manager_can_open_workspace_analysis(self):
        analysis = create_analysis(user_id='u2')
        result = AnalysisOperateSerializer(data={
            'workspace_id': 'ws-a', 'analysis_id': str(analysis.id),
            'user_id': 'manager', 'is_manager': True,
        }).one()
        self.assertEqual(result['id'], str(analysis.id))

    def test_manager_can_filter_by_user_department_status_and_time(self):
        matched = create_analysis(user_id='u-filter')
        matched.result_snapshot = {
            **matched.result_snapshot,
            'candidates': [{
                **matched.result_snapshot['candidates'][0],
                'department': {'owner_department_code': 'DEPT-001'},
            }],
        }
        matched.save()
        create_analysis(user_id='u-other')
        now = timezone.now()
        result = AnalysisSerializer(data={
            'workspace_id': 'ws-a', 'user_id': 'manager', 'is_manager': True,
        }).list({
            'create_user': 'u-filter',
            'department_code': 'DEPT-001',
            'status': AnalysisStatus.WAITING_CONFIRMATION,
            'start_time': (now - timedelta(minutes=1)).isoformat(),
            'end_time': (now + timedelta(minutes=1)).isoformat(),
        }, 1, 20)
        self.assertEqual(result['total'], 1)
        self.assertEqual(str(result['records'][0]['id']), str(matched.id))

    def test_analysis_filter_rejects_reversed_time_range(self):
        now = timezone.now()
        with self.assertRaises(Exception):
            AnalysisSerializer(data={
                'workspace_id': 'ws-a', 'user_id': 'manager', 'is_manager': True,
            }).list({
                'start_time': (now + timedelta(minutes=1)).isoformat(),
                'end_time': now.isoformat(),
            }, 1, 20)

    def test_analysis_filter_rejects_unbounded_page_size(self):
        with self.assertRaises(Exception):
            AnalysisSerializer(data={
                'workspace_id': 'ws-a', 'user_id': 'manager', 'is_manager': True,
            }).list({'page_size': 10000}, 1, 20)
