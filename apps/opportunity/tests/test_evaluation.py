# coding=utf-8
import json
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase


class Phase2EvaluationTests(SimpleTestCase):
    def test_phase2_snapshot_dataset_meets_rule_safety_gates(self):
        output = StringIO()
        dataset = Path(__file__).parent / 'fixtures' / 'phase2_eval.jsonl'
        call_command(
            'evaluate_opportunity', workspace_id='ws-eval', dataset=str(dataset), stdout=output,
        )
        result = json.loads(output.getvalue())
        self.assertGreaterEqual(result['top3_hit_rate'], 90)
        self.assertGreaterEqual(result['case_hit_rate'], 90)
        self.assertEqual(result['hard_constraint_leak'], 0)
        self.assertEqual(result['full_without_evidence'], 0)
        self.assertEqual(result['case_hard_constraint_override'], 0)
        self.assertEqual(result['must_insufficient_case_override'], 0)
        self.assertEqual(result['version_mismatch_case_override'], 0)
        self.assertEqual(result['unauthorized_case_leak'], 0)

    def test_online_mode_requires_cost_confirmation(self):
        dataset = Path(__file__).parent / 'fixtures' / 'phase2_eval.jsonl'
        with self.assertRaises(CommandError):
            call_command(
                'evaluate_opportunity', workspace_id='ws-eval', dataset=str(dataset),
                mode='online', user_id='u-eval',
            )

    def test_online_mode_handles_success_clarification_failure_timeout_and_report(self):
        rows = [
            {'case_id': 'ONLINE-SUCCESS', 'requirement': '原始客户需求 A', 'expected_products': ['P1']},
            {'case_id': 'ONLINE-CLARIFY', 'question': '原始客户需求 B', 'expected_products': []},
            {'case_id': 'ONLINE-FAIL', 'requirement': '原始客户需求 C', 'expected_products': []},
            {'case_id': 'ONLINE-TIMEOUT', 'requirement': '原始客户需求 D', 'expected_products': []},
        ]
        behaviors = iter(('success', 'clarification', 'failed', 'timeout'))
        analyses = []

        def create_analysis(*args, **kwargs):
            analysis = SimpleNamespace(
                id=f'analysis-{len(analyses) + 1}', behavior=next(behaviors), status='ANALYZING',
                result_snapshot={}, requirement_profile={}, clarification_questions=[],
                error_code=None, error_message=None,
            )
            analysis.delete = lambda: None
            analyses.append(analysis)
            return analysis

        def poll_analysis(analysis_id, **kwargs):
            analysis = next(item for item in analyses if item.id == analysis_id)
            if analysis.behavior == 'success':
                analysis.status = 'WAITING_CONFIRMATION'
                analysis.result_snapshot = {'candidates': [{'product_code': 'P1', 'score': 90}]}
            elif analysis.behavior == 'clarification':
                analysis.status = 'NEED_CLARIFICATION'
                analysis.clarification_questions = ['请补充规模参数']
            elif analysis.behavior == 'failed':
                analysis.status = 'FAILED'
                analysis.error_code = 'MODEL_FAILED'
                analysis.error_message = 'api_key=do-not-print'
            else:
                from opportunity.management.commands.evaluate_opportunity import OnlineEvaluationTimeout

                raise OnlineEvaluationTimeout('case')
            return analysis

        with TemporaryDirectory() as directory:
            dataset = Path(directory) / 'online.jsonl'
            dataset.write_text('\n'.join(json.dumps(row, ensure_ascii=False) for row in rows), encoding='utf-8')
            report = Path(directory) / 'report.json'
            output = StringIO()
            with patch('opportunity.management.commands.evaluate_opportunity._validate_online_user'), \
                    patch(
                        'opportunity.management.commands.evaluate_opportunity._create_online_analysis',
                        side_effect=create_analysis,
                    ), \
                    patch(
                        'opportunity.management.commands.evaluate_opportunity._poll_online_analysis',
                        side_effect=poll_analysis,
                    ):
                call_command(
                    'evaluate_opportunity', workspace_id='ws-eval', dataset=str(dataset),
                    mode='online', confirm_online=True, user_id='u-eval', max_cases=4,
                    case_timeout_seconds=0, report_path=str(report), stdout=output,
                )
            result = json.loads(output.getvalue())
            report_text = report.read_text(encoding='utf-8')
            saved = json.loads(report_text)

        self.assertEqual(result['success_count'], 1)
        self.assertEqual(result['clarification_count'], 1)
        self.assertEqual(result['failure_count'], 1)
        self.assertEqual(result['timeout_count'], 1)
        self.assertTrue(result['batch_timed_out'])
        self.assertEqual(result['results'][0]['status'], 'SUCCESS')
        self.assertEqual(result['results'][1]['status'], 'NEED_CLARIFICATION')
        self.assertEqual(result['results'][2]['error_reason'], '分析失败')
        self.assertEqual(result['results'][3]['status'], 'TIMEOUT')
        self.assertEqual(saved['report_path'], str(report))
        self.assertNotIn('原始客户需求 A', report_text)
        self.assertNotIn('do-not-print', report_text)

    def test_online_defaults_to_one_case_and_does_not_run_full_dataset(self):
        rows = [
            {'case_id': 'LIMIT-1', 'requirement': '需求一', 'expected_products': []},
            {'case_id': 'LIMIT-2', 'requirement': '需求二', 'expected_products': []},
        ]
        with TemporaryDirectory() as directory:
            dataset = Path(directory) / 'online.jsonl'
            dataset.write_text('\n'.join(json.dumps(row, ensure_ascii=False) for row in rows), encoding='utf-8')
            analyses = []

            def create_analysis(*args, **kwargs):
                analysis = SimpleNamespace(
                    id=f'analysis-{len(analyses) + 1}', status='WAITING_CONFIRMATION',
                    result_snapshot={'candidates': []}, clarification_questions=[],
                    error_code=None, error_message=None,
                )
                analysis.delete = lambda: None
                analyses.append(analysis)
                return analysis

            output = StringIO()
            with patch('opportunity.management.commands.evaluate_opportunity._validate_online_user'), \
                    patch(
                        'opportunity.management.commands.evaluate_opportunity._create_online_analysis',
                        side_effect=create_analysis,
                    ), \
                    patch(
                        'opportunity.management.commands.evaluate_opportunity._poll_online_analysis',
                        side_effect=lambda analysis_id, **kwargs: next(
                            item for item in analyses if item.id == analysis_id
                        ),
                    ):
                call_command(
                    'evaluate_opportunity', workspace_id='ws-eval', dataset=str(dataset),
                    mode='online', confirm_online=True, user_id='u-eval', stdout=output,
                )
            result = json.loads(output.getvalue())

        self.assertEqual(result['total'], 1)
        self.assertEqual(result['dataset_total'], 2)
        self.assertEqual(result['skipped_cases'], 1)
        self.assertEqual(len(analyses), 1)

    def test_polling_waits_for_terminal_status(self):
        from opportunity.management.commands.evaluate_opportunity import _poll_online_analysis

        analyses = iter((
            SimpleNamespace(id='a1', status='ANALYZING'),
            SimpleNamespace(id='a1', status='WAITING_CONFIRMATION'),
        ))
        with patch('opportunity.management.commands.evaluate_opportunity._get_online_analysis',
                   side_effect=lambda analysis_id: next(analyses)), \
                patch('opportunity.management.commands.evaluate_opportunity.sleep') as wait:
            result = _poll_online_analysis('a1', poll_interval=0)
        self.assertEqual(result.status, 'WAITING_CONFIRMATION')
        wait.assert_not_called()

    def test_single_timeout_stops_before_dispatching_next_case(self):
        from opportunity.management.commands.evaluate_opportunity import OnlineEvaluationTimeout

        rows = [
            {'case_id': 'T-1', 'requirement': '需求一'},
            {'case_id': 'T-2', 'requirement': '需求二'},
        ]
        with TemporaryDirectory() as directory:
            dataset = Path(directory) / 'online.jsonl'
            dataset.write_text('\n'.join(json.dumps(row) for row in rows), encoding='utf-8')
            created = []

            def create(*args, **kwargs):
                analysis = SimpleNamespace(id=f'a-{len(created)}', status='ANALYZING')
                created.append(analysis)
                return analysis

            output = StringIO()
            with patch('opportunity.management.commands.evaluate_opportunity._validate_online_user'), \
                    patch(
                        'opportunity.management.commands.evaluate_opportunity._create_online_analysis',
                        side_effect=create,
                    ), \
                    patch(
                        'opportunity.management.commands.evaluate_opportunity._poll_online_analysis',
                        side_effect=OnlineEvaluationTimeout('case'),
                    ):
                call_command(
                    'evaluate_opportunity', workspace_id='ws-eval', dataset=str(dataset),
                    mode='online', confirm_online=True, user_id='u-eval', max_cases=2,
                    stdout=output,
                )
        result = json.loads(output.getvalue())
        self.assertEqual(len(created), 1)
        self.assertEqual(result['skipped_cases'], 1)
        self.assertEqual(result['timeout_count'], 1)

    def test_total_timeout_stops_without_counting_unexecuted_metrics(self):
        from opportunity.management.commands.evaluate_opportunity import OnlineEvaluationTimeout

        rows = [
            {'case_id': 'B-1', 'requirement': '需求一', 'expected_products': ['P1']},
            {'case_id': 'B-2', 'requirement': '需求二', 'expected_products': ['P1']},
        ]
        with TemporaryDirectory() as directory:
            dataset = Path(directory) / 'online.jsonl'
            dataset.write_text('\n'.join(json.dumps(row) for row in rows), encoding='utf-8')
            output = StringIO()
            with patch('opportunity.management.commands.evaluate_opportunity._validate_online_user'), \
                    patch('opportunity.management.commands.evaluate_opportunity._create_online_analysis',
                          return_value=SimpleNamespace(id='a1', status='ANALYZING')), \
                    patch('opportunity.management.commands.evaluate_opportunity._poll_online_analysis',
                          side_effect=OnlineEvaluationTimeout('batch')):
                call_command(
                    'evaluate_opportunity', workspace_id='ws-eval', dataset=str(dataset),
                    mode='online', confirm_online=True, user_id='u-eval', max_cases=2,
                    stdout=output,
                )
        result = json.loads(output.getvalue())
        self.assertTrue(result['batch_timed_out'])
        self.assertEqual(result['skipped_cases'], 1)
        self.assertEqual(result['top3_hit_rate'], 0)

    def test_online_metrics_use_actual_requirement_profile(self):
        row = {
            'case_id': 'PROFILE-1', 'requirement': '需求一', 'expected_products': ['P1'],
            # This deliberately says nothing about the must requirement.
            'requirements': [],
        }
        analysis = SimpleNamespace(
            id='a1', status='WAITING_CONFIRMATION',
            requirement_profile={'requirements': [{'id': 'R1', 'priority': 'must'}]},
            result_snapshot={'candidates': [{
                'product_code': 'P1', 'score': 90, 'hard_constraint_failed': False,
                'match_items': [{'requirement_id': 'R1', 'status': 'NO'}],
            }]},
            delete=lambda: None,
        )
        with TemporaryDirectory() as directory:
            dataset = Path(directory) / 'online.jsonl'
            dataset.write_text(json.dumps(row), encoding='utf-8')
            output = StringIO()
            with patch('opportunity.management.commands.evaluate_opportunity._validate_online_user'), \
                    patch('opportunity.management.commands.evaluate_opportunity._create_online_analysis',
                          return_value=analysis), \
                    patch('opportunity.management.commands.evaluate_opportunity._poll_online_analysis',
                          return_value=analysis):
                call_command(
                    'evaluate_opportunity', workspace_id='ws-eval', dataset=str(dataset),
                    mode='online', confirm_online=True, user_id='u-eval', stdout=output,
                )
        result = json.loads(output.getvalue())
        self.assertEqual(result['hard_constraint_leak'], 1)

    def test_clarification_answer_continues_existing_analysis(self):
        row = {
            'case_id': 'CLARIFY-ANSWER', 'requirement': '需求一', 'clarification_answer': '规模 100',
            'expected_products': ['P1'],
        }
        analysis = SimpleNamespace(
            id='a1', status='NEED_CLARIFICATION', clarification_questions=['请补充规模'],
            result_snapshot={}, requirement_profile={}, delete=lambda: None,
        )
        polls = iter((analysis, SimpleNamespace(
            id='a1', status='WAITING_CONFIRMATION', result_snapshot={
                'candidates': [{'product_code': 'P1', 'score': 90}],
            },
            requirement_profile={}, delete=lambda: None,
        )))
        submitted = []

        def submit(instance, answer):
            submitted.append(answer)
            return instance

        with TemporaryDirectory() as directory:
            dataset = Path(directory) / 'online.jsonl'
            dataset.write_text(json.dumps(row), encoding='utf-8')
            output = StringIO()
            with patch('opportunity.management.commands.evaluate_opportunity._validate_online_user'), \
                    patch(
                        'opportunity.management.commands.evaluate_opportunity._create_online_analysis',
                        return_value=analysis,
                    ), \
                    patch(
                        'opportunity.management.commands.evaluate_opportunity._poll_online_analysis',
                        side_effect=lambda analysis_id, **kwargs: next(polls),
                    ), \
                    patch(
                        'opportunity.management.commands.evaluate_opportunity._submit_online_clarification',
                        side_effect=submit,
                    ):
                call_command(
                    'evaluate_opportunity', workspace_id='ws-eval', dataset=str(dataset),
                    mode='online', confirm_online=True, user_id='u-eval', stdout=output,
                )
        result = json.loads(output.getvalue())
        self.assertEqual(submitted, ['规模 100'])
        self.assertEqual(result['success_count'], 1)
