from typing import Dict

from django.utils.translation import gettext as _
from langchain_core.messages import HumanMessage

from common import forms
from common.exception.app_exception import AppApiException
from common.forms import BaseForm, TooltipLabel
from common.utils.logger import maxkb_logger
from models_provider.base_model_provider import BaseModelCredential, ValidCode
from models_provider.impl.openai_model_provider.credential.llm import OpenAILLMModelParams
from models_provider.impl.zhiyun_model_provider.catalog import (
    catalog_accepts,
    configured_api_base,
    fetch_gateway_models,
    redact,
)


class ZhiyunLLMModelCredential(BaseForm, BaseModelCredential):
    api_key = forms.PasswordInputField("API Key", required=True)

    def is_valid(self, model_type: str, model_name, model_credential: Dict[str, object], model_params, provider,
                 raise_exception=False):
        apply_fixed_gateway(model_credential)
        _require_listed_model(model_type, model_name, model_credential, provider, raise_exception)
        secret = str(model_credential.get("api_key") or "")
        try:
            model = provider.get_model(model_type, model_name, model_credential, **(model_params or {}))
            model.invoke([HumanMessage(content=_("Hello"))])
        except Exception as exc:
            maxkb_logger.error("Zhiyun LLM verification failed: %s", redact(exc, secret))
            if isinstance(exc, AppApiException):
                raise
            if raise_exception:
                raise AppApiException(
                    ValidCode.valid_error.value,
                    _("Verification failed, please check whether the parameters are correct: {error}").format(
                        error=redact(exc, secret)),
                )
            return False
        return True

    def encryption_dict(self, model: Dict[str, object]):
        prepared = prepare_zhiyun_credential(model)
        return {**prepared, "api_key": super().encryption(prepared.get("api_key", ""))}

    def get_model_params_setting_form(self, model_name):
        return OpenAILLMModelParams()


class ZhiyunEmbeddingCredential(BaseForm, BaseModelCredential):
    api_key = forms.PasswordInputField("API Key", required=True)

    def is_valid(self, model_type: str, model_name, model_credential: Dict[str, object], model_params, provider,
                 raise_exception=False):
        apply_fixed_gateway(model_credential)
        _require_listed_model(model_type, model_name, model_credential, provider, raise_exception)
        secret = str(model_credential.get("api_key") or "")
        try:
            model = provider.get_model(model_type, model_name, model_credential)
            model.embed_query(_("Hello"))
        except Exception as exc:
            maxkb_logger.error("Zhiyun embedding verification failed: %s", redact(exc, secret))
            if isinstance(exc, AppApiException):
                raise
            if raise_exception:
                raise AppApiException(
                    ValidCode.valid_error.value,
                    _("Verification failed, please check whether the parameters are correct: {error}").format(
                        error=redact(exc, secret)),
                )
            return False
        return True

    def encryption_dict(self, model: Dict[str, object]):
        prepared = prepare_zhiyun_credential(model)
        return {**prepared, "api_key": super().encryption(prepared.get("api_key", ""))}

    def get_model_params_setting_form(self, model_name):
        return None


class ZhiyunRerankerModelParams(BaseForm):
    top_n = forms.SliderField(
        TooltipLabel(_("Top N"), _("Number of top documents to return after reranking")),
        required=True,
        default_value=3,
        _min=1,
        _max=100,
        _step=1,
        precision=0,
    )


class ZhiyunRerankerCredential(BaseForm, BaseModelCredential):
    api_key = forms.PasswordInputField("API Key", required=True)

    def is_valid(self, model_type: str, model_name, model_credential: Dict[str, object], model_params, provider,
                 raise_exception=False):
        apply_fixed_gateway(model_credential)
        _require_listed_model(model_type, model_name, model_credential, provider, raise_exception)
        return True

    def encryption_dict(self, model: Dict[str, object]):
        prepared = prepare_zhiyun_credential(model)
        return {**prepared, "api_key": super().encryption(prepared.get("api_key", ""))}

    def get_model_params_setting_form(self, model_name):
        return ZhiyunRerankerModelParams()


def prepare_zhiyun_credential(model_credential):
    credential = dict(model_credential or {})
    credential["api_base"] = configured_api_base()
    return credential


def apply_fixed_gateway(model_credential):
    prepared = prepare_zhiyun_credential(model_credential)
    if isinstance(model_credential, dict):
        model_credential.clear()
        model_credential.update(prepared)
    return prepared


def _require_listed_model(model_type, model_name, model_credential, provider, raise_exception):
    model_type_list = provider.get_model_type_list()
    if not any(item.get("value") == model_type for item in model_type_list):
        raise AppApiException(
            ValidCode.valid_error.value,
            _("{model_type} Model type is not supported").format(model_type=model_type),
        )
    for key in ("api_base", "api_key"):
        if not model_credential.get(key):
            if raise_exception:
                raise AppApiException(ValidCode.valid_error.value, _("{key}  is required").format(key=key))
            raise AppApiException(ValidCode.valid_error.value, _("{key}  is required").format(key=key))
    try:
        _base, models = fetch_gateway_models(model_credential.get("api_base"), model_credential.get("api_key"))
    except AppApiException:
        raise
    except Exception as exc:
        secret = str(model_credential.get("api_key") or "")
        raise AppApiException(ValidCode.valid_error.value, redact(exc, secret))
    if not any(catalog_accepts(item, model_name, model_type) for item in models):
        raise AppApiException(ValidCode.valid_error.value, _("The model does not exist, please download the model first"))
