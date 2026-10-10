"""Shared system-user session issuance.

The password login flow and future trusted-login flows must issue exactly the
same kind of MaxKB session.  Keeping the token payload and cache operation in
one small service avoids accidentally introducing a second authentication
format for portal SSO.
"""

from common.auth.common import FileToken
from common.constants.authentication_type import AuthenticationType
from common.constants.cache_version import Cache_Version
from django.core import signing
from django.core.cache import cache
from maxkb.const import CONFIG


def issue_system_user_session(user):
    """Issue the existing API token and ``mk_file_auth`` token for ``user``.

    The returned tuple intentionally matches ``LoginSerializer.login``'s
    existing return value: ``({"token": token}, file_token)``.  The token
    payload, cache version/key, timeout and FileToken type are kept identical
    to the historical password-login implementation so ``TokenAuth`` accepts
    sessions issued by either path.
    """

    token = signing.dumps(
        {
            "username": user.username,
            "id": str(user.id),
            "email": user.email,
            "type": AuthenticationType.SYSTEM_USER.value,
        }
    )

    version, get_key = Cache_Version.TOKEN.value
    timeout = CONFIG.get_session_timeout()
    cache.set(get_key(token), user, timeout=timeout, version=version)

    file_token = FileToken(str(user.id), AuthenticationType.SYSTEM_USER.value).to_token()
    return {"token": token}, file_token
