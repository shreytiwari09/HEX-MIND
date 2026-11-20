"""Reading a web page for the Researcher (PRD D62, "Advanced research").

The fetcher runs in the backend, never in agent or plugin code, and can only do one thing: read
a public web page. The rules, each tested:

  * the address is `https://name/...` on the standard port, with no credentials, and a site
    **name**, never an IP address, `localhost` or an internal name;
  * the name is looked up here and **every** answer must be a public address (not this machine,
    the local network, a link-local address such as a cloud metadata service, or shared space);
  * the request then goes to the address that was checked, with the name sent as the Host header
    and as the certificate name, so the answer cannot change between the check and the request;
  * a redirect is followed (up to MAX_REDIRECTS) but the new address goes through all of the
    above again, so a public page cannot send the fetcher inside;
  * only text kinds of page are read, at most MAX_BYTES of them, and the readable text is cut to
    MAX_CHARS, with `truncated` saying so;
  * no cookies, no credentials, no environment proxy settings, a generic user agent;
  * what comes back is screened for prompt injection and **marked as data** (D50), never trusted.

The reader never returns raw HTML, only its visible text, so scripts and styles are not shown.
"""

import asyncio
import ipaddress
import re
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import httpx

from app.guardrails.injection import mark, screen

MAX_URL_CHARS = 2000
MAX_BYTES = 1_000_000  # of the page, after decompression
MAX_CHARS = 30_000  # of the readable text
MAX_REDIRECTS = 3
TIMEOUT_SECONDS = 15
USER_AGENT = "hexmind"

_READABLE = {
    "text/html",
    "application/xhtml+xml",
    "text/plain",
    "text/markdown",
    "application/json",
    "application/xml",
    "text/xml",
}
_HTML = {"text/html", "application/xhtml+xml", "application/xml", "text/xml"}
_REDIRECTS = {301, 302, 303, 307, 308}
_INTERNAL_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".intranet", ".home.arpa")


class WebError(ValueError):
    """The page cannot be read; the message says why in plain words."""


@dataclass(frozen=True)
class Page:
    url: str  # the address the text came from, after any redirects
    title: str
    text: str  # readable text, screened and marked when it looks like orders to an AI
    truncated: bool  # the page or its text was cut at a limit
    signals: tuple[str, ...]  # why it was marked (empty when it was not)


Resolver = Callable[[str], Awaitable[list[str]]]


async def system_resolver(host: str) -> list[str]:
    """Every address the system's DNS gives for `host`."""
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except OSError:
        raise WebError("could not find that site") from None
    return list(dict.fromkeys(str(info[4][0]) for info in infos))


def check_url(url: str) -> httpx.URL:
    """The address if it is a public https page address; WebError otherwise. Checks the text of
    the address only; `WebFetcher` also checks where the name leads."""
    text = url.strip()
    if not text or len(text) > MAX_URL_CHARS:
        raise WebError("the address is empty or too long")
    if any(ord(c) <= 32 or ord(c) == 127 for c in text):
        raise WebError("the address has spaces or control characters")
    try:
        parsed = urlparse(text)
        port = parsed.port
    except ValueError:
        raise WebError("the address is not valid") from None
    if parsed.scheme != "https":
        raise WebError("only https:// addresses can be read")
    if parsed.username is not None or parsed.password is not None:
        raise WebError("an address with a user name or password cannot be read")
    if port not in (None, 443):
        raise WebError("only the standard https port can be used")
    host = (parsed.hostname or "").lower().rstrip(".")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise WebError("use the site's name, not an IP address")
    if "." not in host or host == "localhost" or host.endswith(_INTERNAL_SUFFIXES):
        raise WebError("that is not a public website name")
    try:
        return httpx.URL(parsed._replace(fragment="").geturl())
    except httpx.InvalidURL:
        raise WebError("the address is not valid") from None


def _public(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped  # a private v4 address written as v6 is still private
    return ip.is_global and not ip.is_multicast


class _Text(HTMLParser):
    """The visible text of a page and its title; no scripts, styles, navigation or comments."""

    _SKIP = {"script", "style", "noscript", "template", "svg", "head", "nav", "footer", "aside"}
    _BREAK = {
        "p", "div", "br", "li", "ul", "ol", "tr", "table", "section", "article", "main",
        "h1", "h2", "h3", "h4", "h5", "h6", "pre", "blockquote", "header", "form",
    }  # fmt: skip

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title = ""
        self._skipping = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "title":
            self._in_title = True
        elif tag in self._SKIP:
            self._skipping += 1
        elif tag in self._BREAK:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        elif tag in self._SKIP:
            self._skipping = max(0, self._skipping - 1)
        elif tag in self._BREAK:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        elif not self._skipping:
            self.parts.append(data)


def _tidy(text: str) -> str:
    lines = (re.sub(r"[ \t\r\f\v\xa0]+", " ", line).strip() for line in text.split("\n"))
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _readable(body: str, content_type: str) -> tuple[str, str]:
    """(title, text) of a page body."""
    if content_type not in _HTML:
        return "", _tidy(body)
    parser = _Text()
    parser.feed(body)
    parser.close()
    return " ".join(parser.title.split()), _tidy("".join(parser.parts))


def _decode(data: bytes, content_type_header: str) -> str:
    match = re.search(r"charset=([\w.-]+)", content_type_header, re.IGNORECASE)
    try:
        return data.decode(match.group(1) if match else "utf-8", errors="replace")
    except LookupError:
        return data.decode("utf-8", errors="replace")


_PROBLEMS = {
    401: "the site did not allow reading that page",
    403: "the site did not allow reading that page",
    404: "page not found",
    410: "page not found (it was removed)",
    429: "the site said too many requests; try again later",
}


@dataclass
class _Raw:
    status: int
    headers: httpx.Headers
    body: bytes
    truncated: bool


class WebFetcher:
    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        resolver: Resolver = system_resolver,
        max_bytes: int = MAX_BYTES,
        max_chars: int = MAX_CHARS,
    ) -> None:
        self._client = httpx.AsyncClient(
            transport=transport,
            timeout=TIMEOUT_SECONDS,
            follow_redirects=False,  # every hop is checked again, here
            trust_env=False,  # no proxy settings or credentials from the environment
        )
        self._resolver = resolver
        self._max_bytes = max_bytes
        self._max_chars = max_chars

    async def aclose(self) -> None:
        await self._client.aclose()

    async def fetch(self, url: str) -> Page:
        current = check_url(url)
        for _hop in range(MAX_REDIRECTS + 1):
            raw = await self._read(current)
            if raw.status in _REDIRECTS:
                location = raw.headers.get("location")
                if not location:
                    raise WebError("the site sent a redirect without saying where")
                current = check_url(urljoin(str(current), location))
                continue
            return self._page(current, raw)
        raise WebError("too many redirects")

    async def _read(self, url: httpx.URL) -> _Raw:
        host = url.host
        addresses = await self._resolver(host)
        if not addresses or not all(_public(a) for a in addresses):
            raise WebError("that site is not on the public internet")
        # IPv4 first: a dual-stack site that cannot be reached over IPv6 still works.
        ordered = sorted(addresses, key=lambda a: ":" in a)
        last: httpx.HTTPError | None = None
        for address in ordered:
            try:
                return await self._request(url, host, address)
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                last = exc  # try the next address
            except httpx.HTTPError as exc:
                raise WebError(f"could not read the page: {type(exc).__name__}") from None
        raise WebError(f"could not reach the site: {type(last).__name__}")

    async def _request(self, url: httpx.URL, host: str, address: str) -> _Raw:
        headers = {
            "Host": host,
            "User-Agent": USER_AGENT,
            "Accept": "text/html,text/plain;q=0.9,*/*;q=0.1",
        }
        async with self._client.stream(
            "GET",
            url.copy_with(host=address),
            headers=headers,
            extensions={"sni_hostname": host},  # the certificate must be the site's, not the IP's
        ) as response:
            body = bytearray()
            truncated = False
            if response.status_code not in _REDIRECTS and response.status_code == 200:
                async for chunk in response.aiter_bytes():
                    body += chunk
                    if len(body) > self._max_bytes:
                        del body[self._max_bytes :]
                        truncated = True
                        break
            return _Raw(response.status_code, response.headers, bytes(body), truncated)

    def _page(self, url: httpx.URL, raw: _Raw) -> Page:
        if raw.status != 200:
            raise WebError(_PROBLEMS.get(raw.status, f"the site answered {raw.status}"))
        header = raw.headers.get("content-type", "")
        kind = header.split(";", 1)[0].strip().lower()
        if kind not in _READABLE:
            raise WebError(f"that is not a readable page ({kind or 'no type given'})")
        title, text = _readable(_decode(raw.body, header), kind)
        truncated = raw.truncated
        if len(text) > self._max_chars:
            text, truncated = text[: self._max_chars], True
        found = screen(text)
        return Page(
            url=str(url),
            title=screen(title).text[:200],
            text=mark(text, "web page"),
            truncated=truncated,
            signals=found.signals if found.suspicious else (),
        )
