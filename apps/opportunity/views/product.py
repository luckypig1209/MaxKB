# coding=utf-8
"""
    @project: MaxKB
    @Author：bia
    @file： product.py
    @date：2026/9/3
    @desc:
"""
from django.utils.translation import gettext_lazy as _
from drf_spectacular.utils import extend_schema
from rest_framework.request import Request
from rest_framework.views import APIView

from common import result
from common.auth import TokenAuth
from common.auth.authentication import has_permissions
from opportunity.api.product import ProductAPI, ProductBindingAPI
from opportunity.serializers.product import ProductDocumentBindingSerializer, ProductOperateSerializer, ProductSerializer
from opportunity.views.setting import READ_ROLES, WRITE_ROLES
from users.serializers.user import is_workspace_manage


def _can_view_product_support(request, workspace_id: str) -> bool:
    """Support contacts are restricted to workspace managers at the API boundary."""
    user_id = getattr(getattr(request, 'user', None), 'id', None)
    return bool(user_id and is_workspace_manage(str(user_id), workspace_id))


class ProductView(APIView):
    authentication_classes = [TokenAuth]

    @extend_schema(
        methods=['GET'],
        description=_('List products'),
        summary=_('List products'),
        operation_id=_('List products'),
        parameters=ProductAPI.get_parameters(),
        responses=ProductAPI.get_response(),
        tags=[_('Opportunity')],
    )
    @has_permissions(*READ_ROLES)
    def get(self, request: Request, workspace_id: str):
        return result.success(ProductSerializer(data={'workspace_id': workspace_id}).list(
            filters=request.query_params,
            include_support=_can_view_product_support(request, workspace_id),
        ))

    @extend_schema(
        methods=['POST'],
        description=_('Create product'),
        summary=_('Create product'),
        operation_id=_('Create product'),
        parameters=ProductAPI.get_parameters(),
        request=ProductAPI.get_request(),
        responses=ProductAPI.get_response(),
        tags=[_('Opportunity')],
    )
    @has_permissions(*WRITE_ROLES)
    def post(self, request: Request, workspace_id: str):
        return result.success(ProductSerializer(data={'workspace_id': workspace_id}).insert(
            request.data,
            include_support=_can_view_product_support(request, workspace_id),
        ))

    class Operate(APIView):
        authentication_classes = [TokenAuth]

        @extend_schema(
            methods=['GET'],
            description=_('Get product'),
            summary=_('Get product'),
            operation_id=_('Get product'),
            parameters=ProductAPI.get_parameters(),
            responses=ProductAPI.get_response(),
            tags=[_('Opportunity')],
        )
        @has_permissions(*READ_ROLES)
        def get(self, request: Request, workspace_id: str, product_id: str):
            return result.success(ProductOperateSerializer(
                data={'workspace_id': workspace_id, 'product_id': product_id}).one(
                    include_support=_can_view_product_support(request, workspace_id),
                ))

        @extend_schema(
            methods=['PUT'],
            description=_('Update product'),
            summary=_('Update product'),
            operation_id=_('Update product'),
            parameters=ProductAPI.get_parameters(),
            request=ProductAPI.get_request(),
            responses=ProductAPI.get_response(),
            tags=[_('Opportunity')],
        )
        @has_permissions(*WRITE_ROLES)
        def put(self, request: Request, workspace_id: str, product_id: str):
            return result.success(ProductOperateSerializer(
                data={'workspace_id': workspace_id, 'product_id': product_id}).update(
                    request.data,
                    include_support=_can_view_product_support(request, workspace_id),
                ))

        @extend_schema(
            methods=['DELETE'],
            description=_('Delete product'),
            summary=_('Delete product'),
            operation_id=_('Delete product'),
            parameters=ProductAPI.get_parameters(),
            responses=ProductAPI.get_response(),
            tags=[_('Opportunity')],
        )
        @has_permissions(*WRITE_ROLES)
        def delete(self, request: Request, workspace_id: str, product_id: str):
            return result.success(ProductOperateSerializer(
                data={'workspace_id': workspace_id, 'product_id': product_id}).delete())

    class Binding(APIView):
        authentication_classes = [TokenAuth]

        @extend_schema(
            methods=['PUT'],
            description=_('Bind product document metadata'),
            summary=_('Bind product document metadata'),
            operation_id=_('Bind product document metadata'),
            parameters=ProductBindingAPI.get_parameters(),
            request=ProductBindingAPI.get_request(),
            responses=ProductBindingAPI.get_response(),
            tags=[_('Opportunity')],
        )
        @has_permissions(*WRITE_ROLES)
        def put(self, request: Request, workspace_id: str, product_id: str, document_id: str):
            return result.success(ProductDocumentBindingSerializer(data={
                'workspace_id': workspace_id,
                'product_id': product_id,
                'document_id': document_id,
            }).bind(request.data))
