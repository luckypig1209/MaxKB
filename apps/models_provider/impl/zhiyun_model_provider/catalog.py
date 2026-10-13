import json
import time
from urllib.parse import urlparse

import requests
from django.utils.translation import gettext as _

from common.exception.app_exception import AppApiException
from common.utils.logger import maxkb_logger

DEFAULT_API_BASE = "https://aigw.telecomjs.com/v1"
ALLOWED_GATEWAY_HOST = "aigw.telecomjs.com"
ALLOWED_GATEWAY_PATH = "/v1"
SELECTABLE_TYPES = ("LLM", "EMBEDDING", "RERANKER")
CATALOG_TYPES = SELECTABLE_TYPES + ("UNKNOWN", "IMAGE", "VIDEO")
MAX_MODEL_ID_LENGTH = 128
USABLE_TYPES = SELECTABLE_TYPES
CONNECT_TIMEOUT_SECONDS = 5
READ_TIMEOUT_SECONDS = 15
MAX_RESPONSE_BYTES = 1024 * 1024
_GATEWAY_SUFFIXES = {"/models", "/rerank"}
_IMAGE_MARKERS = ("image", "seedream")
_VIDEO_MARKERS = ("happyhorse", "minimax-h3", "-t2v", "-i2v", "-r2v", "video")
_LLM_MARKERS = (
    "deepseek",
    "gpt",
    "qwen",
    "glm",
    "kimi",
    "moonshot",
    "doubao",
    "claude",
    "gemini",
    "llama",
    "hunyuan",
    "ernie",
    "spark",
    "mistral",
    "grok",
    "internlm",
    "baichuan",
    "minimax",
    "chat",
)


def redact(text, secret):
    rendered = "" if text is None else str(text)
    if secret:
        rendered = rendered.replace(str(secret), "***")
    return rendered[:300]


def _read_configured_base():
    from maxkb.const import CONFIG

    value = CONFIG.get("ZHIYUN_API_BASE", DEFAULT_API_BASE)
    text = "" if value is None else str(value).strip()
    return text or DEFAULT_API_BASE


def configured_api_base():
    return normalize_api_base(_read_configured_base())


def normalize_api_base(api_base):
    raw = (api_base or "").strip()
    if not raw:
        raise AppApiException(500, _("API 地址不能为空"))
    try:
        parsed = urlparse(raw)
        host = (parsed.hostname or "").lower()
        port = parsed.port
        path = (parsed.path or "").rstrip("/")
        scheme = (parsed.scheme or "").lower()
        has_userinfo = bool(parsed.username or parsed.password)
        query = parsed.query
        fragment = parsed.fragment
    except ValueError:
        raise AppApiException(500, _("只允许访问企业智云网关"))
    allowed = (
        scheme == "https"
        and host == ALLOWED_GATEWAY_HOST
        and port in (None, 443)
        and not has_userinfo
        and not query
        and not fragment
        and path == ALLOWED_GATEWAY_PATH
    )
    if not allowed:
        raise AppApiException(500, _("只允许访问企业智云网关"))
    return DEFAULT_API_BASE


def _is_video_name(name):
    return name.startswith("wan") or any(marker in name for marker in _VIDEO_MARKERS)


def classify_model_id(model_id):
    name = str(model_id or "").strip().lower()
    if not name:
        return None
    if "embedding" in name:
        return "EMBEDDING"
    if "rerank" in name:
        return "RERANKER"
    if any(marker in name for marker in _IMAGE_MARKERS):
        return "IMAGE"
    if _is_video_name(name):
        return "VIDEO"
    if any(marker in name for marker in _LLM_MARKERS):
        return "LLM"
    return "UNKNOWN"


def describe_catalog_model(model_id, model_type):
    if len(model_id) > MAX_MODEL_ID_LENGTH:
        return {
            "id": model_id,
            "model_type": model_type,
            "selectable": False,
            "disabled_reason": "too_long",
        }
    selectable = model_type in SELECTABLE_TYPES
    if selectable:
        reason = None
    elif model_type == "UNKNOWN":
        reason = "unknown"
    else:
        reason = "unsupported"
    return {
        "id": model_id,
        "model_type": model_type,
        "selectable": selectable,
        "disabled_reason": reason,
    }


def catalog_models(payload_data):
    found = {}
    for item in payload_data or []:
        if not isinstance(item, dict):
            continue
        model_id = str(item.get("id") or "").strip()
        model_type = classify_model_id(model_id)
        if model_type is None or model_id in found:
            continue
        found[model_id] = describe_catalog_model(model_id, model_type)
    return sorted(
        found.values(),
        key=lambda item: (CATALOG_TYPES.index(item["model_type"]), item["id"].lower()),
    )


def usable_models(payload_data):
    return [item for item in catalog_models(payload_data) if item["selectable"]]


def group_models(models):
    groups = {model_type: [] for model_type in CATALOG_TYPES}
    for item in models:
        model_type = item.get("model_type")
        if model_type not in groups:
            continue
        groups[model_type].append({
            "id": item["id"],
            "selectable": bool(item.get("selectable")),
            "disabled_reason": item.get("disabled_reason"),
        })
    return groups


def catalog_accepts(item, model_name, model_type):
    if item.get("id") != model_name or item.get("disabled_reason") == "too_long":
        return False
    if item.get("model_type") == model_type and item.get("selectable", True):
        return True
    return item.get("model_type") == "UNKNOWN" and model_type in SELECTABLE_TYPES


def base_model_options(models, model_type):
    options = []
    for item in models:
        if item.get("disabled_reason") == "too_long":
            continue
        matched = item.get("model_type") == model_type and item.get("selectable")
        unrecognized = item.get("model_type") == "UNKNOWN"
        if matched or unrecognized:
            options.append({"name": item["id"], "desc": "", "model_type": model_type})
    return options


def catalog_summary(models):
    selectable = 0
    unsupported = 0
    unknown = 0
    for item in models:
        if item.get("selectable"):
            selectable += 1
        elif item.get("model_type") == "UNKNOWN" and item.get("disabled_reason") != "too_long":
            unknown += 1
        else:
            unsupported += 1
    return {
        "total": len(models),
        "selectable": selectable,
        "unknown": unknown,
        "unsupported": unsupported,
    }


def _log_gateway_error(error_type, http_status, started):
    elapsed_ms = int((time.monotonic() - started) * 1000)
    status_text = "-" if http_status is None else str(http_status)
    maxkb_logger.warning(
        "zhiyun_gateway error_type=%s http_status=%s elapsed_ms=%s",
        error_type,
        status_text,
        elapsed_ms,
    )


def gateway_request_json(method, suffix, api_key, json_body=None, read_timeout=READ_TIMEOUT_SECONDS):
    if suffix not in _GATEWAY_SUFFIXES:
        raise AppApiException(500, _("智云网关请求失败"))
    key = str(api_key or "").strip()
    if not key:
        raise AppApiException(500, _("API Key 不能为空"))
    url = configured_api_base() + suffix
    response = None
    error_type = None
    http_status = None
    started = time.monotonic()
    try:
        response = requests.request(
            method,
            url,
            json=json_body,
            headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
            timeout=(CONNECT_TIMEOUT_SECONDS, read_timeout),
            allow_redirects=False,
            stream=True,
        )
        http_status = response.status_code
        if 300 <= http_status < 400:
            error_type = "redirect"
            raise AppApiException(500, _("智云网关拒绝跳转"))
        if http_status >= 400:
            error_type = "http_status"
            raise AppApiException(500, _("智云网关返回 {status}").format(status=http_status))
        content_type = (response.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if content_type != "application/json":
            error_type = "non_json"
            raise AppApiException(500, _("智云网关没有返回 JSON"))
        declared = response.headers.get("Content-Length")
        if declared and str(declared).isdigit() and int(declared) > MAX_RESPONSE_BYTES:
            error_type = "oversize"
            raise AppApiException(500, _("智云网关响应过大"))
        size = 0
        chunks = []
        for chunk in response.iter_content(chunk_size=65536):
            if not chunk:
                continue
            size += len(chunk)
            if size > MAX_RESPONSE_BYTES:
                error_type = "oversize"
                raise AppApiException(500, _("智云网关响应过大"))
            chunks.append(chunk)
        try:
            payload = json.loads(b"".join(chunks).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            error_type = "non_json"
            raise AppApiException(500, _("智云网关没有返回 JSON"))
        return payload
    except AppApiException:
        if error_type is None:
            error_type = "gateway"
        raise
    except requests.Timeout:
        error_type = "timeout"
        raise AppApiException(500, _("智云网关请求超时")) from None
    except requests.RequestException:
        error_type = "request"
        raise AppApiException(500, _("智云网关请求失败")) from None
    finally:
        if response is not None:
            response.close()
        if error_type is not None:
            _log_gateway_error(error_type, http_status, started)


def fetch_gateway_models(api_base, api_key, timeout=READ_TIMEOUT_SECONDS):
    base = normalize_api_base(api_base)
    payload = gateway_request_json("GET", "/models", api_key, read_timeout=timeout)
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        raise AppApiException(500, _("智云没有返回模型列表"))
    return base, catalog_models(data)


def parse_rerank_results(payload):
    if not isinstance(payload, dict):
        return []
    if isinstance(payload.get("results"), list):
        return payload["results"]
    output = payload.get("output")
    if isinstance(output, dict) and isinstance(output.get("results"), list):
        return output["results"]
    if isinstance(payload.get("data"), list):
        return payload["data"]
    return []


def credential_unchanged(stored, api_base, api_key):
    try:
        current = json.loads(stored) if isinstance(stored, str) else stored
    except (TypeError, ValueError):
        return False
    return isinstance(current, dict) and current.get("api_base") == api_base and current.get("api_key") == api_key
