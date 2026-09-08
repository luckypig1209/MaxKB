# coding=utf-8
import json
from io import StringIO
from pathlib import Path

from django.core.management import call_command
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
