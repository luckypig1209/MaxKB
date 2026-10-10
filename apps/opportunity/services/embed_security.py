# coding=utf-8
"""业务系统嵌入客户端与短期访问令牌。"""
import secrets
import ipaddress
import re
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import urlsplit

from django.contrib.auth.hashers import check_password, make_password
from django.core import signing
from django.db.models import QuerySet
from django.utils import timezone

from common.exception.app_exception import AppApiException, AppAuthenticationFailed, NotFound404
from maxkb.const import CONFIG
from opportunity.models import DepartmentProfile, DepartmentStatus, OpportunityEmbedClient, OpportunityEmbedSession
from users.models import User

TOKEN_SALT = 'bia.opportunity.embed.v1'
TOKEN_TYPE = 'OPPORTUNITY_EMBED'
MIN_TOKEN_TTL_SECONDS = 60
MAX_TOKEN_TTL_SECONDS = 900
MAX_ACTIVE_SESSIONS_PER_CLIENT = 1000
EMBED_ENABLED_CONFIG_KEY = 'OPPORTUNITY_EMBED_ENABLED'
EMBED_FEATURE_DISABLED_CODE = 404
EMBED_FEATURE_DISABLED_MESSAGE = '嵌入接入功能未启用'
EMBED_FEATURE_DISABLED_HTTP_STATUS = 404
DEFAULT_EMBED_SCOPES = [
    'analysis:create',
    'analysis:read',
    'analysis:decision',
    'report:export',
]


def is_opportunity_embed_enabled() -> bool:
    """Return whether the opportunity embed integration is enabled.

    Configuration values can come from YAML or environment variables, so keep
    the boolean coercion explicit instead of relying on Python's truthiness
    (where the string ``"false"`` would otherwise be treated as true).
    """

    value = CONFIG.get(EMBED_ENABLED_CONFIG_KEY, False)
    if isinstance(value, str):
        return value.strip().lower() in {'1', 'true', 'yes', 'on'}
    return bool(value)


def ensure_opportunity_embed_enabled() -> None:
    """Raise the stable disabled response used by every embed endpoint."""

    if not is_opportunity_embed_enabled():
        raise NotFound404(EMBED_FEATURE_DISABLED_CODE, EMBED_FEATURE_DISABLED_MESSAGE)


@dataclass(frozen=True)
class OpportunityEmbedAuthContext:
    workspace_id: str
    client_id: str
    session_id: str
    user_id: str
    origin: str
    department_ids: tuple[str, ...]
    scopes: tuple[str, ...]
    expires_at: str

    def has_scope(self, scope: str) -> bool:
        return scope in self.scopes


def normalize_origin(value: str) -> str:
    raw = str(value or '').strip()
    if any(char in raw for char in ('\r', '\n', '\t', ' ', "'", '"', ';', '*')):
        raise AppApiException(500, '嵌入来源包含不安全字符')
    parts = urlsplit(raw)
    if parts.scheme.lower() not in ('http', 'https') or not parts.netloc:
        raise AppApiException(500, '嵌入来源必须是完整的 HTTP(S) Origin')
    if parts.username or parts.password or parts.path not in ('', '/') or parts.query or parts.fragment:
        raise AppApiException(500, '嵌入来源只能包含协议、主机和端口')
    try:
        port = parts.port
    except ValueError as exc:
        raise AppApiException(500, '嵌入来源端口无效') from exc
    host = parts.hostname or ''
    try:
        ipaddress.ip_address(host)
    except ValueError:
        try:
            host = host.encode('idna').decode('ascii')
        except UnicodeError as exc:
            raise AppApiException(500, '嵌入来源主机名无效') from exc
        labels = host.split('.')
        if len(host) > 253 or any(
            not label or len(label) > 63 or label.startswith('-') or label.endswith('-')
            or re.fullmatch(r'[A-Za-z0-9-]+', label) is None
            for label in labels
        ):
            raise AppApiException(500, '嵌入来源主机名无效')
    if ':' in host:
        host = f'[{host}]'
    default_port = (parts.scheme.lower() == 'http' and port == 80) or (
        parts.scheme.lower() == 'https' and port == 443
    )
    port_part = '' if port is None or default_port else f':{port}'
    return f'{parts.scheme.lower()}://{host.lower()}{port_part}'


def normalize_origins(values) -> list[str]:
    origins = list(dict.fromkeys(normalize_origin(item) for item in (values or [])))
    if not origins:
        raise AppApiException(500, '至少配置一个允许嵌入来源')
    if len(origins) > 20:
        raise AppApiException(500, '允许嵌入来源最多配置 20 个')
    return origins


def normalize_scopes(values, allowed=None) -> list[str]:
    scopes = list(dict.fromkeys(str(item) for item in (values or DEFAULT_EMBED_SCOPES)))
    unknown = set(scopes) - set(DEFAULT_EMBED_SCOPES)
    if unknown:
        raise AppApiException(500, f'不支持的嵌入权限：{",".join(sorted(unknown))}')
    if allowed is not None and not set(scopes).issubset(set(allowed)):
        raise AppApiException(500, '申请的权限超出客户端授权范围')
    return scopes


def create_client_secret() -> str:
    return f'opp_secret_{secrets.token_urlsafe(32)}'


def hash_client_secret(secret: str) -> str:
    return make_password(secret)


def verify_client_secret(secret: str, digest: str) -> bool:
    return bool(secret and digest and check_password(secret, digest))


def create_client_id() -> str:
    return f'opp_{secrets.token_urlsafe(18)}'


def is_user_workspace_member(user: User, workspace_id: str) -> bool:
    if not user.is_active:
        return False
    from common.auth.handle.impl.user_token import get_auth
    roles = {str(item) for item in get_auth(user).role_list}
    if 'ADMIN' in roles or 'EXTENDS_ADMIN' in roles:
        return True
    workspace_roles = {
        f'WORKSPACE_MANAGE:/WORKSPACE/{workspace_id}',
        f'USER:/WORKSPACE/{workspace_id}',
        f'EXTENDS_WORKSPACE_MANAGE:/WORKSPACE/{workspace_id}',
        f'EXTENDS_USER:/WORKSPACE/{workspace_id}',
    }
    return bool(roles.intersection(workspace_roles))


def validate_department_ids(workspace_id: str, values) -> list[str]:
    ids = list(dict.fromkeys(str(item) for item in (values or [])))
    if not ids:
        return []
    count = QuerySet(DepartmentProfile).filter(
        workspace_id=workspace_id,
        id__in=ids,
        status=DepartmentStatus.ACTIVE,
    ).count()
    if count != len(ids):
        raise AppApiException(500, '部门不存在、已停用或不属于当前工作空间')
    return ids


def issue_embed_token(
    client: OpportunityEmbedClient,
    user: User,
    origin: str,
    department_ids=None,
    scopes=None,
) -> tuple[str, OpportunityEmbedSession]:
    if not client.is_active:
        raise AppAuthenticationFailed(1002, '嵌入客户端已停用')
    normalized_origin = normalize_origin(origin)
    if normalized_origin not in (client.allowed_origins or []):
        raise AppAuthenticationFailed(1002, '嵌入来源未授权')
    if not is_user_workspace_member(user, client.workspace_id):
        raise AppAuthenticationFailed(1002, '用户无权访问该工作空间')
    requested_scopes = normalize_scopes(scopes, allowed=client.allowed_scopes or DEFAULT_EMBED_SCOPES)
    departments = validate_department_ids(client.workspace_id, department_ids)
    now = timezone.now()
    active_count = QuerySet(OpportunityEmbedSession).filter(
        client=client,
        revoked_at__isnull=True,
        expires_at__gt=now,
    ).count()
    if active_count >= MAX_ACTIVE_SESSIONS_PER_CLIENT:
        raise AppApiException(500, '嵌入客户端的有效会话数已达到上限')
    ttl = min(max(int(client.token_ttl_seconds), MIN_TOKEN_TTL_SECONDS), MAX_TOKEN_TTL_SECONDS)
    session = OpportunityEmbedSession.objects.create(
        workspace_id=client.workspace_id,
        client=client,
        user_id=str(user.id),
        origin=normalized_origin,
        department_ids=departments,
        scopes=requested_scopes,
        expires_at=now + timedelta(seconds=ttl),
    )
    payload = {
        'type': TOKEN_TYPE,
        'version': 1,
        'session_id': str(session.id),
        'client_id': client.client_id,
        'workspace_id': client.workspace_id,
        'user_id': str(user.id),
        'origin': normalized_origin,
        'department_ids': departments,
        'scopes': requested_scopes,
        'expires_at': session.expires_at.isoformat(),
        'jti': str(session.id),
    }
    token = signing.dumps(payload, salt=TOKEN_SALT, compress=True)
    client.last_used_at = now
    client.save(update_fields=['last_used_at', 'update_time'])
    return token, session


def validate_embed_token(token: str, required_scope=None) -> tuple[User, OpportunityEmbedAuthContext]:
    if not token or len(token) > 4096:
        raise AppAuthenticationFailed(1002, '嵌入令牌无效')
    try:
        payload = signing.loads(token, salt=TOKEN_SALT, max_age=MAX_TOKEN_TTL_SECONDS)
    except signing.SignatureExpired as exc:
        raise AppAuthenticationFailed(1002, '嵌入令牌已过期') from exc
    except signing.BadSignature as exc:
        raise AppAuthenticationFailed(1002, '嵌入令牌无效') from exc
    if payload.get('type') != TOKEN_TYPE or payload.get('version') != 1:
        raise AppAuthenticationFailed(1002, '嵌入令牌类型无效')
    session = QuerySet(OpportunityEmbedSession).select_related('client').filter(
        id=payload.get('session_id'),
    ).first()
    now = timezone.now()
    if session is None or session.revoked_at or session.expires_at <= now or not session.client.is_active:
        raise AppAuthenticationFailed(1002, '嵌入会话无效或已过期')
    expected = {
        'client_id': session.client.client_id,
        'workspace_id': session.workspace_id,
        'user_id': session.user_id,
        'origin': session.origin,
        'expires_at': session.expires_at.isoformat(),
        'jti': str(session.id),
    }
    if any(str(payload.get(key)) != str(value) for key, value in expected.items()):
        raise AppAuthenticationFailed(1002, '嵌入令牌上下文不一致')
    if [str(item) for item in payload.get('department_ids') or []] != [
        str(item) for item in session.department_ids or []
    ] or [str(item) for item in payload.get('scopes') or []] != [
        str(item) for item in session.scopes or []
    ]:
        raise AppAuthenticationFailed(1002, '嵌入令牌授权范围不一致')
    if required_scope and required_scope not in (session.scopes or []):
        raise AppAuthenticationFailed(1002, '嵌入令牌权限不足')
    user = QuerySet(User).filter(id=session.user_id, is_active=True).first()
    if user is None or not is_user_workspace_member(user, session.workspace_id):
        raise AppAuthenticationFailed(1002, '嵌入用户无效或权限已变更')
    if session.last_seen_at is None or session.last_seen_at < now - timedelta(seconds=60):
        QuerySet(OpportunityEmbedSession).filter(id=session.id).update(last_seen_at=now, update_time=now)
    context = OpportunityEmbedAuthContext(
        workspace_id=session.workspace_id,
        client_id=session.client.client_id,
        session_id=str(session.id),
        user_id=session.user_id,
        origin=session.origin,
        department_ids=tuple(str(item) for item in (session.department_ids or [])),
        scopes=tuple(str(item) for item in (session.scopes or [])),
        expires_at=session.expires_at.isoformat(),
    )
    return user, context


def revoke_embed_session(session: OpportunityEmbedSession):
    if session.revoked_at is None:
        session.revoked_at = timezone.now()
        session.save(update_fields=['revoked_at', 'update_time'])
    return session
