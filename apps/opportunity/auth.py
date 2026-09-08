# coding=utf-8
from rest_framework.authentication import BaseAuthentication

from common.exception.app_exception import AppAuthenticationFailed
from opportunity.services.embed_security import validate_embed_token


class OpportunityEmbedTokenAuth(BaseAuthentication):
    keyword = 'Bearer'

    def authenticate(self, request):
        auth = request.META.get('HTTP_AUTHORIZATION') or ''
        if not auth.startswith(f'{self.keyword} '):
            raise AppAuthenticationFailed(1003, '请提供嵌入访问令牌')
        return validate_embed_token(auth[len(self.keyword) + 1:])
