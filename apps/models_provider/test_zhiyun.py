import json
import uuid
from unittest.mock import patch

import requests
from django.test import SimpleTestCase, TestCase

from common.exception.app_exception import AppApiException
from common.log.log import _get_details
from models_provider.impl.zhiyun_model_provider.catalog import (
    CONNECT_TIMEOUT_SECONDS,
    DEFAULT_API_BASE,
    MAX_RESPONSE_BYTES,
    READ_TIMEOUT_SECONDS,
    classify_model_id,
    configured_api_base,
    fetch_gateway_models,
    group_models,
    normalize_api_base,
    redact,
    usable_models,
)
from models_provider.impl.zhiyun_model_provider.sync import parse_connect_body, redact_request_details, sync_zhiyun_models
from models_provider.models import Model


class FakeGatewayResponse:
    def __init__(self, status=200, body=b"{}", content_type="application/json", headers=None, allow_read=True):
        self.status_code = status
        self.headers = {"Content-Type": content_type}
        if headers:
            self.headers.update(headers)
        self._body = body
        self._allow_read = allow_read
        self.closed = False

    def iter_content(self, chunk_size=65536):
        if not self._allow_read:
            raise AssertionError("response body was read")
        yield self._body

    def close(self):
        self.closed = True


class ZhiyunCatalogTests(SimpleTestCase):
    def test_classifies_gateway_models_by_use(self):
        self.assertEqual(classify_model_id("deepseek-v4-flash-0731"), "LLM")
        self.assertEqual(classify_model_id("kimi-k2.7-code"), "LLM")
        self.assertEqual(classify_model_id("Doubao-Seed-2.0-Pro"), "LLM")
        self.assertEqual(classify_model_id("text-embedding-v4"), "EMBEDDING")
        self.assertEqual(classify_model_id("qwen3-rerank"), "RERANKER")
        self.assertEqual(classify_model_id("gte-rerank-v2"), "RERANKER")
        self.assertEqual(classify_model_id("qwen-image-edit-plus"), "IMAGE")
        self.assertEqual(classify_model_id("wan2.7-t2v"), "VIDEO")
        self.assertEqual(classify_model_id("happyhorse-1.0-i2v"), "VIDEO")
        self.assertEqual(classify_model_id("Doubao-Seedream-5.0-lite"), "IMAGE")
        self.assertEqual(classify_model_id("MiniMax-H3"), "VIDEO")
        self.assertEqual(classify_model_id("vendor-custom-model"), "UNKNOWN")

    def test_catalog_keeps_every_gateway_model(self):
        from models_provider.impl.zhiyun_model_provider.catalog import catalog_models, catalog_summary

        long_id = "deepseek-" + ("x" * 120)
        models = catalog_models([
            {"id": "deepseek-v4-flash-0731"},
            {"id": "text-embedding-v3"},
            {"id": "wan3.0-video"},
            {"id": "vendor-custom-model"},
            {"id": long_id},
            {"id": "deepseek-v4-flash-0731"},
            {"id": ""},
        ])
        by_id = {item["id"]: item for item in models}
        self.assertEqual(set(by_id), {
            "deepseek-v4-flash-0731",
            "text-embedding-v3",
            "wan3.0-video",
            "vendor-custom-model",
            long_id,
        })
        self.assertTrue(by_id["deepseek-v4-flash-0731"]["selectable"])
        self.assertFalse(by_id["wan3.0-video"]["selectable"])
        self.assertEqual(by_id["wan3.0-video"]["disabled_reason"], "unsupported")
        self.assertEqual(by_id["vendor-custom-model"]["disabled_reason"], "unknown")
        self.assertEqual(by_id[long_id]["disabled_reason"], "too_long")
        self.assertEqual([item["id"] for item in usable_models([
            {"id": "deepseek-v4-flash-0731"},
            {"id": "wan3.0-video"},
        ])], ["deepseek-v4-flash-0731"])
        summary = catalog_summary(models)
        self.assertEqual(summary["total"], 5)
        self.assertEqual(summary["selectable"], 2)
        self.assertEqual(group_models(models)["LLM"][0]["id"], "deepseek-v4-flash-0731")

    def test_allows_only_exact_enterprise_gateway(self):
        self.assertEqual(normalize_api_base("https://aigw.telecomjs.com/v1"), DEFAULT_API_BASE)
        self.assertEqual(normalize_api_base("https://aigw.telecomjs.com/v1/"), DEFAULT_API_BASE)
        self.assertEqual(normalize_api_base("https://aigw.telecomjs.com:443/v1"), DEFAULT_API_BASE)
        self.assertEqual(normalize_api_base("HTTPS://AIGW.TELECOMJS.COM/v1"), DEFAULT_API_BASE)
        self.assertEqual(configured_api_base(), DEFAULT_API_BASE)

    def test_rejects_unexpected_gateway_addresses(self):
        rejected = [
            "http://aigw.telecomjs.com/v1",
            "https://example.com/v1",
            "https://aigw.telecomjs.com.evil.com/v1",
            "https://aigw.telecomjs.com:8443/v1",
            "https://user:secret@aigw.telecomjs.com/v1",
            "https://aigw.telecomjs.com/v1?q=1",
            "https://aigw.telecomjs.com/v1#frag",
            "https://127.0.0.1/v1",
            "https://169.254.169.254/latest/meta-data",
            "https://aigw.telecomjs.com",
            "https://aigw.telecomjs.com/v1/models",
        ]
        for raw in rejected:
            with self.assertRaises(AppApiException):
                normalize_api_base(raw)

    def test_rejected_address_makes_no_outbound_request(self):
        with patch("models_provider.impl.zhiyun_model_provider.catalog.requests.request") as request:
            with self.assertRaises(AppApiException) as caught:
                fetch_gateway_models("http://127.0.0.1:8080/v1", "test-token-not-a-secret")
        request.assert_not_called()
        self.assertNotIn("test-token-not-a-secret", caught.exception.message)
        self.assertNotIn("127.0.0.1", caught.exception.message)

    def test_invalid_configured_gateway_fails_closed(self):
        with patch(
            "models_provider.impl.zhiyun_model_provider.catalog._read_configured_base",
            return_value="http://169.254.169.254/",
        ):
            with self.assertRaises(AppApiException) as caught:
                configured_api_base()
        self.assertNotIn("169.254.169.254", caught.exception.message)

    def test_gateway_request_does_not_follow_redirects_or_log_secrets(self):
        secret = "test-token-not-a-secret"
        response = FakeGatewayResponse(
            status=302,
            body=secret.encode(),
            headers={"Location": "http://127.0.0.1/secret", "Content-Type": "application/json"},
            allow_read=False,
        )
        with patch("models_provider.impl.zhiyun_model_provider.catalog.maxkb_logger") as logger, patch(
            "models_provider.impl.zhiyun_model_provider.catalog.requests.request",
            return_value=response,
        ) as request:
            with self.assertRaises(AppApiException) as caught:
                fetch_gateway_models(DEFAULT_API_BASE, secret)
        self.assertNotIn(secret, caught.exception.message)
        self.assertNotIn("127.0.0.1", caught.exception.message)
        self.assertTrue(response.closed)
        request.assert_called_once()
        self.assertEqual(request.call_args.args[0], "GET")
        self.assertEqual(request.call_args.args[1], DEFAULT_API_BASE + "/models")
        self.assertFalse(request.call_args.kwargs["allow_redirects"])
        self.assertTrue(request.call_args.kwargs["stream"])
        self.assertEqual(request.call_args.kwargs["timeout"], (CONNECT_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS))
        logged = " ".join(str(arg) for call in logger.warning.call_args_list for arg in call.args)
        self.assertIn("redirect", logged)
        self.assertIn("302", logged)
        self.assertIn("elapsed_ms", logged)
        self.assertNotIn(secret, logged)
        self.assertNotIn("127.0.0.1", logged)

    def test_gateway_http_errors_keep_status_and_drop_body(self):
        secret = "test-token-not-a-secret"
        for status in (401, 403, 500):
            response = FakeGatewayResponse(status=status, body=f"error {secret}".encode(), allow_read=False)
            with patch("models_provider.impl.zhiyun_model_provider.catalog.maxkb_logger") as logger, patch(
                "models_provider.impl.zhiyun_model_provider.catalog.requests.request",
                return_value=response,
            ):
                with self.assertRaises(AppApiException) as caught:
                    fetch_gateway_models(DEFAULT_API_BASE, secret)
            self.assertIn(str(status), caught.exception.message)
            self.assertNotIn(secret, caught.exception.message)
            logged = " ".join(str(arg) for call in logger.warning.call_args_list for arg in call.args)
            self.assertIn("http_status", logged)
            self.assertIn(str(status), logged)
            self.assertIn("elapsed_ms", logged)
            self.assertNotIn(secret, logged)

    def test_gateway_timeout_oversize_and_non_json(self):
        secret = "test-token-not-a-secret"
        with patch("models_provider.impl.zhiyun_model_provider.catalog.maxkb_logger") as logger, patch(
            "models_provider.impl.zhiyun_model_provider.catalog.requests.request",
            side_effect=requests.Timeout(secret),
        ):
            with self.assertRaises(AppApiException) as caught:
                fetch_gateway_models(DEFAULT_API_BASE, secret)
        self.assertNotIn(secret, caught.exception.message)
        logged = " ".join(str(arg) for call in logger.warning.call_args_list for arg in call.args)
        self.assertIn("timeout", logged)
        self.assertNotIn(secret, logged)

        oversized = FakeGatewayResponse(
            body=b"{}",
            headers={"Content-Length": str(MAX_RESPONSE_BYTES + 1)},
            allow_read=False,
        )
        with patch("models_provider.impl.zhiyun_model_provider.catalog.requests.request", return_value=oversized):
            with self.assertRaises(AppApiException) as caught:
                fetch_gateway_models(DEFAULT_API_BASE, secret)
        self.assertNotIn(secret, caught.exception.message)

        html = FakeGatewayResponse(
            body=secret.encode(),
            content_type="text/html",
            allow_read=False,
        )
        with patch("models_provider.impl.zhiyun_model_provider.catalog.maxkb_logger") as logger, patch(
            "models_provider.impl.zhiyun_model_provider.catalog.requests.request",
            return_value=html,
        ):
            with self.assertRaises(AppApiException) as caught:
                fetch_gateway_models(DEFAULT_API_BASE, secret)
        self.assertNotIn(secret, caught.exception.message)
        logged = " ".join(str(arg) for call in logger.warning.call_args_list for arg in call.args)
        self.assertIn("non_json", logged)
        self.assertNotIn(secret, logged)

        broken = FakeGatewayResponse(body=f"not-json {secret}".encode())
        with patch("models_provider.impl.zhiyun_model_provider.catalog.maxkb_logger") as logger, patch(
            "models_provider.impl.zhiyun_model_provider.catalog.requests.request",
            return_value=broken,
        ):
            with self.assertRaises(AppApiException) as caught:
                fetch_gateway_models(DEFAULT_API_BASE, secret)
        self.assertNotIn(secret, caught.exception.message)
        logged = " ".join(str(arg) for call in logger.warning.call_args_list for arg in call.args)
        self.assertNotIn(secret, logged)

    def test_redact_replaces_secret(self):
        self.assertEqual(redact("token test-token-not-a-secret end", "test-token-not-a-secret"), "token *** end")

    def test_missing_address_uses_configured_gateway(self):
        api_base, api_key, model_ids, model_types = parse_connect_body({"api_key": "test-token-not-a-secret"})
        self.assertEqual(api_base, DEFAULT_API_BASE)
        self.assertEqual(api_key, "test-token-not-a-secret")
        self.assertIsNone(model_ids)
        self.assertEqual(model_types, {})

    def test_rejects_missing_key_without_echoing_it(self):
        with self.assertRaises(AppApiException) as caught:
            parse_connect_body({"api_key": ""})
        self.assertNotIn("sk-", caught.exception.message)

    def test_audit_details_do_not_keep_api_key_or_unexpected_address(self):
        class DummyRequest:
            path = "/workspace/default/model/zhiyun/catalog"
            data = {
                "api_base": "https://user:test-token-not-a-secret@127.0.0.1/v1",
                "api_key": "test-token-not-a-secret",
                "model_ids": ["deepseek-v4-flash-0731"],
            }
            query_params = {}

        rendered = json.dumps(redact_request_details(DummyRequest()), ensure_ascii=False)
        self.assertNotIn("test-token-not-a-secret", rendered)
        self.assertNotIn("127.0.0.1", rendered)
        self.assertIn("***", rendered)

        class GenericRequest:
            path = "/model"
            data = {
                "api_key": "test-token-not-a-secret",
                "credential": {"api_base": DEFAULT_API_BASE, "api_key": "test-token-not-a-secret"},
                "password": "local-password",
            }
            query_params = {}

        generic = json.dumps(_get_details(GenericRequest()), ensure_ascii=False)
        self.assertNotIn("test-token-not-a-secret", generic)
        self.assertNotIn("local-password", generic)

    def test_redacts_query_and_nested_secret_fields(self):
        secret = "test-token-not-a-secret"

        class Request:
            path = "/workspace/default/model/zhiyun/catalog"
            data = {
                "model_ids": ["deepseek-v4-flash-0731"],
                "credential": {
                    "api_key": secret,
                    "api_base": "https://aigw.telecomjs.com/v1",
                    "name": "kept",
                },
                "nested": [{"Token": secret, "id": "model-1"}, {"password": secret}],
            }
            query_params = {
                "api_key": secret,
                "Authorization": "Bearer " + secret,
                "status": "SUCCESS",
            }

        rendered = json.dumps(redact_request_details(Request()), ensure_ascii=False)
        self.assertNotIn(secret, rendered)
        self.assertNotIn("Bearer", rendered)
        self.assertIn("deepseek-v4-flash-0731", rendered)
        self.assertIn("/workspace/default/model/zhiyun/catalog", rendered)
        self.assertIn("SUCCESS", rendered)
        self.assertIn("kept", rendered)
        self.assertIn("model-1", rendered)
        generic = json.dumps(_get_details(Request()), ensure_ascii=False)
        self.assertNotIn(secret, generic)
        self.assertIn("SUCCESS", generic)

    def test_malformed_gateway_address_is_rejected_without_a_request(self):
        rejected = [
            "https://aigw.telecomjs.com:bad/v1",
            "https://aigw.telecomjs.com:70000/v1",
            "https://[gggg::1]/v1",
        ]
        for raw in rejected:
            with patch("models_provider.impl.zhiyun_model_provider.catalog.requests.request") as request:
                with self.assertRaises(AppApiException) as caught:
                    normalize_api_base(raw)
                with self.assertRaises(AppApiException):
                    fetch_gateway_models(raw, "test-token-not-a-secret")
            request.assert_not_called()
            self.assertNotIn("aigw.telecomjs.com", caught.exception.message)
            self.assertNotIn(raw, caught.exception.message)

        class Request:
            path = "/workspace/default/model/zhiyun/catalog"
            data = {"api_base": "https://aigw.telecomjs.com:bad/v1", "api_key": "test-token-not-a-secret"}
            query_params = {"token": "test-token-not-a-secret"}

        rendered = json.dumps(redact_request_details(Request()), ensure_ascii=False)
        self.assertNotIn("test-token-not-a-secret", rendered)
        self.assertNotIn(":bad", rendered)
        self.assertNotIn("aigw.telecomjs.com:bad", rendered)

    def test_audit_detail_failure_does_not_replace_the_business_error(self):
        from common.log.log import log

        class Request:
            path = "/model"
            data = {"api_key": "test-token-not-a-secret"}
            query_params = {}
            META = {}
            user = None

        def bad_details(request):
            raise RuntimeError("test-token-not-a-secret")

        @log(menu="model", operate="op", get_details=bad_details)
        def failing(self, request):
            raise AppApiException(500, "business")

        @log(menu="model", operate="op", get_details=bad_details)
        def succeeding(self, request):
            return "ok"

        with patch("common.log.log.Log") as log_model, patch("common.log.log.maxkb_logger") as logger:
            with self.assertRaises(AppApiException) as caught:
                failing(None, Request())
            self.assertEqual(succeeding(None, Request()), "ok")
        self.assertEqual(caught.exception.message, "business")
        logged = " ".join(str(arg) for call in logger.warning.call_args_list for arg in call.args)
        self.assertNotIn("test-token-not-a-secret", logged)
        log_model.assert_not_called()

    def test_form_schema_omits_api_base_and_stores_the_fixed_gateway(self):
        from models_provider.impl.zhiyun_model_provider.credential import (
            ZhiyunEmbeddingCredential,
            ZhiyunLLMModelCredential,
            ZhiyunRerankerCredential,
        )

        secret = "test-token-not-a-secret"
        for credential_type in (ZhiyunLLMModelCredential, ZhiyunEmbeddingCredential, ZhiyunRerankerCredential):
            fields = [item["field"] for item in credential_type().to_form_list()]
            self.assertNotIn("api_base", fields)
            self.assertIn("api_key", fields)
            stored = credential_type().encryption_dict({"api_key": secret, "api_base": "http://127.0.0.1/v1"})
            self.assertEqual(stored["api_base"], DEFAULT_API_BASE)
            self.assertNotIn(secret, json.dumps(stored))

    def test_validation_overwrites_a_submitted_gateway_address(self):
        from models_provider.impl.zhiyun_model_provider.credential import (
            ZhiyunEmbeddingCredential,
            ZhiyunLLMModelCredential,
            ZhiyunRerankerCredential,
        )

        catalog = [
            {"id": "deepseek-v4-flash-0731", "model_type": "LLM"},
            {"id": "text-embedding-v4", "model_type": "EMBEDDING"},
            {"id": "qwen3-rerank", "model_type": "RERANKER"},
        ]

        class Provider:
            def get_model_type_list(self):
                return [{"value": "LLM"}, {"value": "EMBEDDING"}, {"value": "RERANKER"}]

            def get_model(self, model_type, model_name, model_credential, **kwargs):
                self.base = model_credential.get("api_base")

                class Ready:
                    def invoke(self, messages):
                        return "ok"

                    def embed_query(self, text):
                        return [0.1]

                return Ready()

        cases = [
            (ZhiyunLLMModelCredential(), "LLM", "deepseek-v4-flash-0731"),
            (ZhiyunEmbeddingCredential(), "EMBEDDING", "text-embedding-v4"),
            (ZhiyunRerankerCredential(), "RERANKER", "qwen3-rerank"),
        ]
        for credential, model_type, model_name in cases:
            submitted = {"api_key": "test-token-not-a-secret", "api_base": "https://evil.example/v1"}
            provider = Provider()
            with patch(
                "models_provider.impl.zhiyun_model_provider.credential.fetch_gateway_models",
                return_value=(DEFAULT_API_BASE, catalog),
            ) as fetch:
                self.assertTrue(credential.is_valid(model_type, model_name, submitted, {}, provider, True))
            self.assertEqual(submitted["api_base"], DEFAULT_API_BASE)
            self.assertEqual(fetch.call_args.args[0], DEFAULT_API_BASE)
            self.assertNotIn("evil.example", fetch.call_args.args[0])

    def test_tokenhub_runtime_uses_fixed_gateway_and_locked_transport(self):
        from models_provider.impl.openai_model_provider.model.llm import OpenAIChatModel
        from models_provider.impl.zhiyun_model_provider.transport import (
            ZHIYUN_CONNECT_TIMEOUT_SECONDS,
            ZHIYUN_MAX_CONNECTIONS,
            ZHIYUN_MAX_KEEPALIVE_CONNECTIONS,
            ZHIYUN_POOL_TIMEOUT_SECONDS,
            ZHIYUN_READ_TIMEOUT_SECONDS,
            ZHIYUN_SDK_RETRIES,
            ZHIYUN_TRANSPORT_RETRIES,
            ZHIYUN_WRITE_TIMEOUT_SECONDS,
        )
        from models_provider.impl.zhiyun_model_provider.zhiyun_model_provider import (
            ZhiyunChatModel,
            ZhiyunEmbeddingModel,
        )

        submitted = {"api_base": "http://127.0.0.1/v1", "api_key": "test-token-not-a-secret"}
        with patch(
            "models_provider.impl.zhiyun_model_provider.zhiyun_model_provider.OpenAIChatModel.new_instance"
        ) as create:
            ZhiyunChatModel.new_instance("LLM", "deepseek-v4-flash-0731", submitted, http_client="caller")
            sync_client = create.call_args.kwargs["http_client"]
            ZhiyunChatModel.new_instance("LLM", "deepseek-v4-flash-0731", submitted)
        self.assertEqual(create.call_args_list[0].args[2]["api_base"], DEFAULT_API_BASE)
        self.assertIs(create.call_args.kwargs["http_client"], sync_client)
        self.assertIsNot(sync_client, "caller")
        async_client = create.call_args.kwargs["http_async_client"]
        self.assertFalse(sync_client.follow_redirects)
        self.assertFalse(async_client.follow_redirects)
        self.assertEqual(sync_client.timeout.connect, ZHIYUN_CONNECT_TIMEOUT_SECONDS)
        self.assertEqual(sync_client.timeout.read, ZHIYUN_READ_TIMEOUT_SECONDS)
        self.assertEqual(sync_client.timeout.write, ZHIYUN_WRITE_TIMEOUT_SECONDS)
        self.assertEqual(sync_client.timeout.pool, ZHIYUN_POOL_TIMEOUT_SECONDS)
        self.assertEqual(sync_client._transport._pool._retries, ZHIYUN_TRANSPORT_RETRIES)
        self.assertEqual(sync_client._transport._pool._max_connections, ZHIYUN_MAX_CONNECTIONS)
        self.assertEqual(sync_client._transport._pool._max_keepalive_connections, ZHIYUN_MAX_KEEPALIVE_CONNECTIONS)
        self.assertEqual(create.call_args.kwargs["max_retries"], ZHIYUN_SDK_RETRIES)

        with patch("models_provider.impl.zhiyun_model_provider.zhiyun_model_provider.openai.OpenAI") as openai_cls:
            ZhiyunEmbeddingModel.new_instance("EMBEDDING", "text-embedding-v4", submitted)
        self.assertEqual(openai_cls.call_args.kwargs["base_url"], DEFAULT_API_BASE)
        self.assertFalse(openai_cls.call_args.kwargs["http_client"].follow_redirects)
        self.assertEqual(openai_cls.call_args.kwargs["max_retries"], ZHIYUN_SDK_RETRIES)
        self.assertIs(openai_cls.call_args.kwargs["http_client"], sync_client)

        with patch.object(OpenAIChatModel, "__init__", return_value=None) as init:
            OpenAIChatModel.new_instance(
                "LLM", "gpt-4o", {"api_base": "https://api.openai.com/v1", "api_key": "other"},
            )
        self.assertNotIn("http_client", init.call_args.kwargs)
        self.assertEqual(init.call_args.kwargs["openai_api_base"], "https://api.openai.com/v1")


class ZhiyunSyncTests(TestCase):
    def setUp(self):
        self.workspace_id = "zhiyun-test"
        self.user_id = uuid.uuid4()
        self.catalog = [
            {"id": "deepseek-v4-flash-0731", "model_type": "LLM"},
            {"id": "text-embedding-v4", "model_type": "EMBEDDING"},
        ]

    def _sync(self, model_ids, model_types=None):
        with patch(
            "models_provider.impl.zhiyun_model_provider.sync.fetch_gateway_models",
            return_value=("https://aigw.telecomjs.com/v1", self.catalog),
        ), patch(
            "models_provider.impl.zhiyun_model_provider.sync.rsa_long_encrypt",
            side_effect=lambda message, *_args, **_kwargs: "enc:" + message,
        ), patch(
            "models_provider.impl.zhiyun_model_provider.sync.rsa_long_decrypt",
            side_effect=lambda message, *_args, **_kwargs: message[4:],
        ), patch(
            "models_provider.impl.zhiyun_model_provider.sync.UserResourcePermissionSerializer"
        ) as permission:
            permission.return_value.auth_resource.return_value = True
            return sync_zhiyun_models(
                self.workspace_id,
                self.user_id,
                "https://aigw.telecomjs.com",
                "test-token-not-a-secret",
                model_ids,
                model_types,
            )

    def test_sync_creates_selected_models_and_is_idempotent(self):
        created = self._sync(["deepseek-v4-flash-0731", "text-embedding-v4", "wan2.7-t2v"])
        self.assertEqual(created["created"], ["deepseek-v4-flash-0731", "text-embedding-v4"])
        self.assertEqual(created["skipped"], [{"id": "wan2.7-t2v", "reason": "not_in_catalog"}])
        self.assertNotIn("test-token-not-a-secret", json.dumps(created))
        stored = Model.objects.get(workspace_id=self.workspace_id, model_name="deepseek-v4-flash-0731")
        self.assertEqual(stored.provider, "model_zhiyun_provider")
        self.assertEqual(stored.model_type, "LLM")
        self.assertTrue(stored.credential.startswith("enc:"))

        again = self._sync(["deepseek-v4-flash-0731"])
        self.assertEqual(again["unchanged"], ["deepseek-v4-flash-0731"])
        self.assertEqual(Model.objects.filter(workspace_id=self.workspace_id, model_name="deepseek-v4-flash-0731").count(), 1)

    def test_sync_does_not_replace_another_providers_model(self):
        Model.objects.create(
            workspace_id=self.workspace_id,
            name="deepseek-v4-flash-0731",
            model_type="LLM",
            model_name="other",
            provider="model_openai_provider",
            credential="{}",
        )
        result = self._sync(["deepseek-v4-flash-0731"])
        self.assertEqual(result["skipped"], [{"id": "deepseek-v4-flash-0731", "reason": "name_exists"}])
        self.assertEqual(Model.objects.filter(workspace_id=self.workspace_id).count(), 1)

    def test_sync_imports_a_confirmed_unknown_model_and_skips_video(self):
        self.catalog = [
            {"id": "vendor-custom-model", "model_type": "UNKNOWN", "selectable": False, "disabled_reason": "unknown"},
            {"id": "wan2.7-t2v", "model_type": "VIDEO", "selectable": False, "disabled_reason": "unsupported"},
        ]
        with self.assertRaises(AppApiException):
            self._sync(["vendor-custom-model", "wan2.7-t2v"])
        created = self._sync(["vendor-custom-model", "wan2.7-t2v"], {"vendor-custom-model": "LLM"})
        self.assertEqual(created["created"], ["vendor-custom-model"])
        self.assertEqual(created["skipped"], [{"id": "wan2.7-t2v", "reason": "unsupported"}])
        stored = Model.objects.get(workspace_id=self.workspace_id, model_name="vendor-custom-model")
        self.assertEqual(stored.model_type, "LLM")

    def test_saved_credential_fills_the_base_model_dropdown(self):
        from models_provider.impl.zhiyun_model_provider.sync import list_workspace_base_models

        model = Model.objects.create(
            workspace_id=self.workspace_id,
            name="saved-zhiyun",
            model_type="LLM",
            model_name="deepseek-v4-flash-0731",
            provider="model_zhiyun_provider",
            credential="enc:hidden",
        )
        catalog = [
            {"id": "deepseek-v4-flash-0731", "model_type": "LLM", "selectable": True, "disabled_reason": None},
            {"id": "kimi-k2.7-code", "model_type": "LLM", "selectable": True, "disabled_reason": None},
            {"id": "vendor-custom-model", "model_type": "UNKNOWN", "selectable": False, "disabled_reason": "unknown"},
            {"id": "wan2.7-t2v", "model_type": "VIDEO", "selectable": False, "disabled_reason": "unsupported"},
        ]
        with patch(
            "models_provider.impl.zhiyun_model_provider.sync.rsa_long_decrypt",
            return_value='{"api_base":"https://aigw.telecomjs.com/v1","api_key":"test-token-not-a-secret"}',
        ), patch(
            "models_provider.impl.zhiyun_model_provider.sync.fetch_gateway_models",
            return_value=("https://aigw.telecomjs.com/v1", catalog),
        ) as fetch:
            options = list_workspace_base_models(self.workspace_id, "LLM", str(model.id))
        self.assertEqual(
            [item["name"] for item in options],
            ["deepseek-v4-flash-0731", "kimi-k2.7-code", "vendor-custom-model"],
        )
        self.assertNotIn("wan2.7-t2v", [item["name"] for item in options])
        self.assertNotIn("test-token-not-a-secret", json.dumps(options))
        fetch.assert_called_once()
        self.assertIsNone(list_workspace_base_models("missing-workspace", "LLM"))
