import atexit
import asyncio
import threading

import httpx

# Chat and embedding responses are parsed by the OpenAI SDK as they arrive.
# That client does not expose a reliable raw-body cap, so these calls do not
# claim the 1 MB limit used by the catalog and rerank requests. The bounds
# below are the equivalent controls: no redirects, split timeouts, a small
# connection pool, two transport retries, and the LLM max_tokens form
# (default 8192, maximum 100000). A reverse proxy in front of BIA should
# still limit upstream response size.
ZHIYUN_CONNECT_TIMEOUT_SECONDS = 5
ZHIYUN_READ_TIMEOUT_SECONDS = 120
ZHIYUN_WRITE_TIMEOUT_SECONDS = 30
ZHIYUN_POOL_TIMEOUT_SECONDS = 5
ZHIYUN_MAX_CONNECTIONS = 20
ZHIYUN_MAX_KEEPALIVE_CONNECTIONS = 10
ZHIYUN_TRANSPORT_RETRIES = 2
ZHIYUN_SDK_RETRIES = 2

_LOCK = threading.Lock()
_SYNC_CLIENT = None
_ASYNC_CLIENT = None


class _ProcessHttpxClient(httpx.Client):
    def close(self):
        return None

    def force_close(self):
        super().close()


class _ProcessAsyncHttpxClient(httpx.AsyncClient):
    def close(self):
        return None

    async def aclose(self):
        return None

    def force_close(self):
        _shutdown_async(super().aclose())


def zhiyun_timeout():
    return httpx.Timeout(
        connect=ZHIYUN_CONNECT_TIMEOUT_SECONDS,
        read=ZHIYUN_READ_TIMEOUT_SECONDS,
        write=ZHIYUN_WRITE_TIMEOUT_SECONDS,
        pool=ZHIYUN_POOL_TIMEOUT_SECONDS,
    )


def zhiyun_limits():
    return httpx.Limits(
        max_connections=ZHIYUN_MAX_CONNECTIONS,
        max_keepalive_connections=ZHIYUN_MAX_KEEPALIVE_CONNECTIONS,
    )


def build_zhiyun_sync_client():
    return _ProcessHttpxClient(
        timeout=zhiyun_timeout(),
        follow_redirects=False,
        transport=httpx.HTTPTransport(retries=ZHIYUN_TRANSPORT_RETRIES, limits=zhiyun_limits()),
    )


def build_zhiyun_async_client():
    return _ProcessAsyncHttpxClient(
        timeout=zhiyun_timeout(),
        follow_redirects=False,
        transport=httpx.AsyncHTTPTransport(retries=ZHIYUN_TRANSPORT_RETRIES, limits=zhiyun_limits()),
    )


def get_zhiyun_sync_client():
    global _SYNC_CLIENT
    with _LOCK:
        if _SYNC_CLIENT is None or _SYNC_CLIENT.is_closed:
            _SYNC_CLIENT = build_zhiyun_sync_client()
        return _SYNC_CLIENT


def get_zhiyun_async_client():
    global _ASYNC_CLIENT
    with _LOCK:
        if _ASYNC_CLIENT is None or _ASYNC_CLIENT.is_closed:
            _ASYNC_CLIENT = build_zhiyun_async_client()
        return _ASYNC_CLIENT


def _shutdown_async(coroutine):
    try:
        asyncio.run(coroutine)
    except RuntimeError:
        coroutine.close()


def close_zhiyun_http_clients():
    global _SYNC_CLIENT, _ASYNC_CLIENT
    with _LOCK:
        for client in (_SYNC_CLIENT, _ASYNC_CLIENT):
            if client is not None and not client.is_closed:
                client.force_close()
        _SYNC_CLIENT = None
        _ASYNC_CLIENT = None


atexit.register(close_zhiyun_http_clients)
