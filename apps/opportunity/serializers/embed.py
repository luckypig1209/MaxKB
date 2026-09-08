# coding=utf-8
"""嵌入客户端管理、令牌签发和会话查询。"""
from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone
from rest_framework import serializers

from common.exception.app_exception import AppApiException, AppAuthenticationFailed
from opportunity.models import OpportunityEmbedClient, OpportunityEmbedSession
from opportunity.serializers.common import model_time
from opportunity.services.embed_security import (
    DEFAULT_EMBED_SCOPES,
    create_client_id,
    create_client_secret,
    hash_client_secret,
    issue_embed_token,
    normalize_origins,
    normalize_scopes,
    revoke_embed_session,
    verify_client_secret,
)
from users.models import User
from maxkb.const import CONFIG


class EmbedClientWriteSerializer(serializers.Serializer):
    name = serializers.CharField(required=True, max_length=128)
    allowed_origins = serializers.ListField(
        child=serializers.CharField(max_length=512), required=True, allow_empty=False,
    )
    allowed_scopes = serializers.ListField(
        child=serializers.ChoiceField(choices=DEFAULT_EMBED_SCOPES), required=False,
        allow_empty=False, default=lambda: list(DEFAULT_EMBED_SCOPES),
    )
    token_ttl_seconds = serializers.IntegerField(required=False, min_value=60, max_value=900, default=300)
    is_active = serializers.BooleanField(required=False, default=True)

    def validate_allowed_origins(self, value):
        return normalize_origins(value)

    def validate_allowed_scopes(self, value):
        return normalize_scopes(value)


class EmbedTokenExchangeRequest(serializers.Serializer):
    client_id = serializers.CharField(required=True, max_length=64)
    client_secret = serializers.CharField(required=True, max_length=256, trim_whitespace=False)
    user_id = serializers.UUIDField(required=True)
    origin = serializers.CharField(required=True, max_length=512)
    department_ids = serializers.ListField(child=serializers.UUIDField(), required=False, default=list)
    scopes = serializers.ListField(
        child=serializers.ChoiceField(choices=DEFAULT_EMBED_SCOPES), required=False, allow_empty=False,
    )


def embed_client_to_dict(client: OpportunityEmbedClient) -> dict:
    now = timezone.now()
    return {
        'id': str(client.id),
        'workspace_id': client.workspace_id,
        'name': client.name,
        'client_id': client.client_id,
        'embed_path': f'{CONFIG.get_admin_path().rstrip("/")}/opportunity/embed/{client.client_id}',
        'allowed_origins': client.allowed_origins or [],
        'allowed_scopes': client.allowed_scopes or [],
        'token_ttl_seconds': client.token_ttl_seconds,
        'is_active': client.is_active,
        'creator_user_id': client.creator_user_id,
        'active_session_count': QuerySet(OpportunityEmbedSession).filter(
            client=client, revoked_at__isnull=True, expires_at__gt=now,
        ).count(),
        'last_used_at': model_time(client.last_used_at),
        'create_time': model_time(client.create_time),
        'update_time': model_time(client.update_time),
    }


class EmbedClientSerializer(serializers.Serializer):
    workspace_id = serializers.CharField(required=True, max_length=64)
    user_id = serializers.CharField(required=True, max_length=128)

    def list(self):
        self.is_valid(raise_exception=True)
        queryset = QuerySet(OpportunityEmbedClient).filter(
            workspace_id=self.validated_data['workspace_id'],
        ).order_by('-create_time')
        return [embed_client_to_dict(item) for item in queryset]

    def insert(self, instance: dict):
        self.is_valid(raise_exception=True)
        serializer = EmbedClientWriteSerializer(data=instance)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        secret = create_client_secret()
        client = OpportunityEmbedClient.objects.create(
            workspace_id=self.validated_data['workspace_id'],
            name=data['name'],
            client_id=create_client_id(),
            secret_digest=hash_client_secret(secret),
            allowed_origins=data['allowed_origins'],
            allowed_scopes=data['allowed_scopes'],
            token_ttl_seconds=data['token_ttl_seconds'],
            is_active=data['is_active'],
            creator_user_id=self.validated_data['user_id'],
        )
        return {
            **embed_client_to_dict(client),
            'client_secret': secret,
        }


class EmbedClientOperateSerializer(EmbedClientSerializer):
    client_id = serializers.UUIDField(required=True)

    def _get(self):
        self.is_valid(raise_exception=True)
        client = QuerySet(OpportunityEmbedClient).filter(
            workspace_id=self.validated_data['workspace_id'],
            id=self.validated_data['client_id'],
        ).first()
        if client is None:
            raise AppApiException(500, '嵌入客户端不存在')
        return client

    def update(self, instance: dict):
        client = self._get()
        serializer = EmbedClientWriteSerializer(data=instance, partial=True)
        serializer.is_valid(raise_exception=True)
        security_fields = {'allowed_origins', 'allowed_scopes', 'token_ttl_seconds', 'is_active'}
        revoke_sessions = any(
            field in serializer.validated_data and getattr(client, field) != value
            for field, value in serializer.validated_data.items()
            if field in security_fields
        )
        with transaction.atomic():
            for field, value in serializer.validated_data.items():
                setattr(client, field, value)
            client.save()
            if revoke_sessions:
                QuerySet(OpportunityEmbedSession).filter(
                    client=client, revoked_at__isnull=True,
                ).update(revoked_at=timezone.now(), update_time=timezone.now())
        return embed_client_to_dict(client)

    def disable(self):
        client = self._get()
        client.is_active = False
        with transaction.atomic():
            client.save(update_fields=['is_active', 'update_time'])
            QuerySet(OpportunityEmbedSession).filter(
                client=client, revoked_at__isnull=True,
            ).update(revoked_at=timezone.now(), update_time=timezone.now())
        return True

    def rotate_secret(self):
        client = self._get()
        secret = create_client_secret()
        with transaction.atomic():
            client.secret_digest = hash_client_secret(secret)
            client.save(update_fields=['secret_digest', 'update_time'])
            QuerySet(OpportunityEmbedSession).filter(
                client=client, revoked_at__isnull=True,
            ).update(revoked_at=timezone.now(), update_time=timezone.now())
        return {**embed_client_to_dict(client), 'client_secret': secret}


class EmbedTokenExchangeSerializer(serializers.Serializer):
    def exchange(self, instance: dict):
        serializer = EmbedTokenExchangeRequest(data=instance)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        client = QuerySet(OpportunityEmbedClient).filter(client_id=data['client_id'], is_active=True).first()
        if client is None or not verify_client_secret(data['client_secret'], client.secret_digest):
            raise AppAuthenticationFailed(1002, '嵌入客户端凭据无效')
        user = QuerySet(User).filter(id=data['user_id'], is_active=True).first()
        if user is None:
            raise AppAuthenticationFailed(1002, '嵌入用户不存在或已停用')
        token, session = issue_embed_token(
            client,
            user,
            data['origin'],
            department_ids=data.get('department_ids'),
            scopes=data.get('scopes'),
        )
        return {
            'access_token': token,
            'token_type': 'Bearer',
            'expires_in': client.token_ttl_seconds,
            'expires_at': model_time(session.expires_at),
            'session_id': str(session.id),
            'client_id': client.client_id,
            'embed_path': f'{CONFIG.get_admin_path().rstrip("/")}/opportunity/embed/{client.client_id}',
        }


class EmbedSessionOperateSerializer(serializers.Serializer):
    workspace_id = serializers.CharField(required=True, max_length=64)
    session_id = serializers.UUIDField(required=True)

    def revoke(self):
        self.is_valid(raise_exception=True)
        session = QuerySet(OpportunityEmbedSession).filter(
            workspace_id=self.validated_data['workspace_id'],
            id=self.validated_data['session_id'],
        ).first()
        if session is None:
            raise AppApiException(500, '嵌入会话不存在')
        revoke_embed_session(session)
        return True
