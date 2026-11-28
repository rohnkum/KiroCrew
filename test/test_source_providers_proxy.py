"""A source provider's REST read goes through the configured forward proxy.

aiohttp ignores ``HTTPS_PROXY``, so on a host whose only way out is the proxy a
provider that dials directly never reaches the operator's Jira, Linear, Gerrit,
ServiceNow or Bitbucket Server instance.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import pytest

from kiro_crew.dashboard.source_providers import (
    bitbucket_server,
    gerrit,
    hosts,
    jira,
    linear,
    servicenow,
)
from kiro_crew.dashboard.source_providers.contract import SourceRef

#: Every variable the proxy lookup reads, cleared so the host's own cannot leak in.
_PROXY_VARS = (
    "HTTPS_PROXY",
    "HTTP_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
    "https_proxy",
    "http_proxy",
    "all_proxy",
    "no_proxy",
)
_PROXY = "http://proxy.invalid:3128"
_HOST = "source.example"


class _Dialed(Exception):
    """Raised by the fake session once it has recorded the request's proxy."""


class _Session:
    def __init__(self, proxies: list[str | None]) -> None:
        self._proxies = proxies

    def get(self, url: Any, **kwargs: Any) -> Any:
        self._proxies.append(kwargs.get("proxy"))
        raise _Dialed

    post = get

    async def __aenter__(self) -> _Session:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


def _ref(provider: str) -> SourceRef:
    return SourceRef(
        provider=provider, url=f"https://{_HOST}/c/r/+/1", host=_HOST, owner="P", repo="r", number=1
    )


async def _jira(monkeypatch: pytest.MonkeyPatch, session: _Session) -> None:
    monkeypatch.setattr(jira.aiohttp, "ClientSession", lambda *a, **k: session)
    await jira._jira_get_json(
        f"https://{_HOST}/rest/api/2/issue/P-1",
        {},
        host=_HOST,
        subject="this issue",
        not_found="",
        what="P-1",
    )


async def _linear(monkeypatch: pytest.MonkeyPatch, session: _Session) -> None:
    monkeypatch.setattr(linear, "ClientSession", lambda *a, **k: session)
    await linear._post(b"{}", "key")


async def _servicenow(monkeypatch: pytest.MonkeyPatch, session: _Session) -> None:
    monkeypatch.setattr(servicenow, "ClientSession", lambda *a, **k: session)
    await servicenow._get(servicenow.table_url(_HOST, "incident"), "key")


async def _gerrit(monkeypatch: pytest.MonkeyPatch, session: Any) -> None:
    monkeypatch.setattr(hosts, "_gerrit_hosts_snapshot", frozenset({_HOST}))
    client = gerrit._Client(_ref("gerrit"), session, has_credential=False, secret_name="")
    await client.get(client.change_api, cap=1)


async def _bitbucket_server(monkeypatch: pytest.MonkeyPatch, session: Any) -> None:
    monkeypatch.setattr(hosts, "_bitbucket_server_hosts_snapshot", frozenset({_HOST}))
    client = bitbucket_server._Client(_ref("bitbucket_server"), session, has_token=False)
    await client.get(client.pr_api, cap=1)


_Read = Callable[[pytest.MonkeyPatch, Any], Awaitable[None]]
#: provider -> (the host its request names, one REST read through its own request path)
_READS: dict[str, tuple[str, _Read]] = {
    "bitbucket_server": (_HOST, _bitbucket_server),
    "gerrit": (_HOST, _gerrit),
    "jira": (_HOST, _jira),
    "linear": ("api.linear.app", _linear),
    "servicenow": (_HOST, _servicenow),
}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("bypassed", "expected"), [(False, _PROXY), (True, None)], ids=["proxied", "no-proxy-host"]
)
@pytest.mark.parametrize("provider", sorted(_READS))
async def test_provider_read_goes_through_the_configured_proxy(
    monkeypatch: pytest.MonkeyPatch, provider: str, bypassed: bool, expected: str | None
) -> None:
    for var in _PROXY_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("HTTPS_PROXY", _PROXY)
    host, read = _READS[provider]
    if bypassed:
        # A host the operator lists in NO_PROXY is still dialed directly.
        monkeypatch.setenv("NO_PROXY", host)
    proxies: list[str | None] = []

    with pytest.raises(_Dialed):
        await read(monkeypatch, _Session(proxies))

    assert proxies == [expected]
