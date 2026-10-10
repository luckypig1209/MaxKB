# coding=utf-8
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter

from common.mixins.api_mixin import APIMixin
from common.result import DefaultResultSerializer
from opportunity.serializers.product import DocumentBindingSerializer, ProductWriteSerializer


class ProductAPI(APIMixin):
    @staticmethod
    def get_parameters():
        return [
            OpenApiParameter(name='workspace_id', description='工作空间id', type=OpenApiTypes.STR,
                             location='path', required=True),
            OpenApiParameter(name='name', description='按产品名称筛选', type=OpenApiTypes.STR,
                             location='query', required=False),
            OpenApiParameter(name='alias', description='按产品别名筛选', type=OpenApiTypes.STR,
                             location='query', required=False),
            OpenApiParameter(name='product_line', description='按产品线筛选', type=OpenApiTypes.STR,
                             location='query', required=False),
            OpenApiParameter(name='department', description='按主责部门编码或名称筛选', type=OpenApiTypes.STR,
                             location='query', required=False),
            OpenApiParameter(name='knowledge_status', description='按资料状态筛选 READY/PENDING',
                             type=OpenApiTypes.STR, location='query', required=False),
        ]

    @staticmethod
    def get_request():
        return ProductWriteSerializer

    @staticmethod
    def get_response():
        return DefaultResultSerializer


class ProductBindingAPI(APIMixin):
    @staticmethod
    def get_parameters():
        return [
            OpenApiParameter(name='workspace_id', description='工作空间id', type=OpenApiTypes.STR,
                             location='path', required=True),
            OpenApiParameter(name='product_id', description='产品id', type=OpenApiTypes.STR,
                             location='path', required=True),
            OpenApiParameter(name='document_id', description='文档id', type=OpenApiTypes.STR,
                             location='path', required=True),
        ]

    @staticmethod
    def get_request():
        return DocumentBindingSerializer

    @staticmethod
    def get_response():
        return DefaultResultSerializer
