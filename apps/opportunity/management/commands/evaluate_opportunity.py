# coding=utf-8
from django.core.management.base import BaseCommand
from time import perf_counter

from opportunity.services.scoring import apply_ranking, hard_constraint_failed


class Command(BaseCommand):
    help = 'Evaluate opportunity matching with a JSONL dataset. LLM calls are skipped in dry-run mode.'

    def add_arguments(self, parser):
        parser.add_argument('--workspace-id', required=True)
        parser.add_argument('--dataset', required=True)
        parser.add_argument('--persist', action='store_true', default=False)

    def handle(self, *args, **options):
        import json
        started = perf_counter()
        path = options['dataset']
        total = 0
        product_expected_total = 0
        top1 = 0
        top3 = 0
        hard_leak = 0
        evidence_gap = 0
        full_count = 0
        case_expected_total = 0
        case_hit = 0
        case_hard_override = 0
        must_insufficient_override = 0
        version_mismatch_override = 0
        unauthorized_case_leak = 0
        correct_no_match = 0
        expected_no_match = 0
        failed_cases = []
        with open(path, 'r', encoding='utf-8') as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                case = json.loads(line)
                total += 1
                expected = set(case.get('expected_products') or [])
                if expected:
                    product_expected_total += 1
                candidates = case.get('predicted_candidates') or []
                ranked, _ = apply_ranking(candidates, max_candidates=3)
                codes = [item.get('product_code') for item in ranked]
                if codes and codes[0] in expected:
                    top1 += 1
                if expected & set(codes[:3]):
                    top3 += 1
                if not expected:
                    expected_no_match += 1
                    if not codes:
                        correct_no_match += 1
                expected_cases = set(case.get('expected_cases') or [])
                predicted_cases = {
                    reference.get('case_code')
                    for item in candidates
                    for reference in item.get('case_references') or []
                }
                if expected_cases:
                    case_expected_total += 1
                    if expected_cases & predicted_cases:
                        case_hit += 1
                for item in ranked:
                    for match in item.get('match_items') or []:
                        if match.get('status') == 'FULL':
                            full_count += 1
                            if not match.get('evidence'):
                                evidence_gap += 1
                for item in candidates:
                    if (
                        hard_constraint_failed(case.get('requirements') or [], item.get('match_items') or [])
                        and item.get('rank') is not None
                    ):
                        hard_leak += 1
                    case_score = float((item.get('score_detail') or {}).get('case_score') or 0)
                    if item.get('hard_constraint_failed') and case_score > 0:
                        case_hard_override += 1
                    requirement_map = {r.get('id'): r for r in case.get('requirements') or []}
                    for match in item.get('match_items') or []:
                        requirement = requirement_map.get(match.get('requirement_id')) or {}
                        if requirement.get('priority') == 'must' and match.get('status') == 'INSUFFICIENT' and case_score > 0:
                            must_insufficient_override += 1
                    for reference in item.get('case_references') or []:
                        if reference.get('version_compatible') is False and case_score > 0:
                            version_mismatch_override += 1
                        if reference.get('eligible') is False:
                            unauthorized_case_leak += 1
                passed = (
                    (not expected or bool(expected & set(codes[:3])))
                    and (not expected_cases or bool(expected_cases & predicted_cases))
                )
                if not passed:
                    failed_cases.append(case.get('case_id'))
        evidence_coverage = round((full_count - evidence_gap) / full_count * 100, 1) if full_count else 100.0
        self.stdout.write(json.dumps({
            'workspace_id': options['workspace_id'],
            'total': total,
            'top1_hit_rate': round(top1 / product_expected_total * 100, 1) if product_expected_total else 0,
            'top3_hit_rate': round(top3 / product_expected_total * 100, 1) if product_expected_total else 0,
            'hard_constraint_leak': hard_leak,
            'full_without_evidence': evidence_gap,
            'full_evidence_coverage': evidence_coverage,
            'case_hit_rate': round(case_hit / case_expected_total * 100, 1) if case_expected_total else 0,
            'case_hard_constraint_override': case_hard_override,
            'must_insufficient_case_override': must_insufficient_override,
            'version_mismatch_case_override': version_mismatch_override,
            'unauthorized_case_leak': unauthorized_case_leak,
            'no_match_accuracy': round(correct_no_match / expected_no_match * 100, 1) if expected_no_match else 0,
            'failed_cases': failed_cases,
            'elapsed_ms': int((perf_counter() - started) * 1000),
            'persist': options['persist'],
        }, ensure_ascii=False, indent=2))
