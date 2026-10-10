# coding=utf-8
from datetime import timedelta
import json
from unittest.mock import patch

from django.core import signing
from django.http import HttpResponse
from django.test import RequestFactory, TestCase
from django.utils import timezone
from rest_framework.test import APIRequestFactory

from common.exception.app_exception import AppAuthenticationFailed
from maxkb.const import CONFIG
from opportunity.middleware import OpportunityEmbedHeadersMiddleware
from opportunity.models import OpportunityAnalysis, OpportunityEmbedClient, OpportunityEmbedSession
from opportunity.serializers.embed import (
    EmbedClientOperateSerializer,
    EmbedClientSerializer,
    EmbedTokenExchangeSerializer,
)
from opportunity.services.embed_security import (
    EMBED_FEATURE_DISABLED_CODE,
    EMBED_FEATURE_DISABLED_MESSAGE,
    TOKEN_SALT,
    hash_client_secret,
    is_opportunity_embed_enabled,
    normalize_origin,
    revoke_embed_session,
    validate_embed_token,
)
from opportunity.views.embed import (
    EmbedAnalysisView,
    EmbedClientView,
    EmbedSessionView,
    EmbedTokenExchangeView,
)
from users.models import User


class OpportunityEmbedSecurityTests(TestCase):
    workspace_id = 'default'
    origin = 'https://crm.example.com'

    def setUp(self):
        self.embed_enabled_patch = patch.dict(CONFIG, {'OPPORTUNITY_EMBED_ENABLED': True})
        self.embed_enabled_patch.start()
        self.user = User.objects.create(
            username='embed-user', nick_name='embed-user', password='unused', role='ADMIN', is_active=True,
        )
        self.secret = 'opp_secret_test-only'
        self.client = OpportunityEmbedClient.objects.create(
            workspace_id=self.workspace_id,
            name='CRM 测试接入方',
            client_id='opp_test_client',
            secret_digest=hash_client_secret(self.secret),
            allowed_origins=[self.origin],
            allowed_scopes=['analysis:create', 'analysis:read'],
            token_ttl_seconds=120,
            creator_user_id=str(self.user.id),
        )

    def tearDown(self):
        self.embed_enabled_patch.stop()
        super().tearDown()

    def exchange(self, **overrides):
        data = {
            'client_id': self.client.client_id,
            'client_secret': self.secret,
            'user_id': str(self.user.id),
            'origin': self.origin,
            'scopes': ['analysis:read'],
        }
        data.update(overrides)
        return EmbedTokenExchangeSerializer().exchange(data)

    def test_client_secret_is_only_returned_when_created(self):
        created = EmbedClientSerializer(data={
            'workspace_id': self.workspace_id,
            'user_id': str(self.user.id),
        }).insert({
            'name': '门户接入',
            'allowed_origins': ['HTTPS://Portal.Example.Com/'],
        })
        self.assertTrue(created['client_secret'].startswith('opp_secret_'))
        stored = OpportunityEmbedClient.objects.get(id=created['id'])
        self.assertNotEqual(stored.secret_digest, created['client_secret'])
        listed = EmbedClientSerializer(data={
            'workspace_id': self.workspace_id,
            'user_id': str(self.user.id),
        }).list()
        listed_client = next(item for item in listed if item['id'] == created['id'])
        self.assertNotIn('client_secret', listed_client)
        self.assertEqual(listed_client['allowed_origins'], ['https://portal.example.com'])

    def test_exchange_and_validate_short_token(self):
        exchanged = self.exchange()
        user, context = validate_embed_token(exchanged['access_token'], required_scope='analysis:read')
        self.assertEqual(user.id, self.user.id)
        self.assertEqual(context.workspace_id, self.workspace_id)
        self.assertEqual(context.client_id, self.client.client_id)
        self.assertEqual(context.origin, self.origin)
        self.assertEqual(context.scopes, ('analysis:read',))
        self.assertNotIn(self.secret, exchanged['access_token'])
        self.assertTrue(context.expires_at)
        payload = signing.loads(exchanged['access_token'], salt=TOKEN_SALT)
        self.assertEqual(payload['jti'], exchanged['session_id'])
        self.assertEqual(payload['department_ids'], [])
        self.assertEqual(payload['scopes'], ['analysis:read'])
        self.assertTrue(payload['expires_at'])

    def test_rejects_bad_secret_origin_scope_and_tampered_token(self):
        with self.assertRaises(AppAuthenticationFailed):
            self.exchange(client_secret='wrong')
        with self.assertRaises(AppAuthenticationFailed):
            self.exchange(origin='https://attacker.example.com')
        with self.assertRaises(Exception):
            self.exchange(scopes=['report:export'])
        token = self.exchange()['access_token']
        with self.assertRaises(AppAuthenticationFailed):
            validate_embed_token(f'{token}tampered')

    def test_revoked_expired_and_disabled_sessions_are_rejected(self):
        first = self.exchange()
        first_session = OpportunityEmbedSession.objects.get(id=first['session_id'])
        revoke_embed_session(first_session)
        with self.assertRaises(AppAuthenticationFailed):
            validate_embed_token(first['access_token'])

        second = self.exchange()
        OpportunityEmbedSession.objects.filter(id=second['session_id']).update(
            expires_at=timezone.now() - timedelta(seconds=1),
        )
        with self.assertRaises(AppAuthenticationFailed):
            validate_embed_token(second['access_token'])

        third = self.exchange()
        self.client.is_active = False
        self.client.save(update_fields=['is_active', 'update_time'])
        with self.assertRaises(AppAuthenticationFailed):
            validate_embed_token(third['access_token'])

    def test_security_setting_change_revokes_existing_sessions(self):
        exchanged = self.exchange()
        EmbedClientOperateSerializer(data={
            'workspace_id': self.workspace_id,
            'user_id': str(self.user.id),
            'client_id': str(self.client.id),
        }).update({'allowed_origins': ['https://portal.example.com']})
        with self.assertRaises(AppAuthenticationFailed):
            validate_embed_token(exchanged['access_token'])

    def test_origin_accepts_only_http_origin_without_path_or_credentials(self):
        self.assertEqual(normalize_origin('HTTPS://CRM.EXAMPLE.COM:8443/'), 'https://crm.example.com:8443')
        self.assertEqual(normalize_origin('https://crm.example.com:443'), 'https://crm.example.com')
        for invalid in (
            'crm.example.com', 'https://crm.example.com/path', 'https://u:p@crm.example.com',
            'https://*.example.com', "https://crm.example.com';script-src",
        ):
            with self.subTest(invalid=invalid), self.assertRaises(Exception):
                normalize_origin(invalid)

    def test_embed_page_uses_origin_bound_frame_policy_and_no_store(self):
        factory = RequestFactory()
        middleware = OpportunityEmbedHeadersMiddleware(lambda request: HttpResponse())
        admin_path = CONFIG.get_admin_path().rstrip('/')
        response = middleware.process_response(
            factory.get(f'{admin_path}/opportunity/embed/{self.client.client_id}'), HttpResponse(),
        )
        self.assertEqual(
            response['Content-Security-Policy'],
            "frame-ancestors 'self' https://crm.example.com",
        )
        self.assertEqual(response['Cache-Control'], 'no-store')
        self.assertEqual(response['Referrer-Policy'], 'no-referrer')

        unknown = middleware.process_response(
            factory.get(f'{admin_path}/opportunity/embed/unknown'), HttpResponse(),
        )
        self.assertEqual(unknown['Content-Security-Policy'], "frame-ancestors 'none'")

    def test_embed_api_uses_token_identity_and_enforces_scope(self):
        token = self.exchange()['access_token']
        factory = APIRequestFactory()
        session_response = EmbedSessionView.as_view()(
            factory.get('/opportunity/embed/session', HTTP_AUTHORIZATION=f'Bearer {token}'),
        )
        session_payload = json.loads(session_response.content)
        self.assertEqual(session_response.status_code, 200)
        self.assertEqual(session_payload['data']['user_id'], str(self.user.id))
        self.assertNotIn('access_token', session_payload['data'])

        denied = EmbedAnalysisView.as_view()(
            factory.post(
                '/opportunity/embed/analyses',
                {'idempotency_key': 'scope-test', 'requirement': '测试需求'},
                format='json',
                HTTP_AUTHORIZATION=f'Bearer {token}',
            ),
        )
        self.assertEqual(denied.status_code, 401)
        self.assertEqual(json.loads(denied.content)['code'], 1002)

        other = OpportunityAnalysis.objects.create(
            workspace_id=self.workspace_id,
            user_id='another-user',
            idempotency_key='other-analysis',
            original_requirement='不应被当前嵌入用户访问',
        )
        isolated = EmbedAnalysisView.Operate.as_view()(
            factory.get(
                f'/opportunity/embed/analyses/{other.id}',
                HTTP_AUTHORIZATION=f'Bearer {token}',
            ),
            analysis_id=str(other.id),
        )
        self.assertEqual(json.loads(isolated.content)['code'], 403)

    @patch('opportunity.tasks.analyze_opportunity.delay')
    def test_embed_api_can_create_for_token_user(self, delay):
        token = self.exchange(scopes=['analysis:create', 'analysis:read'])['access_token']
        response = EmbedAnalysisView.as_view()(
            APIRequestFactory().post(
                '/opportunity/embed/analyses',
                {'idempotency_key': 'embed-create', 'requirement': '需要一个云网监控产品'},
                format='json',
                HTTP_AUTHORIZATION=f'Bearer {token}',
            ),
        )
        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        created = OpportunityAnalysis.objects.get(id=payload['data']['id'])
        self.assertEqual(created.user_id, str(self.user.id))
        self.assertEqual(created.workspace_id, self.workspace_id)
        delay.assert_called_once_with(str(created.id))


class OpportunityEmbedFeatureFlagTests(TestCase):
    def test_disabled_flag_is_false_by_default_and_coerces_string_values(self):
        with patch.dict(CONFIG, {'OPPORTUNITY_EMBED_ENABLED': False}):
            self.assertFalse(is_opportunity_embed_enabled())
        with patch.dict(CONFIG, {'OPPORTUNITY_EMBED_ENABLED': 'false'}):
            self.assertFalse(is_opportunity_embed_enabled())
        with patch.dict(CONFIG, {'OPPORTUNITY_EMBED_ENABLED': 'true'}):
            self.assertTrue(is_opportunity_embed_enabled())

    def test_all_embed_endpoints_return_same_disabled_result_before_authentication(self):
        factory = APIRequestFactory()
        requests = [
            (EmbedClientView.as_view(), factory.get('/workspace/default/opportunity/embed/clients'),
             {'workspace_id': 'default'}),
            (EmbedClientView.as_view(), factory.post('/workspace/default/opportunity/embed/clients', {}),
             {'workspace_id': 'default'}),
            (EmbedClientView.Operate.as_view(), factory.put('/workspace/default/opportunity/embed/clients/c'),
             {'workspace_id': 'default', 'client_id': 'c'}),
            (EmbedClientView.Operate.as_view(), factory.delete('/workspace/default/opportunity/embed/clients/c'),
             {'workspace_id': 'default', 'client_id': 'c'}),
            (EmbedClientView.RotateSecret.as_view(), factory.post('/workspace/default/opportunity/embed/clients/c/rotate-secret'),
             {'workspace_id': 'default', 'client_id': 'c'}),
            (EmbedClientView.RevokeSession.as_view(), factory.post('/workspace/default/opportunity/embed/sessions/s/revoke'),
             {'workspace_id': 'default', 'session_id': 's'}),
            (EmbedTokenExchangeView.as_view(), factory.post('/opportunity/embed/tokens', {}), {}),
            (EmbedSessionView.as_view(), factory.get('/opportunity/embed/session'), {}),
            (EmbedAnalysisView.as_view(), factory.get('/opportunity/embed/analyses'), {}),
            (EmbedAnalysisView.as_view(), factory.post('/opportunity/embed/analyses', {}), {}),
            (EmbedAnalysisView.Operate.as_view(), factory.get('/opportunity/embed/analyses/a'), {'analysis_id': 'a'}),
            (EmbedAnalysisView.Clarification.as_view(), factory.post('/opportunity/embed/analyses/a/clarifications', {}),
             {'analysis_id': 'a'}),
            (EmbedAnalysisView.Retry.as_view(), factory.post('/opportunity/embed/analyses/a/retry', {}), {'analysis_id': 'a'}),
            (EmbedAnalysisView.Confirm.as_view(), factory.post('/opportunity/embed/analyses/a/confirm', {}), {'analysis_id': 'a'}),
            (EmbedAnalysisView.ExportReport.as_view(), factory.get('/opportunity/embed/analyses/a/report/export'),
             {'analysis_id': 'a'}),
        ]
        with patch.dict(CONFIG, {'OPPORTUNITY_EMBED_ENABLED': False}):
            responses = [view(request, **kwargs) for view, request, kwargs in requests]

        payloads = [json.loads(response.content) for response in responses]
        self.assertTrue(all(response.status_code == 404 for response in responses))
        self.assertTrue(all(payload['code'] == EMBED_FEATURE_DISABLED_CODE for payload in payloads))
        self.assertTrue(all(payload['message'] == EMBED_FEATURE_DISABLED_MESSAGE for payload in payloads))
        self.assertTrue(all(payload['data'] is None for payload in payloads))

    def test_embed_page_path_returns_same_disabled_result_without_database_lookup(self):
        factory = RequestFactory()
        middleware = OpportunityEmbedHeadersMiddleware(lambda request: HttpResponse('<html>embed</html>'))
        with patch.dict(CONFIG, {'OPPORTUNITY_EMBED_ENABLED': False}):
            response = middleware.process_response(
                factory.get('/admin/opportunity/embed/opp_existing'), HttpResponse('<html>embed</html>'),
            )
        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(payload['code'], EMBED_FEATURE_DISABLED_CODE)
        self.assertEqual(payload['message'], EMBED_FEATURE_DISABLED_MESSAGE)
