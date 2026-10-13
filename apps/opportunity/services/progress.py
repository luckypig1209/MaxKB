# coding=utf-8
"""
    @project: MaxKB
    @Author：bia
    @file： progress.py
    @date：2026/9/17
    @desc: 商机分析进度协议、阶段计时与节流写入
"""
import logging
import time
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime

from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

logger = logging.getLogger('maxkb')

PROGRESS_VERSION = 2
PROGRESS_STEPS = (
    ('PARSE', '解析客户需求'),
    ('RETRIEVE', '检索产品知识库'),
    ('MATCH', '对照产品资料匹配'),
    ('CASE', '检索相似案例'),
    ('RANK', '评分排序并生成结论'),
)
STAGE_KEYS = [item[0] for item in PROGRESS_STEPS]
FLUSH_INTERVAL_SECONDS = 1.0

STATE_RUNNING = 'RUNNING'
STATE_DONE = 'DONE'
STATE_FAILED = 'FAILED'
STATE_CANCELLED = 'CANCELLED'
STATE_WAITING_USER = 'WAITING_USER'
TERMINAL_PROGRESS_STATES = {STATE_FAILED, STATE_WAITING_USER, STATE_DONE, STATE_CANCELLED}

EVENT_METRIC_KEYS = {
    'product_code',
    'query_index',
    'hit_count',
    'evidence_count',
    'unique_paragraphs',
    'evidence_chars',
    'requirement_count',
    'requirement_chars',
    'prompt_chars',
    'outcome',
}
EVENT_INT_KEYS = {
    'query_index', 'hit_count', 'evidence_count', 'unique_paragraphs',
    'evidence_chars', 'requirement_count', 'requirement_chars', 'prompt_chars',
}
ALLOWED_OUTCOMES = {'SUCCESS', 'FAILED'}
PRODUCT_CODE_MAX_LEN = 64

EMPTY_COUNTERS = {
    'queries_done': 0,
    'queries_total': 0,
    'query_attempts': 0,
    'retrieved_hits': 0,
    'raw_hits': 0,
    'unique_paragraphs': 0,
    'products_found': 0,
    'products_matched': 0,
    'match_model_calls': 0,
    'match_model_attempts': 0,
    'requirement_count': 0,
    'requirement_chars': 0,
    # VC-206C request-local performance metrics.  Values are counts only;
    # query text, evidence bodies and prompts are never persisted.
    'raw_query_count': 0,
    'unique_query_count': 0,
    'cache_hit_count': 0,
    'raw_evidence_count': 0,
    'unique_paragraph_count': 0,
    'prompt_chars': 0,
}


def _isoformat(value):
    if value is None:
        return None
    if hasattr(value, 'isoformat'):
        from opportunity.serializers.common import model_time

        return model_time(value)
    return str(value)


def _safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def evidence_text_metrics(evidence_list) -> dict:
    items = evidence_list or []
    chars = 0
    paragraph_ids = set()
    for item in items:
        chars += len(str(item.get('content_excerpt') or ''))
        chars += len(str(item.get('title') or ''))
        paragraph_id = item.get('paragraph_id')
        if paragraph_id:
            paragraph_ids.add(str(paragraph_id))
    return {
        'evidence_count': len(items),
        'unique_paragraphs': len(paragraph_ids),
        'evidence_chars': chars,
    }


def requirement_text_metrics(requirements) -> dict:
    items = requirements or []
    chars = 0
    for item in items:
        chars += len(str(item.get('id') or ''))
        chars += len(str(item.get('description') or ''))
        chars += len(str(item.get('name') or ''))
    return {
        'requirement_count': len(items),
        'requirement_chars': chars,
    }


def build_steps(current_key: str, done: bool = False, waiting: bool = False) -> list:
    current_index = STAGE_KEYS.index(current_key) if current_key in STAGE_KEYS else 0
    steps = []
    for index, (key, label) in enumerate(PROGRESS_STEPS):
        if done or index < current_index:
            status = 'done'
        elif index == current_index:
            status = 'done' if waiting else 'active'
        else:
            status = 'pending'
        steps.append({'key': key, 'label': label, 'status': status})
    return steps


def _legacy_percent(progress: dict) -> int:
    steps = progress.get('steps') or []
    if not steps:
        return 0
    done = sum(1 for item in steps if item.get('status') == 'done')
    active = 1 if any(item.get('status') == 'active' for item in steps) else 0
    raw = int(100 * (done + active * 0.3) / max(len(steps), 1))
    return min(99, max(0, raw))


def _legacy_units(progress: dict, done: bool) -> tuple[int, int]:
    steps = progress.get('steps') or []
    total = max(len(PROGRESS_STEPS), len(steps), 1)
    if done:
        return total, total
    completed = sum(1 for item in steps if item.get('status') == 'done')
    return min(completed, total), total


def normalize_progress(progress) -> dict:
    if not isinstance(progress, dict) or not progress:
        return {}
    if _safe_int(progress.get('version'), 1) >= PROGRESS_VERSION:
        payload = dict(progress)
        payload.setdefault('counters', {})
        payload.setdefault('timings', [])
        payload.setdefault('steps', [])
        payload.setdefault('attempt', 1)
        payload.setdefault('attempt_history', [])
        return payload
    current = progress.get('current') or 'PARSE'
    done = current == 'DONE'
    steps = progress.get('steps') or []
    parse_step = next((item for item in steps if item.get('key') == 'PARSE'), None)
    waiting = (
        current == 'PARSE'
        and not done
        and bool(parse_step)
        and parse_step.get('status') == 'done'
    )
    state = STATE_DONE if done else (STATE_WAITING_USER if waiting else STATE_RUNNING)
    completed_units, total_units = _legacy_units(progress, done)
    return {
        **progress,
        'version': 1,
        'state': state,
        'percent': 100 if done else _legacy_percent(progress),
        'completed_units': completed_units,
        'total_units': total_units,
        'started_at': progress.get('started_at'),
        'stage_started_at': progress.get('stage_started_at'),
        'last_updated_at': progress.get('last_updated_at'),
        'elapsed_ms': progress.get('elapsed_ms') or 0,
        'counters': progress.get('counters') or {},
        'timings': progress.get('timings') or [],
        'attempt': 1,
        'attempt_history': [],
    }


def strip_progress(snapshot: dict) -> dict:
    data = deepcopy(snapshot or {})
    data.pop('progress', None)
    return data


def _parse_started_at(value):
    if not value:
        return timezone.now()
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if timezone.is_naive(parsed):
            parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
        return parsed
    except (TypeError, ValueError):
        return timezone.now()


def _sanitize_progress_for_closed(payload: dict) -> dict:
    data = dict(payload or {})
    data['state'] = STATE_CANCELLED
    if data.get('current') == 'DONE':
        data['current'] = 'RANK'
    if _safe_int(data.get('percent'), 0) >= 100:
        data['percent'] = 99
    data['detail'] = data.get('detail') if data.get('detail') in ('分析已取消', '分析已关闭') else '分析已取消'
    data['last_updated_at'] = data.get('last_updated_at') or _isoformat(timezone.now())
    data['steps'] = build_steps(data.get('current') if data.get('current') in STAGE_KEYS else 'RANK', done=False)
    return data


def _attempt_summary(progress: dict) -> dict:
    counters = progress.get('counters') or {}
    return {
        'attempt': _safe_int(progress.get('attempt'), 1) or 1,
        'state': progress.get('state'),
        'elapsed_ms': _safe_int(progress.get('elapsed_ms')),
        'percent': _safe_int(progress.get('percent')),
        'counters': {
            key: _safe_int(counters.get(key))
            for key in (
                'query_attempts', 'queries_done', 'match_model_attempts',
                'products_matched', 'retrieved_hits', 'raw_query_count',
                'unique_query_count', 'cache_hit_count', 'raw_evidence_count',
                'unique_paragraph_count', 'prompt_chars',
            )
        },
    }


def _is_model(analysis) -> bool:
    try:
        from opportunity.models import OpportunityAnalysis
    except Exception:
        return False
    return isinstance(analysis, OpportunityAnalysis) and getattr(analysis, 'pk', None)


def persist_snapshot(analysis, *, progress=None, snapshot_fields=None, status=None, extra_fields=None):
    """Merge progress and optional snapshot keys using the latest locked row."""
    from opportunity.models import AnalysisStatus, OpportunityAnalysis

    snapshot_fields = snapshot_fields or {}
    extra_fields = extra_fields or {}

    def apply(target, latest_snapshot, already_closed: bool):
        snapshot = dict(latest_snapshot or {})
        if snapshot_fields and not already_closed:
            snapshot.update(snapshot_fields)
        if progress is not None:
            existing_progress = snapshot.get('progress') or {}
            if already_closed and existing_progress.get('state') == STATE_CANCELLED:
                pass
            elif already_closed:
                payload = _sanitize_progress_for_closed(progress)
                closed_detail = existing_progress.get('detail')
                payload['detail'] = closed_detail if closed_detail in ('分析已取消', '分析已关闭') else '分析已取消'
                payload['last_updated_at'] = _isoformat(timezone.now())
                snapshot['progress'] = payload
            else:
                snapshot['progress'] = dict(progress)
        target.result_snapshot = snapshot
        if not already_closed:
            for key, value in extra_fields.items():
                setattr(target, key, value)
            if status:
                target.status = status
        return snapshot

    if not _is_model(analysis):
        already_closed = getattr(analysis, 'status', None) == AnalysisStatus.CLOSED
        snapshot = apply(analysis, analysis.result_snapshot, already_closed)
        analysis.save(update_fields=['result_snapshot', 'update_time'])
        return snapshot, already_closed

    with transaction.atomic():
        locked = QuerySet(OpportunityAnalysis).select_for_update().filter(id=analysis.id).first()
        if locked is None:
            return (analysis.result_snapshot or {}), True
        already_closed = locked.status == AnalysisStatus.CLOSED
        snapshot = apply(locked, locked.result_snapshot, already_closed)
        update_fields = ['result_snapshot', 'update_time']
        if not already_closed:
            update_fields.extend(extra_fields.keys())
            if status:
                update_fields.append('status')
        locked.save(update_fields=list(dict.fromkeys(update_fields)))
        analysis.result_snapshot = locked.result_snapshot
        analysis.status = locked.status
        for key in extra_fields:
            if hasattr(locked, key):
                setattr(analysis, key, getattr(locked, key))
        return snapshot, already_closed


def start_new_attempt(analysis):
    existing = ((analysis.result_snapshot or {}).get('progress') or {})
    current_attempt = _safe_int(existing.get('attempt'), 0)
    history = list(existing.get('attempt_history') or [])
    has_prior = bool(existing.get('state') or existing.get('timings') or current_attempt)
    if has_prior:
        history.append(_attempt_summary(existing))
        next_attempt = (current_attempt or 1) + 1
    else:
        next_attempt = 1
    now = timezone.now()
    progress = {
        'version': PROGRESS_VERSION,
        'attempt': next_attempt,
        'attempt_history': history,
        'state': STATE_RUNNING,
        'current': 'PARSE',
        'detail': '正在把客户需求拆成可匹配的能力项',
        'index': 1,
        'total': len(PROGRESS_STEPS),
        'percent': 0,
        'completed_units': 0,
        'total_units': len(PROGRESS_STEPS),
        'started_at': _isoformat(now),
        'stage_started_at': _isoformat(now),
        'last_updated_at': _isoformat(now),
        'elapsed_ms': 0,
        'counters': dict(EMPTY_COUNTERS),
        'timings': [],
        'steps': build_steps('PARSE'),
    }
    persist_snapshot(analysis, progress=progress)
    return progress


def maybe_start_new_attempt(analysis):
    existing = ((analysis.result_snapshot or {}).get('progress') or {})
    if existing.get('state') in TERMINAL_PROGRESS_STATES:
        return start_new_attempt(analysis)
    return existing


class ProgressTracker:
    def __init__(self, analysis):
        self.analysis = analysis
        existing = ((analysis.result_snapshot or {}).get('progress') or {})
        self.started_at = _parse_started_at(existing.get('started_at'))
        self.state = existing.get('state') or STATE_RUNNING
        self.current = existing.get('current') if existing.get('current') in STAGE_KEYS else 'PARSE'
        if existing.get('current') == 'DONE':
            self.current = 'RANK'
            self.state = STATE_DONE
        self.detail = existing.get('detail') or ''
        self.percent = _safe_int(existing.get('percent'), 0)
        self.completed_units = _safe_int(existing.get('completed_units'), 0)
        self.total_units = max(_safe_int(existing.get('total_units'), len(PROGRESS_STEPS)), 1)
        self.attempt = max(_safe_int(existing.get('attempt'), 1), 1)
        self.attempt_history = list(existing.get('attempt_history') or [])
        self.counters = {
            **EMPTY_COUNTERS,
            **(existing.get('counters') or {}),
        }
        self.timings = list(existing.get('timings') or [])
        self.stage_started_at = timezone.now()
        self._last_flush_mono = {}
        self.cancelled = self.state == STATE_CANCELLED

    def elapsed_ms(self) -> int:
        delta = timezone.now() - self.started_at
        return max(0, int(delta.total_seconds() * 1000))

    def payload(self) -> dict:
        done = self.state == STATE_DONE
        waiting = self.state == STATE_WAITING_USER
        current_key = 'DONE' if done else self.current
        current_index = STAGE_KEYS.index(self.current) if self.current in STAGE_KEYS else 0
        return {
            'version': PROGRESS_VERSION,
            'attempt': self.attempt,
            'attempt_history': list(self.attempt_history),
            'state': self.state,
            'current': current_key,
            'detail': self.detail,
            'index': len(PROGRESS_STEPS) if done else current_index + 1,
            'total': len(PROGRESS_STEPS),
            'percent': 100 if done else min(99, max(0, self.percent)),
            'completed_units': self.completed_units,
            'total_units': self.total_units,
            'started_at': _isoformat(self.started_at),
            'stage_started_at': _isoformat(self.stage_started_at),
            'last_updated_at': _isoformat(timezone.now()),
            'elapsed_ms': self.elapsed_ms(),
            'counters': dict(self.counters),
            'timings': list(self.timings),
            'steps': build_steps(self.current, done=done, waiting=waiting),
        }

    def _recompute_percent(self):
        total = max(self.total_units, 1)
        raw = int(100 * self.completed_units / total)
        if self.state == STATE_DONE:
            raw = 100
        elif raw >= 100:
            raw = 99
        if raw < self.percent and self.state == STATE_RUNNING:
            raw = self.percent
        self.percent = raw

    def set_totals(self, **kwargs):
        if 'total_units' in kwargs:
            self.total_units = max(_safe_int(kwargs['total_units'], self.total_units), 1)
        for key in ('queries_total', 'products_found', 'requirement_count', 'requirement_chars'):
            if key in kwargs:
                self.counters[key] = _safe_int(kwargs[key], self.counters.get(key, 0))
        self._recompute_percent()

    def add_completed(self, count=1):
        self.completed_units = max(0, self.completed_units + _safe_int(count, 0))
        self._recompute_percent()

    def increment_counter(self, key: str, count=1):
        self.counters[key] = _safe_int(self.counters.get(key)) + _safe_int(count, 0)

    def begin(self, stage: str, detail: str, force=True):
        if self.cancelled or self.state == STATE_CANCELLED:
            return self.flush(force=True)
        if stage in STAGE_KEYS:
            self.current = stage
        self.detail = detail
        self.state = STATE_RUNNING
        self.stage_started_at = timezone.now()
        return self.flush(force=force)

    def record_event(self, stage: str, name: str, duration_ms: int, **metrics):
        safe = {}
        for key, value in metrics.items():
            if key not in EVENT_METRIC_KEYS or value is None:
                continue
            if key == 'outcome':
                if value in ALLOWED_OUTCOMES:
                    safe[key] = value
                continue
            if key == 'product_code':
                text = str(value)[:PRODUCT_CODE_MAX_LEN]
                if text:
                    safe[key] = text
                continue
            if key in EVENT_INT_KEYS:
                safe[key] = _safe_int(value)
        event = {
            'stage': stage,
            'name': name,
            'duration_ms': max(0, _safe_int(duration_ms)),
            **safe,
        }
        self.timings.append(event)
        logger.info(
            'opportunity_timing analysis_id=%s stage=%s name=%s duration_ms=%s outcome=%s counters=%s',
            getattr(self.analysis, 'id', ''),
            stage,
            name,
            event['duration_ms'],
            event.get('outcome'),
            {key: self.counters.get(key) for key in (
                'query_attempts', 'queries_done', 'queries_total', 'retrieved_hits',
                'products_found', 'match_model_attempts', 'products_matched', 'match_model_calls',
            )},
        )

    @contextmanager
    def timed(self, stage: str, name: str, **metrics):
        started = time.perf_counter()
        outcome = 'SUCCESS'
        try:
            yield
        except Exception:
            outcome = 'FAILED'
            raise
        finally:
            duration_ms = int((time.perf_counter() - started) * 1000)
            self.record_event(stage, name, duration_ms, outcome=outcome, **metrics)

    def note_query(self, hit_count: int):
        self.counters['queries_done'] = _safe_int(self.counters.get('queries_done')) + 1
        self.counters['raw_hits'] = _safe_int(self.counters.get('raw_hits')) + _safe_int(hit_count)
        self.counters['retrieved_hits'] = _safe_int(self.counters.get('retrieved_hits')) + _safe_int(hit_count)
        self.add_completed(1)

    def note_unique_paragraphs(self, count: int):
        self.counters['unique_paragraphs'] = _safe_int(count)
        self.counters['unique_paragraph_count'] = _safe_int(count)

    def note_retrieval_metrics(self, metrics: dict):
        """Persist redacted request-local retrieval counters."""
        for key in (
            'raw_query_count',
            'unique_query_count',
            'cache_hit_count',
            'raw_evidence_count',
            'unique_paragraph_count',
        ):
            if key in metrics:
                self.counters[key] = _safe_int(metrics[key])

    def note_match(self, **metrics):
        self.counters['products_matched'] = _safe_int(self.counters.get('products_matched')) + 1
        self.counters['match_model_calls'] = _safe_int(self.counters.get('match_model_calls')) + 1
        if metrics.get('evidence_chars') is not None:
            self.counters['last_match_evidence_chars'] = _safe_int(metrics.get('evidence_chars'))
        if metrics.get('prompt_chars') is not None:
            self.counters['prompt_chars'] = _safe_int(self.counters.get('prompt_chars')) + _safe_int(
                metrics.get('prompt_chars'),
            )
        self.add_completed(1)

    def waiting_user(self, detail: str):
        self.state = STATE_WAITING_USER
        self.current = 'PARSE'
        self.detail = detail
        self._recompute_percent()
        return self.flush(force=True)

    def complete(self, detail: str = '分析完成', flush: bool = True):
        if self.cancelled or self.state == STATE_CANCELLED:
            return self.flush(force=True) if flush else self.payload()
        self.state = STATE_DONE
        self.current = 'RANK'
        self.detail = detail
        self.percent = 100
        self.completed_units = max(self.completed_units, self.total_units)
        if flush:
            return self.flush(force=True)
        return self.payload()

    def fail(self, detail: str = '分析失败'):
        if self.cancelled or self.state == STATE_CANCELLED:
            return self.flush(force=True)
        self.state = STATE_FAILED
        self.detail = detail
        return self.flush(force=True)

    def flush(self, force: bool = False):
        now_mono = time.monotonic()
        last = self._last_flush_mono.get(self.current)
        if not force and last is not None and (now_mono - last) < FLUSH_INTERVAL_SECONDS:
            return ((self.analysis.result_snapshot or {}).get('progress')) or self.payload()
        self._last_flush_mono[self.current] = now_mono
        payload = self.payload()
        _, cancelled = persist_snapshot(self.analysis, progress=payload)
        if cancelled:
            self.cancelled = True
            self.state = STATE_CANCELLED
            stored = ((self.analysis.result_snapshot or {}).get('progress')) or payload
            return stored
        return ((self.analysis.result_snapshot or {}).get('progress')) or payload


def mark_progress_failed(analysis, detail: str = '分析失败'):
    tracker = ProgressTracker(analysis)
    return tracker.fail(detail)


def mark_progress_cancelled(analysis, detail: str = '分析已取消'):
    snapshot = dict(analysis.result_snapshot or {})
    existing = dict(snapshot.get('progress') or {})
    if existing.get('state') == STATE_CANCELLED:
        persist_snapshot(analysis, progress=None)
        return existing
    progress = _sanitize_progress_for_closed({
        **existing,
        'version': existing.get('version') or PROGRESS_VERSION,
        'attempt': existing.get('attempt') or 1,
        'current': existing.get('current') if existing.get('current') in STAGE_KEYS else 'PARSE',
        'detail': detail,
        'percent': existing.get('percent') or 0,
        'index': existing.get('index') or 1,
        'total': existing.get('total') or len(PROGRESS_STEPS),
        'counters': existing.get('counters') or dict(EMPTY_COUNTERS),
        'timings': existing.get('timings') or [],
    })
    progress['detail'] = detail
    progress['last_updated_at'] = _isoformat(timezone.now())
    persist_snapshot(analysis, progress=progress)
    return progress
