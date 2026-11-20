"""Web search for the Researcher (PRD D62): Tavily's HTTP API.

The key lives in the OS key store like every provider key (`SEARCH_KEY_REF`), is sent only as the
`Authorization` header to Tavily's one address, and is never returned, logged or put in an error.

What leaves the machine is the query, so it is cleaned first (anything that looks like a secret is
replaced) and kept short. What comes back is untrusted: every title and snippet is screened and
marked (D50), and a result whose address could not be read later (not a public https address) is
dropped and counted. The cost is reported in **Tavily credits as Tavily states them**; when Tavily
does not say, it is `None`, never a guess.
"""

from dataclasses import dataclass

import httpx
from fastapi.concurrency import run_in_threadpool
from pydantic import SecretStr

from app.context.redact import redact
from app.guardrails.injection import mark, screen
from app.providers.secrets import KeyStore, KeyStoreError
from app.research.web import USER_AGENT, WebError, check_url

SEARCH_KEY_REF = "search-tavily"
ENDPOINT = "https://api.tavily.com/search"
MAX_QUERY_CHARS = 400
MAX_RESULTS = 8
SNIPPET_CHARS = 1000
TIMEOUT_SECONDS = 20

_PROBLEMS = {
    401: "the search key was rejected: check it or set a new one",
    429: "the search service said too many requests; try again in a moment",
    432: "the search allowance is used up (the key's or the plan's limit)",
    433: "the search allowance is used up (the pay-as-you-go limit)",
}


class SearchError(ValueError):
    """The search could not be done; the message says why and never contains the key."""


@dataclass(frozen=True)
class Hit:
    title: str
    url: str  # a public https address (checked), ready for the page reader
    snippet: str  # marked as untrusted when it looks like orders to an AI


@dataclass(frozen=True)
class SearchResult:
    query: str  # as sent, after cleaning
    hits: tuple[Hit, ...]
    credits: float | None  # what Tavily says it cost; None when it did not say
    dropped: int  # results left out because their address cannot be read


class TavilySearch:
    def __init__(
        self,
        keystore: KeyStore | None,
        *,
        client: httpx.AsyncClient | None = None,
        env_key: SecretStr | None = None,
    ):
        self._keystore = keystore
        self._client = client
        self._env_key = env_key

    async def search(self, query: str, max_results: int = 5) -> SearchResult:
        cleaned = redact(" ".join(query.split()))
        if not cleaned:
            raise SearchError("the search is empty")
        if len(cleaned) > MAX_QUERY_CHARS:
            raise SearchError(f"the search is longer than {MAX_QUERY_CHARS} characters")
        count = max(1, min(int(max_results), MAX_RESULTS))
        key = await self._key()
        body = {
            "query": cleaned,
            "search_depth": "basic",
            "max_results": count,
            "include_answer": False,
            "include_raw_content": False,
            "include_images": False,
            "include_usage": True,
        }
        data = await self._post(key, body)
        results = data.get("results")
        if not isinstance(results, list):
            raise SearchError("could not understand the search service's answer")
        hits: list[Hit] = []
        for item in results[:count]:
            hit = _hit(item)
            if hit is not None:
                hits.append(hit)
        usage = data.get("usage")
        credits = usage.get("credits") if isinstance(usage, dict) else None
        if isinstance(credits, bool) or not isinstance(credits, int | float):
            credits = None
        return SearchResult(cleaned, tuple(hits), credits, min(len(results), count) - len(hits))

    async def _key(self) -> str:
        key, _ = await search_key(self._keystore, self._env_key)
        if key is None:
            raise SearchError("no search key is set")
        return key

    async def _post(self, key: str, body: dict) -> dict:  # type: ignore[type-arg]
        client = self._client or httpx.AsyncClient(
            timeout=TIMEOUT_SECONDS, follow_redirects=False, trust_env=False
        )
        try:
            response = await client.post(
                ENDPOINT,
                json=body,
                headers={"Authorization": f"Bearer {key}", "User-Agent": USER_AGENT},
            )
        except httpx.HTTPError as exc:
            raise SearchError(f"could not reach the search service: {type(exc).__name__}") from None
        finally:
            if self._client is None:
                await client.aclose()
        if response.status_code != 200:
            raise SearchError(
                _PROBLEMS.get(
                    response.status_code, f"the search service answered {response.status_code}"
                )
            )
        try:
            data = response.json()
        except ValueError:
            raise SearchError("could not understand the search service's answer") from None
        if not isinstance(data, dict):
            raise SearchError("could not understand the search service's answer")
        return data


async def search_key(
    keystore: KeyStore | None, env_key: SecretStr | None
) -> tuple[str | None, str | None]:
    """(key, where it came from): the OS key store first, then the settings (`.env`)."""
    if keystore is not None:
        try:
            stored = await run_in_threadpool(keystore.get, SEARCH_KEY_REF)
        except KeyStoreError as exc:
            raise SearchError(str(exc)) from None
        if stored:
            return stored, "keychain"
    if env_key is not None and env_key.get_secret_value().strip():
        return env_key.get_secret_value().strip(), "env"
    return None, None


def _hit(item: object) -> Hit | None:
    if not isinstance(item, dict) or not isinstance(item.get("url"), str):
        return None
    try:
        url = str(check_url(item["url"]))
    except WebError:
        return None
    return Hit(
        title=screen(str(item.get("title") or "")).text[:200],
        url=url,
        snippet=mark(str(item.get("content") or "")[:SNIPPET_CHARS], "search result"),
    )
