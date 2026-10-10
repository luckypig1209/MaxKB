# coding=utf-8
"""Evaluate the opportunity matching pipeline.

The default ``snapshot`` mode only evaluates the candidate snapshots already
stored in a JSONL file.  ``online`` mode is deliberately opt-in: it creates a
temporary :class:`OpportunityAnalysis` and runs the existing orchestration
service, so the command does not maintain a second RAG or scoring path.
"""

import hashlib
import json
import time
from pathlib import Path
from time import perf_counter, sleep

from django.core.management.base import BaseCommand, CommandError

from opportunity.services.scoring import apply_ranking, hard_constraint_failed


DEFAULT_ONLINE_CASE_LIMIT = 1
DEFAULT_CASE_TIMEOUT_SECONDS = 600
DEFAULT_POLL_INTERVAL_SECONDS = 1


class OnlineEvaluationTimeout(TimeoutError):
    """A polling deadline exceeded; ``scope`` distinguishes case/batch limits."""

    def __init__(self, scope):
        self.scope = scope
        super().__init__(f'{scope} timeout')


def _as_set(value):
    """Return a set of scalar values without failing on malformed rows."""
    if value is None:
        return set()
    if isinstance(value, (str, int, float)):
        return {str(value)}
    if not isinstance(value, (list, tuple, set)):
        return set()
    return {str(item) for item in value if item is not None and not isinstance(item, (dict, list))}


def _safe_text(value, fallback='', limit=500):
    """Bound error text and avoid leaking common credentials into output."""
    text = str(value or fallback).strip()
    lowered = text.lower()
    secret_markers = (
        'sk-', 'api_key', 'apikey', 'access_token', 'refresh_token',
        'authorization:', 'password', 'secret', 'bearer ',
    )
    if any(marker in lowered for marker in secret_markers):
        return '分析失败'
    return text[:limit]


def _fingerprint(text):
    """Identify an input in reports without persisting its full contents."""
    if not text:
        return None
    return hashlib.sha256(str(text).encode('utf-8')).hexdigest()[:16]


def _case_id(case, line_number):
    value = case.get('case_id') or case.get('id') or f'line-{line_number}'
    return _safe_text(value, f'line-{line_number}', limit=128)


def _requirement_text(case):
    """Accept the names used by phase fixtures and by online datasets."""
    for key in ('original_requirement', 'requirement', 'question', 'input'):
        value = case.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ''


def _number(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _candidate_metrics(case, candidates, requirements=None):
    """Compute the shared, deterministic quality metrics for one result."""
    source_candidates = list(candidates or [])
    requirements = [
        item for item in (requirements if requirements is not None else case.get('requirements') or [])
        if isinstance(item, dict)
    ]
    # apply_ranking mutates rank/exclusion fields.  Copy the outer dictionaries
    # so an online result snapshot is not modified while it is being reported.
    copied_candidates = [dict(item) for item in source_candidates if isinstance(item, dict)]
    ranked, excluded = apply_ranking(copied_candidates, max_candidates=3)
    expected_products = _as_set(case.get('expected_products'))
    expected_cases = _as_set(case.get('expected_cases'))
    codes = [str(item.get('product_code')) for item in ranked if item.get('product_code')]
    predicted_cases = {
        str(reference.get('case_code'))
        for item in copied_candidates
        for reference in (item.get('case_references') or [])
        if isinstance(reference, dict) and reference.get('case_code')
    }

    full_count = 0
    evidence_gap = 0
    hard_leak = 0
    case_hard_override = 0
    must_insufficient_override = 0
    version_mismatch_override = 0
    unauthorized_case_leak = 0
    requirement_map = {
        str(item.get('id')): item
        for item in requirements
        if isinstance(item, dict) and item.get('id') is not None
    }
    for item in ranked:
        for match in item.get('match_items') or []:
            if not isinstance(match, dict):
                continue
            if match.get('status') == 'FULL':
                full_count += 1
                if not match.get('evidence'):
                    evidence_gap += 1
    for item in copied_candidates:
        if not isinstance(item, dict):
            continue
        match_items = [match for match in (item.get('match_items') or []) if isinstance(match, dict)]
        if (
                hard_constraint_failed(requirements, match_items)
                and item.get('rank') is not None
        ):
            hard_leak += 1
        case_score = _number((item.get('score_detail') or {}).get('case_score'))
        if item.get('hard_constraint_failed') and case_score > 0:
            case_hard_override += 1
        for match in match_items:
            if not isinstance(match, dict):
                continue
            requirement = requirement_map.get(str(match.get('requirement_id'))) or {}
            if requirement.get('priority') == 'must' and match.get('status') == 'INSUFFICIENT' and case_score > 0:
                must_insufficient_override += 1
        for reference in item.get('case_references') or []:
            if not isinstance(reference, dict):
                continue
            if reference.get('version_compatible') is False and case_score > 0:
                version_mismatch_override += 1
            if reference.get('eligible') is False:
                unauthorized_case_leak += 1

    top1_hit = bool(codes and expected_products and codes[0] in expected_products)
    top3_hit = bool(expected_products & set(codes[:3]))
    no_match = not expected_products and not codes
    case_hit = bool(expected_cases & predicted_cases)
    passed = (not expected_products or top3_hit) and (not expected_cases or case_hit)
    return {
        'ranked': ranked,
        'excluded': excluded,
        'codes': codes,
        'predicted_cases': sorted(predicted_cases),
        'expected_products': sorted(expected_products),
        'expected_cases': sorted(expected_cases),
        'top1_hit': top1_hit,
        'top3_hit': top3_hit,
        'case_hit': case_hit,
        'no_match': no_match,
        'passed': passed,
        'full_count': full_count,
        'evidence_gap': evidence_gap,
        'hard_leak': hard_leak,
        'case_hard_override': case_hard_override,
        'must_insufficient_override': must_insufficient_override,
        'version_mismatch_override': version_mismatch_override,
        'unauthorized_case_leak': unauthorized_case_leak,
    }


def _new_totals():
    return {
        'product_expected_total': 0,
        'top1': 0,
        'top3': 0,
        'hard_leak': 0,
        'evidence_gap': 0,
        'full_count': 0,
        'case_expected_total': 0,
        'case_hit': 0,
        'case_hard_override': 0,
        'must_insufficient_override': 0,
        'version_mismatch_override': 0,
        'unauthorized_case_leak': 0,
        'correct_no_match': 0,
        'expected_no_match': 0,
    }


def _add_metrics(totals, metrics):
    if metrics['expected_products']:
        totals['product_expected_total'] += 1
        totals['top1'] += int(metrics['top1_hit'])
        totals['top3'] += int(metrics['top3_hit'])
    if metrics['expected_cases']:
        totals['case_expected_total'] += 1
        totals['case_hit'] += int(metrics['case_hit'])
    if not metrics['expected_products']:
        totals['expected_no_match'] += 1
        totals['correct_no_match'] += int(metrics['no_match'])
    totals['hard_leak'] += metrics['hard_leak']
    totals['evidence_gap'] += metrics['evidence_gap']
    totals['full_count'] += metrics['full_count']
    totals['case_hard_override'] += metrics['case_hard_override']
    totals['must_insufficient_override'] += metrics['must_insufficient_override']
    totals['version_mismatch_override'] += metrics['version_mismatch_override']
    totals['unauthorized_case_leak'] += metrics['unauthorized_case_leak']


def _summary_metrics(totals):
    full_count = totals['full_count']
    return {
        'top1_hit_rate': round(totals['top1'] / totals['product_expected_total'] * 100, 1)
        if totals['product_expected_total'] else 0,
        'top3_hit_rate': round(totals['top3'] / totals['product_expected_total'] * 100, 1)
        if totals['product_expected_total'] else 0,
        'hard_constraint_leak': totals['hard_leak'],
        'full_without_evidence': totals['evidence_gap'],
        'full_evidence_coverage': round((full_count - totals['evidence_gap']) / full_count * 100, 1)
        if full_count else 100.0,
        'case_hit_rate': round(totals['case_hit'] / totals['case_expected_total'] * 100, 1)
        if totals['case_expected_total'] else 0,
        'case_hard_constraint_override': totals['case_hard_override'],
        'must_insufficient_case_override': totals['must_insufficient_override'],
        'version_mismatch_case_override': totals['version_mismatch_override'],
        'unauthorized_case_leak': totals['unauthorized_case_leak'],
        'no_match_accuracy': round(totals['correct_no_match'] / totals['expected_no_match'] * 100, 1)
        if totals['expected_no_match'] else 0,
    }


def _result_row(case, line_number, metrics, *, status='SUCCESS', analysis_status=None,
                analysis_id=None, error_code=None, error_reason=None, clarification_questions=None,
                elapsed_ms=0):
    """Build a safe per-case row; never include the original requirement text."""
    row = {
        'case_id': _case_id(case, line_number),
        # A short digest lets a report be joined to a private source file
        # without copying the customer's requirement into stdout or disk.
        'requirement_fingerprint': _fingerprint(_requirement_text(case)),
        'requirement_length': len(_requirement_text(case)),
        'status': status,
        'analysis_status': analysis_status,
        'analysis_id': str(analysis_id) if analysis_id else None,
        'candidate_codes': metrics.get('codes', []),
        'case_codes': metrics.get('predicted_cases', []),
        'top1_hit': bool(metrics.get('top1_hit', False)),
        'top3_hit': bool(metrics.get('top3_hit', False)),
        'case_hit': bool(metrics.get('case_hit', False)),
        'no_match': bool(metrics.get('no_match', False)),
        'passed': bool(metrics.get('passed', False)),
        'full_count': metrics.get('full_count', 0),
        'full_without_evidence': metrics.get('evidence_gap', 0),
        'elapsed_ms': int(elapsed_ms),
    }
    if error_code:
        row['error_code'] = _safe_text(error_code, 'ANALYSIS_FAILED', limit=128)
    if error_reason:
        requirement = _requirement_text(case)
        row['error_reason'] = (
            '分析失败' if requirement and requirement in str(error_reason)
            else _safe_text(error_reason)
        )
    if clarification_questions:
        # Questions are useful for diagnosing a clarification-heavy dataset,
        # but bound them to avoid echoing a large sensitive prompt.
        requirement = _requirement_text(case)
        row['clarification_questions'] = [
            (
                '需要补充关键参数' if requirement and requirement in str(item)
                else _safe_text(item, limit=256)
            )
            for item in clarification_questions[:7]
        ]
    return row


def _create_online_analysis(workspace_id, user_id, case_id, requirement, sequence):
    """Create through the production service so the normal Celery path is used."""
    from opportunity.services.analysis import create_analysis

    # A unique key is required by the model, while keeping the value free of
    # the original requirement.  The UUID suffix also makes repeated reports
    # safe when the same case id occurs more than once.
    key_base = f'evaluation-{sequence}-{_safe_text(case_id, "case", limit=64)}'
    idempotency_key = f'{key_base}-{hashlib.sha256(str(time.time_ns()).encode()).hexdigest()[:16]}'[:128]
    return create_analysis(
        workspace_id=workspace_id,
        user_id=str(user_id),
        idempotency_key=idempotency_key,
        requirement=requirement,
    )


def _get_online_analysis(analysis_id):
    from opportunity.models import OpportunityAnalysis

    return OpportunityAnalysis.objects.get(id=analysis_id)


def _submit_online_clarification(analysis, answer):
    from opportunity.services.analysis import submit_clarification

    return submit_clarification(analysis, answer)


def _poll_online_analysis(analysis_id, case_deadline=None, batch_deadline=None, poll_interval=1):
    """Poll the persisted orchestration task until it reaches a terminal state."""
    terminal_statuses = {'WAITING_CONFIRMATION', 'NEED_CLARIFICATION', 'FAILED', 'CONFIRMED', 'CLOSED'}
    while True:
        now = perf_counter()
        if batch_deadline is not None and now >= batch_deadline:
            raise OnlineEvaluationTimeout('batch')
        if case_deadline is not None and now >= case_deadline:
            raise OnlineEvaluationTimeout('case')
        analysis = _get_online_analysis(analysis_id)
        if str(getattr(analysis, 'status', '') or '') in terminal_statuses:
            return analysis
        remaining = [deadline - now for deadline in (case_deadline, batch_deadline) if deadline is not None]
        wait_for = max(0, min([poll_interval, *remaining]))
        if wait_for:
            sleep(wait_for)


def _clarification_answers(case):
    """Normalize optional one- or multi-round answers from a JSONL row."""
    value = case.get('answers')
    if value in (None, '', []):
        value = case.get('clarification_answer')
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, dict):
        value = value.get('answer') or value.get('text') or ''
        return [str(value)] if str(value).strip() else []
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value if str(item).strip()]
    return [str(value)]


def _validate_online_user(user_id, workspace_id):
    """Reject accidental evaluations under a made-up identity.

    Community editions do not have a workspace membership table, so an active
    local user is sufficient there.  Enterprise editions expose the dynamic
    ``workspace_user_role_mapping`` model and are checked for membership too.
    """
    if not user_id:
        raise CommandError('在线模式必须显式传入 --user-id。')
    try:
        from users.models import User

        if not User.objects.filter(id=user_id, is_active=True).exists():
            raise CommandError('在线评测用户不存在或已停用。')
        from common.database_model_manage.database_model_manage import DatabaseModelManage

        mapping_model = DatabaseModelManage.get_model('workspace_user_role_mapping')
        if mapping_model is not None and not mapping_model.objects.filter(
                workspace_id=workspace_id, user_id=user_id,
        ).exists():
            raise CommandError('在线评测用户不属于指定工作空间。')
    except CommandError:
        raise
    except Exception as exc:  # pragma: no cover - only exercised on incomplete installations
        raise CommandError(f'无法校验在线评测用户：{_safe_text(exc, "用户校验失败")}') from exc


def _load_dataset(path):
    with open(path, 'r', encoding='utf-8') as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except (TypeError, ValueError) as exc:
                yield line_number, None, exc
                continue
            if not isinstance(value, dict):
                yield line_number, None, ValueError('JSONL 行必须是对象')
                continue
            yield line_number, value, None


def _initial_invalid_metrics():
    return {
        'ranked': [], 'excluded': [], 'codes': [], 'predicted_cases': [],
        'expected_products': [], 'expected_cases': [], 'top1_hit': False,
        'top3_hit': False, 'case_hit': False, 'no_match': False, 'passed': False,
        'full_count': 0, 'evidence_gap': 0, 'hard_leak': 0,
        'case_hard_override': 0, 'must_insufficient_override': 0,
        'version_mismatch_override': 0, 'unauthorized_case_leak': 0,
    }


class Command(BaseCommand):
    help = 'Evaluate opportunity matching with a JSONL dataset (snapshot or explicitly confirmed online mode).'

    def add_arguments(self, parser):
        parser.add_argument('--workspace-id', required=True)
        parser.add_argument('--dataset', required=True)
        parser.add_argument('--persist', action='store_true', default=False,
                            help='Keep online OpportunityAnalysis rows; snapshot mode retains this legacy flag.')
        parser.add_argument('--mode', choices=('snapshot', 'online'), default='snapshot')
        parser.add_argument('--online', action='store_true', default=False,
                            help='Alias for --mode online; still requires --confirm-online.')
        parser.add_argument('--confirm-online', '--allow-online', dest='confirm_online', action='store_true',
                            default=False, help='Required acknowledgement that online mode invokes configured models.')
        parser.add_argument('--user-id', default=None, help='Required active user id for online analysis rows.')
        parser.add_argument('--max-cases', type=int, default=None,
                            help='Maximum online rows to execute (defaults to 1 online; snapshot is unlimited).')
        parser.add_argument('--case-timeout-seconds', '--timeout-seconds', dest='case_timeout_seconds',
                            type=float, default=DEFAULT_CASE_TIMEOUT_SECONDS,
                            help='Per-case online polling timeout; non-positive disables the case deadline.')
        parser.add_argument('--total-timeout-seconds', type=float, default=None,
                            help='Optional wall-clock budget for the online batch.')
        parser.add_argument('--poll-interval-seconds', type=float, default=DEFAULT_POLL_INTERVAL_SECONDS,
                            help='Online DB polling interval; non-positive values poll without sleeping.')
        parser.add_argument('--report-path', '--report', '--output', dest='report_path', default=None,
                            help='Write the redacted machine-readable JSON report to this path.')

    def handle(self, *args, **options):
        started = perf_counter()
        mode = 'online' if options.get('online') else options.get('mode', 'snapshot')
        if mode == 'online' and not options.get('confirm_online'):
            raise CommandError(
                '在线模式会调用已配置模型并产生费用；请显式传入 --confirm-online '
                '（或 --allow-online）确认。',
            )
        if mode == 'online':
            _validate_online_user(options.get('user_id'), options['workspace_id'])
        max_cases = options.get('max_cases')
        if mode == 'online':
            if max_cases is None:
                max_cases = DEFAULT_ONLINE_CASE_LIMIT
            if max_cases <= 0:
                raise CommandError('--max-cases 必须是大于 0 的整数。')
        path = options['dataset']
        totals = _new_totals()
        results = []
        failed_cases = []
        status_counts = {'SUCCESS': 0, 'NEED_CLARIFICATION': 0, 'FAILED': 0, 'TIMEOUT': 0}
        dataset_rows = list(_load_dataset(path))
        dataset_total = len(dataset_rows)
        processed = 0
        invalid_rows = 0
        batch_timed_out = False
        stop_reason = None
        batch_started = perf_counter()

        for line_number, case, parse_error in dataset_rows:
            if mode == 'online' and processed >= max_cases:
                break
            total_timeout = options.get('total_timeout_seconds')
            if mode == 'online' and total_timeout is not None and total_timeout > 0:
                elapsed = perf_counter() - batch_started
                if elapsed >= total_timeout:
                    batch_timed_out = True
                    stop_reason = 'total_timeout'
                    break

            processed += 1
            if parse_error is not None or case is None:
                invalid_rows += 1
                row = _result_row(
                    {}, line_number, _initial_invalid_metrics(), status='FAILED',
                    error_code='INVALID_JSONL', error_reason=_safe_text(parse_error, 'JSONL 行无效'),
                )
                results.append(row)
                status_counts['FAILED'] += 1
                failed_cases.append(row['case_id'])
                continue

            if mode == 'snapshot':
                metrics = _candidate_metrics(case, case.get('predicted_candidates') or [])
                _add_metrics(totals, metrics)
                row = _result_row(case, line_number, metrics, status='SUCCESS', analysis_status='SNAPSHOT')
                results.append(row)
                status_counts['SUCCESS'] += 1
                if not metrics['passed']:
                    failed_cases.append(row['case_id'])
                continue

            requirement = _requirement_text(case)
            if not requirement:
                row = _result_row(
                    case, line_number, _initial_invalid_metrics(), status='FAILED',
                    error_code='MISSING_REQUIREMENT', error_reason='JSONL 行缺少原始需求文本',
                )
                results.append(row)
                status_counts['FAILED'] += 1
                failed_cases.append(row['case_id'])
                continue

            case_started = perf_counter()
            analysis = None
            row = None
            stop_after_case = False
            try:
                analysis = _create_online_analysis(
                    options['workspace_id'], options.get('user_id'), _case_id(case, line_number),
                    requirement, processed,
                )
                case_timeout = options.get('case_timeout_seconds')
                case_deadline = case_started + case_timeout if case_timeout and case_timeout > 0 else None
                batch_deadline = (
                    batch_started + total_timeout
                    if total_timeout is not None and total_timeout > 0 else None
                )
                answers = _clarification_answers(case)
                while True:
                    analysis = _poll_online_analysis(
                        str(analysis.id),
                        case_deadline=case_deadline,
                        batch_deadline=batch_deadline,
                        poll_interval=max(0, options.get('poll_interval_seconds') or 0),
                    )
                    analysis_status = str(getattr(analysis, 'status', '') or '')
                    if analysis_status != 'NEED_CLARIFICATION' or not answers:
                        break
                    analysis = _submit_online_clarification(analysis, answers.pop(0))
                if analysis_status in ('WAITING_CONFIRMATION', 'CONFIRMED'):
                    snapshot = getattr(analysis, 'result_snapshot', {}) or {}
                    profile = getattr(analysis, 'requirement_profile', {}) or {}
                    metrics = _candidate_metrics(
                        case,
                        snapshot.get('candidates') or [],
                        requirements=(profile.get('requirements') if isinstance(profile, dict) else None),
                    )
                    _add_metrics(totals, metrics)
                    row = _result_row(
                        case, line_number, metrics, status='SUCCESS', analysis_status=analysis_status,
                        analysis_id=getattr(analysis, 'id', None),
                        elapsed_ms=(perf_counter() - case_started) * 1000,
                    )
                    status_counts['SUCCESS'] += 1
                    if not metrics['passed']:
                        failed_cases.append(row['case_id'])
                elif analysis_status == 'NEED_CLARIFICATION':
                    questions = getattr(analysis, 'clarification_questions', []) or []
                    row = _result_row(
                        case, line_number, _initial_invalid_metrics(), status='NEED_CLARIFICATION',
                        analysis_status=analysis_status, analysis_id=getattr(analysis, 'id', None),
                        error_code='NEED_CLARIFICATION', error_reason='模型要求补充关键参数',
                        clarification_questions=questions,
                        elapsed_ms=(perf_counter() - case_started) * 1000,
                    )
                    status_counts['NEED_CLARIFICATION'] += 1
                    failed_cases.append(row['case_id'])
                elif analysis_status == 'FAILED':
                    row = _result_row(
                        case, line_number, _initial_invalid_metrics(), status='FAILED',
                        analysis_status=analysis_status, analysis_id=getattr(analysis, 'id', None),
                        error_code=getattr(analysis, 'error_code', None) or 'ANALYSIS_FAILED',
                        error_reason=getattr(analysis, 'error_message', None) or '分析失败',
                        elapsed_ms=(perf_counter() - case_started) * 1000,
                    )
                    status_counts['FAILED'] += 1
                    failed_cases.append(row['case_id'])
                else:
                    row = _result_row(
                        case, line_number, _initial_invalid_metrics(), status='FAILED',
                        analysis_status=analysis_status or None, analysis_id=getattr(analysis, 'id', None),
                        error_code='ANALYSIS_INCOMPLETE', error_reason='编排服务未返回完成状态',
                        elapsed_ms=(perf_counter() - case_started) * 1000,
                    )
                    status_counts['FAILED'] += 1
                    failed_cases.append(row['case_id'])
            except OnlineEvaluationTimeout as exc:
                row = _result_row(
                    case, line_number, _initial_invalid_metrics(), status='TIMEOUT',
                    analysis_status=getattr(analysis, 'status', None) if analysis else None,
                    analysis_id=getattr(analysis, 'id', None) if analysis else None,
                    error_code='EVALUATION_TOTAL_TIMEOUT' if exc.scope == 'batch' else 'EVALUATION_TIMEOUT',
                    error_reason=(
                        '达到在线批次总超时限制'
                        if exc.scope == 'batch' else '模型编排超过单条超时限制'
                    ),
                    elapsed_ms=(perf_counter() - case_started) * 1000,
                )
                status_counts['TIMEOUT'] += 1
                failed_cases.append(row['case_id'])
                batch_timed_out = True
                stop_reason = exc.scope + '_timeout'
                stop_after_case = True
            except Exception:  # noqa: BLE001 - one bad row must not abort the batch
                row = _result_row(
                    case, line_number, _initial_invalid_metrics(), status='FAILED',
                    analysis_status=getattr(analysis, 'status', None) if analysis else None,
                    analysis_id=getattr(analysis, 'id', None) if analysis else None,
                    error_code='EVALUATION_FAILED', error_reason='分析失败',
                    elapsed_ms=(perf_counter() - case_started) * 1000,
                )
                status_counts['FAILED'] += 1
                failed_cases.append(row['case_id'])
            if analysis is not None and not options.get('persist') and row.get('status') != 'TIMEOUT':
                try:
                    analysis.delete()
                except Exception:  # pragma: no cover - cleanup is best effort
                    pass
            results.append(row)
            if stop_after_case:
                break

        output = {
            'workspace_id': options['workspace_id'],
            'mode': mode,
            'total': processed,
            'dataset_total': dataset_total,
            'skipped_cases': max(0, dataset_total - processed),
            'batch_timed_out': batch_timed_out,
            'stop_reason': stop_reason,
            'success_count': status_counts['SUCCESS'],
            'clarification_count': status_counts['NEED_CLARIFICATION'],
            'failure_count': status_counts['FAILED'],
            'timeout_count': status_counts['TIMEOUT'],
            'invalid_rows': invalid_rows,
            **_summary_metrics(totals),
            'failed_cases': failed_cases,
            'results': results,
            'elapsed_ms': int((perf_counter() - started) * 1000),
            'persist': options['persist'],
            'max_cases': max_cases if mode == 'online' else None,
            'case_timeout_seconds': options.get('case_timeout_seconds') if mode == 'online' else None,
            'total_timeout_seconds': options.get('total_timeout_seconds') if mode == 'online' else None,
            'poll_interval_seconds': options.get('poll_interval_seconds') if mode == 'online' else None,
        }
        report_path = options.get('report_path')
        if report_path:
            target = Path(report_path)
            output['report_path'] = str(target)
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(json.dumps(output, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            except OSError as exc:
                raise CommandError(f'无法写入评测报告：{_safe_text(exc, "写入失败")}') from exc
        self.stdout.write(json.dumps(output, ensure_ascii=False, indent=2))
