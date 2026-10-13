from typing import Dict, Optional, Sequence

from django.utils.translation import gettext as _
from langchain_core.callbacks import Callbacks
from langchain_core.documents import BaseDocumentCompressor, Document

from common.exception.app_exception import AppApiException
from models_provider.base_model_provider import MaxKBBaseModel
from models_provider.impl.zhiyun_model_provider.catalog import (
    gateway_request_json,
    normalize_api_base,
    parse_rerank_results,
)


class ZhiyunReranker(MaxKBBaseModel, BaseDocumentCompressor):
    api_key: str
    api_base: str
    model_name: str
    top_n: int = 3

    @staticmethod
    def is_cache_model():
        return False

    @staticmethod
    def new_instance(model_type, model_name, model_credential: Dict[str, object], **model_kwargs):
        try:
            top_n = int(model_kwargs.get("top_n", 3))
        except (TypeError, ValueError):
            top_n = 3
        return ZhiyunReranker(
            api_key=str(model_credential.get("api_key") or ""),
            api_base=normalize_api_base(model_credential.get("api_base")),
            model_name=model_name,
            top_n=top_n,
        )

    def compress_documents(self, documents: Sequence[Document], query: str, callbacks: Optional[Callbacks] = None) -> \
            Sequence[Document]:
        if not documents:
            return []
        try:
            payload = gateway_request_json(
                "POST",
                "/rerank",
                self.api_key,
                json_body={
                    "model": self.model_name,
                    "query": query,
                    "documents": [item.page_content for item in documents],
                    "top_n": self.top_n,
                },
                read_timeout=60,
            )
            rows = parse_rerank_results(payload)
        except AppApiException:
            raise
        except Exception:
            raise AppApiException(500, _("智云网关请求失败")) from None
        reranked = []
        for item in rows:
            if not isinstance(item, dict):
                continue
            index = item.get("index")
            if not isinstance(index, int) or index < 0 or index >= len(documents):
                continue
            source = documents[index]
            score = item.get("relevance_score", item.get("score"))
            reranked.append(Document(
                page_content=source.page_content,
                metadata={**source.metadata, "relevance_score": score},
            ))
        return reranked
