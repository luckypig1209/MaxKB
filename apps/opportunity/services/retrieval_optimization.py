"""Attempt-scoped retrieval de-duplication and evidence helpers.

The helpers in this module intentionally have no module-level result cache.
An :class:`AttemptRetrievalCache` is created by one analysis execution and is
discarded with that execution, which keeps knowledge-base authorization and
version boundaries intact.
"""

from copy import deepcopy
import re
from collections.abc import Callable


_EQUIVALENT_PUNCTUATION = str.maketrans({
    '\u3000': ' ',
    '\u2018': "'",
    '\u2019': "'",
    '\u201c': '"',
    '\u201d': '"',
    '\u2013': '-',
    '\u2014': '-',
    '\u2212': '-',
    '\uff0c': ',',
    '\u3002': '.',
    '\uff1a': ':',
    '\uff1b': ';',
    '\uff01': '!',
    '\uff1f': '?',
    '\uff08': '(',
    '\uff09': ')',
    '\uff0d': '-',
    '\u3010': '[',
    '\u3011': ']',
    '\u3001': ',',
})
_WHITESPACE = re.compile(r'\s+')
_PUNCTUATION_SPACING = re.compile(r'\s*([,:;!?()\[\]])\s*')


def normalize_query_key(query: object) -> str:
    """Return a comparison key without rewriting the query sent to search."""

    value = str(query or '').translate(_EQUIVALENT_PUNCTUATION).casefold()
    value = _WHITESPACE.sub(' ', value).strip()
    return _PUNCTUATION_SPACING.sub(r'\1', value)


def dedupe_evidence_hits(hits: list[dict] | None) -> list[dict]:
    """Deduplicate paragraph evidence, retaining the first source row.

    Retrieval order is part of the existing model input contract.  A later
    query may report a different score or source metadata for the same
    paragraph, but replacing the first row would change the prompt and report
    semantics.  Every retained row stays intact for traceability.
    """

    retained: dict[str, tuple[int, dict]] = {}
    for index, hit in enumerate(hits or []):
        if not isinstance(hit, dict):
            continue
        paragraph_id = str(hit.get('paragraph_id') or '')
        if not paragraph_id:
            # Rows without a paragraph identity cannot be safely merged.
            retained[f'__missing__{index}'] = (index, hit)
            continue
        if paragraph_id not in retained:
            retained[paragraph_id] = (index, hit)
    return [item for _, item in sorted(retained.values(), key=lambda value: value[0])]


class AttemptRetrievalCache:
    """A tiny cache whose lifetime is one analysis attempt."""

    def __init__(self):
        self._values: dict[tuple, list[dict]] = {}
        self.raw_query_count = 0
        self.unique_query_count = 0
        self.cache_hit_count = 0
        self.raw_evidence_count = 0
        self.unique_paragraph_ids: set[str] = set()

    @staticmethod
    def _key(
        *, workspace_id, knowledge_id, search_mode, top_n, similarity, query,
        user_id=None, authorization_scope=None, knowledge_version=None,
    ):
        # Workspace, user/authorization scope and knowledge version are
        # included even though the cache is already attempt-local.  Keeping
        # these boundaries explicit prevents an eventual caller from turning
        # this helper into a cross-user or cross-version cache by accident.
        return (
            str(workspace_id),
            str(knowledge_id),
            str(user_id or ''),
            str(authorization_scope or ''),
            str(knowledge_version or ''),
            str(search_mode or 'blend'),
            int(top_n or 0),
            str(similarity),
            normalize_query_key(query),
        )

    def get_or_retrieve(
        self,
        *,
        workspace_id,
        knowledge_id,
        search_mode,
        top_n,
        similarity,
        query,
        user_id=None,
        authorization_scope=None,
        knowledge_version=None,
        retrieve: Callable[[], list[dict]],
    ) -> tuple[list[dict], bool]:
        """Return ``(hits, cache_hit)`` and never cache a failed call."""

        self.raw_query_count += 1
        key = self._key(
            workspace_id=workspace_id,
            knowledge_id=knowledge_id,
            search_mode=search_mode,
            top_n=top_n,
            similarity=similarity,
            query=query,
            user_id=user_id,
            authorization_scope=authorization_scope,
            knowledge_version=knowledge_version,
        )
        if key in self._values:
            self.cache_hit_count += 1
            hits = deepcopy(self._values[key])
            self.raw_evidence_count += len(hits)
            self.unique_paragraph_ids.update(
                str(item.get('paragraph_id'))
                for item in hits
                if isinstance(item, dict) and item.get('paragraph_id')
            )
            return hits, True

        self.unique_query_count += 1
        # Exceptions deliberately escape before assignment to _values.  A
        # transient/failed search therefore never poisons a later retry.
        result = retrieve()
        hits = list(result or [])
        self._values[key] = deepcopy(hits)
        self.raw_evidence_count += len(hits)
        self.unique_paragraph_ids.update(
            str(item.get('paragraph_id'))
            for item in hits
            if isinstance(item, dict) and item.get('paragraph_id')
        )
        return deepcopy(hits), False

    def metrics(self) -> dict:
        return {
            'raw_query_count': self.raw_query_count,
            'unique_query_count': self.unique_query_count,
            'cache_hit_count': self.cache_hit_count,
            'raw_evidence_count': self.raw_evidence_count,
            'unique_paragraph_count': len(self.unique_paragraph_ids),
        }
