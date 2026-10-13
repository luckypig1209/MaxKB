import os

import openai
from django.utils.translation import gettext_lazy as _

from common.utils.common import get_file_content
from maxkb.conf import PROJECT_DIR
from models_provider.base_model_provider import IModelProvider, ModelInfo, ModelInfoManage, ModelProvideInfo, ModelTypeConst
from models_provider.impl.openai_model_provider.model.embedding import OpenAIEmbeddingModel
from models_provider.impl.openai_model_provider.model.llm import OpenAIChatModel
from models_provider.impl.zhiyun_model_provider.credential import (
    ZhiyunEmbeddingCredential,
    ZhiyunLLMModelCredential,
    ZhiyunRerankerCredential,
    prepare_zhiyun_credential,
)
from models_provider.impl.zhiyun_model_provider.reranker import ZhiyunReranker
from models_provider.impl.zhiyun_model_provider.transport import (
    ZHIYUN_SDK_RETRIES,
    get_zhiyun_async_client,
    get_zhiyun_sync_client,
)

llm_credential = ZhiyunLLMModelCredential()
embedding_credential = ZhiyunEmbeddingCredential()
reranker_credential = ZhiyunRerankerCredential()


def _tokenhub_model_kwargs(model_kwargs):
    kwargs = dict(model_kwargs or {})
    kwargs.pop("http_client", None)
    kwargs.pop("http_async_client", None)
    kwargs["max_retries"] = ZHIYUN_SDK_RETRIES
    return kwargs


class ZhiyunChatModel(OpenAIChatModel):
    @staticmethod
    def new_instance(model_type, model_name, model_credential, **model_kwargs):
        return OpenAIChatModel.new_instance(
            model_type,
            model_name,
            prepare_zhiyun_credential(model_credential),
            http_client=get_zhiyun_sync_client(),
            http_async_client=get_zhiyun_async_client(),
            **_tokenhub_model_kwargs(model_kwargs),
        )


class ZhiyunEmbeddingModel(OpenAIEmbeddingModel):
    def __init__(self, api_key, base_url, model_name, optional_params, http_client):
        self.client = openai.OpenAI(
            api_key=api_key,
            base_url=base_url,
            http_client=http_client,
            max_retries=ZHIYUN_SDK_RETRIES,
        ).embeddings
        self.model_name = model_name
        self.optional_params = optional_params
        self._http_client = http_client

    @staticmethod
    def new_instance(model_type, model_name, model_credential, **model_kwargs):
        credential = prepare_zhiyun_credential(model_credential)
        return ZhiyunEmbeddingModel(
            api_key=credential.get("api_key"),
            base_url=credential.get("api_base"),
            model_name=model_name,
            optional_params=OpenAIEmbeddingModel.filter_optional_params(model_kwargs),
            http_client=get_zhiyun_sync_client(),
        )


model_info_manage = (
    ModelInfoManage.builder()
    .append_model_info(ModelInfo(
        "deepseek-v4-flash-0731", "", ModelTypeConst.LLM, llm_credential, ZhiyunChatModel,
    ))
    .append_default_model_info(ModelInfo(
        "deepseek-v4-flash-0731", "", ModelTypeConst.LLM, llm_credential, ZhiyunChatModel,
    ))
    .append_model_info(ModelInfo(
        "text-embedding-v4", "", ModelTypeConst.EMBEDDING, embedding_credential, ZhiyunEmbeddingModel,
    ))
    .append_default_model_info(ModelInfo(
        "text-embedding-v4", "", ModelTypeConst.EMBEDDING, embedding_credential, ZhiyunEmbeddingModel,
    ))
    .append_model_info(ModelInfo(
        "qwen3-rerank", "", ModelTypeConst.RERANKER, reranker_credential, ZhiyunReranker,
    ))
    .append_default_model_info(ModelInfo(
        "qwen3-rerank", "", ModelTypeConst.RERANKER, reranker_credential, ZhiyunReranker,
    ))
    .build()
)


class ZhiyunModelProvider(IModelProvider):
    def get_model_info_manage(self):
        return model_info_manage

    def get_model_provide_info(self):
        return ModelProvideInfo(
            provider="model_zhiyun_provider",
            name=_("智云TokenHub"),
            icon=get_file_content(os.path.join(
                PROJECT_DIR, "apps", "models_provider", "impl", "zhiyun_model_provider", "icon", "zhiyun_icon_svg",
            )),
        )
