# coding=utf-8
"""VC-206C request-local retrieval and evidence invariants."""

from unittest import TestCase

from opportunity.services.retrieval_optimization import (
    AttemptRetrievalCache,
    dedupe_evidence_hits,
    normalize_query_key,
)


class RetrievalOptimizationTests(TestCase):
    def test_query_key_normalizes_non_semantic_formatting_only(self):
        self.assertEqual(
            normalize_query_key('  Unified\tMonitoring：East  '),
            normalize_query_key('unified monitoring: east'),
        )
        self.assertNotEqual(
            normalize_query_key('product A'),
            normalize_query_key('product B'),
        )

    def test_cache_sends_first_raw_query_and_counts_hits(self):
        calls = []

        def retrieve():
            calls.append('called')
            return [{'paragraph_id': 'p1', 'similarity': 0.8}]

        cache = AttemptRetrievalCache()
        first, first_hit = cache.get_or_retrieve(
            workspace_id='ws', knowledge_id='kb', search_mode='blend',
            top_n=10, similarity=0.3, query='  Original Query  ', retrieve=retrieve,
        )
        second, second_hit = cache.get_or_retrieve(
            workspace_id='ws', knowledge_id='kb', search_mode='blend',
            top_n=10, similarity=0.3, query='original   query', retrieve=retrieve,
        )

        self.assertFalse(first_hit)
        self.assertTrue(second_hit)
        self.assertEqual(len(calls), 1)
        self.assertEqual(first, second)
        self.assertEqual(cache.metrics(), {
            'raw_query_count': 2,
            'unique_query_count': 1,
            'cache_hit_count': 1,
            'raw_evidence_count': 2,
            'unique_paragraph_count': 1,
        })

    def test_cache_key_contains_scope_and_retrieval_parameters(self):
        calls = []

        def retrieve():
            calls.append(1)
            return []

        cache = AttemptRetrievalCache()
        base = {
            'workspace_id': 'ws', 'knowledge_id': 'kb', 'search_mode': 'blend',
            'top_n': 10, 'similarity': 0.3, 'query': 'same', 'retrieve': retrieve,
        }
        cache.get_or_retrieve(**base)
        cache.get_or_retrieve(**{**base, 'knowledge_id': 'other'})
        cache.get_or_retrieve(**{**base, 'search_mode': 'semantic'})
        cache.get_or_retrieve(**{**base, 'top_n': 20})
        cache.get_or_retrieve(**{**base, 'similarity': 0.4})
        self.assertEqual(len(calls), 5)

    def test_failed_retrieval_is_not_cached(self):
        calls = []

        def retrieve():
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError('temporary search failure')
            return [{'paragraph_id': 'p1', 'similarity': 0.7}]

        cache = AttemptRetrievalCache()
        with self.assertRaises(RuntimeError):
            cache.get_or_retrieve(
                workspace_id='ws', knowledge_id='kb', search_mode='blend',
                top_n=10, similarity=0.3, query='same', retrieve=retrieve,
            )
        hits, cache_hit = cache.get_or_retrieve(
            workspace_id='ws', knowledge_id='kb', search_mode='blend',
            top_n=10, similarity=0.3, query='same', retrieve=retrieve,
        )
        self.assertFalse(cache_hit)
        self.assertEqual(len(calls), 2)
        self.assertEqual(hits[0]['paragraph_id'], 'p1')

    def test_evidence_dedupe_keeps_first_source_and_retrieval_order(self):
        hits = [
            {'paragraph_id': 'p1', 'similarity': 0.4, 'document_id': 'd-old'},
            {'paragraph_id': 'p2', 'similarity': 0.9, 'document_id': 'd2'},
            {'paragraph_id': 'p1', 'similarity': 0.8, 'document_id': 'd-new'},
            {'paragraph_id': 'p3', 'similarity': 0.9, 'document_id': 'd3'},
        ]
        result = dedupe_evidence_hits(hits)
        self.assertEqual([item['paragraph_id'] for item in result], ['p1', 'p2', 'p3'])
        self.assertEqual(result[0]['similarity'], 0.4)
        self.assertEqual(result[0]['document_id'], 'd-old')
