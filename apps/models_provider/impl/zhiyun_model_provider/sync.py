import json

from django.db import transaction
from django.utils.translation import gettext as _

from common.exception.app_exception import AppApiException
from common.log.log import REDACTED, redact_sensitive
from common.utils.rsa_util import rsa_long_decrypt, rsa_long_encrypt
from models_provider.impl.zhiyun_model_provider.catalog import (
    SELECTABLE_TYPES,
    base_model_options,
    catalog_summary,
    configured_api_base,
    credential_unchanged,
    fetch_gateway_models,
    group_models,
    normalize_api_base,
)
from models_provider.models import Model, Status
from system_manage.models import AuthTargetType
from system_manage.serializers.user_resource_permission import UserResourcePermissionSerializer

PROVIDER = "model_zhiyun_provider"


def redact_request_details(request):
    try:
        body = redact_sensitive(getattr(request, "data", None) or {})
        if isinstance(body, dict) and "api_base" in body:
            try:
                body["api_base"] = normalize_api_base(body.get("api_base"))
            except Exception:
                body["api_base"] = REDACTED
        return {
            "path": getattr(request, "path", ""),
            "body": body,
            "query": redact_sensitive(getattr(request, "query_params", None) or {}),
        }
    except Exception:
        return {"path": getattr(request, "path", ""), "body": REDACTED, "query": REDACTED}


def parse_connect_body(data, require_selection=False):
    if not isinstance(data, dict):
        raise AppApiException(500, _("请求无效"))
    raw_base = str(data.get("api_base") or "").strip()
    api_base = normalize_api_base(raw_base) if raw_base else configured_api_base()
    api_key = data.get("api_key")
    api_key = str(api_key).strip() if api_key is not None else ""
    if not api_key or len(api_key) > 512:
        raise AppApiException(500, _("API Key 无效"))
    raw_ids = data.get("model_ids", None)
    model_ids = None
    if raw_ids is not None:
        if not isinstance(raw_ids, list) or len(raw_ids) > 500:
            raise AppApiException(500, _("模型选择无效"))
        model_ids = []
        for item in raw_ids:
            model_id = str(item or "").strip()
            if model_id and model_id not in model_ids:
                model_ids.append(model_id)
        if require_selection and not model_ids:
            raise AppApiException(500, _("请选择至少一个模型"))
    elif require_selection:
        raise AppApiException(500, _("请选择至少一个模型"))
    model_types = _parse_model_types(data.get("model_types"))
    return api_base, api_key, model_ids, model_types


def _parse_model_types(raw_types):
    if raw_types in (None, ""):
        return {}
    if not isinstance(raw_types, dict) or len(raw_types) > 500:
        raise AppApiException(500, _("模型选择无效"))
    model_types = {}
    for raw_id, raw_type in raw_types.items():
        model_id = str(raw_id or "").strip()
        model_type = str(raw_type or "").strip()
        if not model_id:
            continue
        if model_type not in SELECTABLE_TYPES:
            raise AppApiException(500, _("模型选择无效"))
        model_types[model_id] = model_type
    return model_types


def list_workspace_base_models(workspace_id, model_type, model_id=None):
    if model_type not in SELECTABLE_TYPES:
        raise AppApiException(500, _("模型类型无效"))
    api_key = _workspace_api_key(workspace_id, model_id)
    if not api_key:
        return None
    _base, models = fetch_gateway_models(configured_api_base(), api_key)
    return base_model_options(models, model_type)


def _workspace_api_key(workspace_id, model_id=None):
    query = Model.objects.filter(workspace_id=workspace_id, provider=PROVIDER)
    model = query.filter(id=model_id).first() if model_id else None
    if model is None:
        model = query.order_by("-update_time").first()
    if model is None or not model.credential:
        return None
    try:
        stored = json.loads(rsa_long_decrypt(model.credential))
    except Exception:
        return None
    if not isinstance(stored, dict):
        return None
    api_key = str(stored.get("api_key") or "").strip()
    return api_key or None


def preview_zhiyun_models(api_base, api_key):
    base, models = fetch_gateway_models(api_base, api_key)
    return {"api_base": base, "summary": catalog_summary(models), "groups": group_models(models)}


def _import_type(item, model_types):
    model_type = item.get("model_type")
    if item.get("disabled_reason") == "too_long":
        return None
    if model_type in SELECTABLE_TYPES and item.get("selectable", True):
        return model_type
    if model_type == "UNKNOWN":
        chosen = (model_types or {}).get(item.get("id"))
        if chosen in SELECTABLE_TYPES:
            return chosen
    return None


def sync_zhiyun_models(workspace_id, user_id, api_base, api_key, model_ids, model_types=None):
    base, models = fetch_gateway_models(api_base, api_key)
    by_id = {item["id"]: item for item in models}
    importable = []
    skipped = []
    for model_id in model_ids:
        item = by_id.get(model_id)
        if item is None:
            skipped.append({"id": model_id, "reason": "not_in_catalog"})
            continue
        model_type = _import_type(item, model_types)
        if model_type is None:
            reason = "unconfirmed" if item.get("model_type") == "UNKNOWN" else "unsupported"
            skipped.append({"id": model_id, "reason": reason})
            continue
        importable.append((item, model_type))
    if not importable:
        raise AppApiException(500, _("没有可同步的模型"))
    created, updated, unchanged = [], [], []
    credential = {"api_base": base, "api_key": api_key}
    with transaction.atomic():
        for item, model_type in importable:
            outcome = _upsert_model(workspace_id, user_id, item, credential, model_type)
            if outcome == "created":
                created.append(item["id"])
            elif outcome == "updated":
                updated.append(item["id"])
            elif outcome == "unchanged":
                unchanged.append(item["id"])
            else:
                skipped.append({"id": item["id"], "reason": outcome})
    return {
        "api_base": base,
        "created": created,
        "updated": updated,
        "unchanged": unchanged,
        "skipped": skipped,
        "counts": {model_type: len(rows) for model_type, rows in group_models(models).items()},
    }


def _upsert_model(workspace_id, user_id, item, credential, model_type):
    model_id = item["id"]
    same = (
        Model.objects.select_for_update()
        .filter(workspace_id=workspace_id, provider=PROVIDER, model_name=model_id)
        .first()
    )
    if same is not None:
        return _refresh_existing(same, model_type, credential)
    named = Model.objects.select_for_update().filter(workspace_id=workspace_id, name=model_id).first()
    if named is not None:
        return "name_exists"
    model = Model(
        status=Status.SUCCESS,
        user_id=user_id,
        name=model_id,
        credential=rsa_long_encrypt(json.dumps(credential)),
        provider=PROVIDER,
        model_type=model_type,
        model_name=model_id,
        model_params_form=[],
        workspace_id=workspace_id,
    )
    model.save()
    if workspace_id != "None":
        UserResourcePermissionSerializer(data={
            "workspace_id": workspace_id,
            "user_id": user_id,
            "auth_target_type": AuthTargetType.MODEL.value,
        }).auth_resource(str(model.id))
    return "created"


def _refresh_existing(model, model_type, credential):
    try:
        stored = json.loads(rsa_long_decrypt(model.credential))
    except Exception:
        stored = None
    same_credential = credential_unchanged(stored, credential["api_base"], credential["api_key"])
    if same_credential and model.model_type == model_type and model.status == Status.SUCCESS:
        return "unchanged"
    model.credential = rsa_long_encrypt(json.dumps(credential))
    model.model_type = model_type
    model.status = Status.SUCCESS
    model.save(update_fields=["credential", "model_type", "status", "update_time"])
    return "updated"
