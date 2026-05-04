"""Shared ouo.io URL resolver used by all source crawlers.

Contains:
- OuoResolverConfig: dataclass bundling all ouo-related options.
- OuoBypass: legacy /go + /xreallcygo bypass with optional browser fallback.
- OuoResolver: full resolver with FlareSolverr request.get + form parse,
  retry with exponential backoff, DB-backed success/failure cache + cooldown,
  and OuoBypass legacy fallback.

Extracted from nxbrew.crawler.ContentExtractor (which had 2951 successful
resolutions in production by 2026-04-29) so ziperto and other sources can
reuse the same battle-tested flow.
"""

from __future__ import annotations

import logging
import random
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Protocol, Tuple
from urllib.parse import urljoin, urlparse, urlencode

import requests
from bs4 import BeautifulSoup


__all__ = [
    "OuoResolverConfig",
    "OuoBypass",
    "OuoResolver",
    "OuoCacheStore",
    "OuoBackend",
    "BACKEND_REGISTRY",
]


# ---- Backend registry --------------------------------------------------
# Each backend is a name → (resolver_method_name) mapping. To add a new
# backend (e.g. cloudflare_worker, bypass_vip, ...): write a method on
# OuoResolver returning Optional[str] and add a row here. Configure which
# backends run, and in what order, via OuoResolverConfig.backend_order.
#
# Backend method signature: (self, ouo_url: str, *, fs_session_id: str = "",
#                            referer: str = "") -> Optional[str]
BACKEND_REGISTRY: Dict[str, str] = {
    "curl_impersonate": "_resolve_via_curl_impersonate",
    "flaresolverr_form": "_resolve_via_flaresolverr_form",
    "undetected_chromedriver": "_resolve_via_browser",
    "ouo_bypass_legacy": "_resolve_via_legacy_bypass",
}


@dataclass
class OuoBackend:
    """A pluggable resolver backend selected by name from BACKEND_REGISTRY."""
    name: str
    method_name: str


# Browser impersonation profiles tried in order by the curl_cffi backend.
# safari15_5 currently (2026-05) bypasses ouo's Cloudflare from datacenter IPs
# that block chrome110/chrome107 — keep the order so we waste no time on the
# blocked profiles in cache-warm scenarios.
_IMPERSONATION_PROFILES = ("safari15_5", "chrome110", "chrome107")


def _curl_browser_headers(hostname: str, referer: str) -> Dict[str, str]:
    return {
        'authority': hostname,
        'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
        'accept-language': 'en-US,en;q=0.9',
        'cache-control': 'max-age=0',
        'pragma': 'no-cache',
        'referer': referer,
        'sec-ch-ua': '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"macOS"',
        'sec-fetch-dest': 'document',
        'sec-fetch-mode': 'navigate',
        'sec-fetch-site': 'same-origin',
        'sec-fetch-user': '?1',
        'upgrade-insecure-requests': '1',
        'user-agent': (
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/122.0.0.0 Safari/537.36'
        ),
    }


def _is_cloudflare_challenge(response) -> bool:
    body_lower = (getattr(response, 'text', '') or '').lower()
    return (
        getattr(response, 'status_code', 0) in {403, 429, 503}
        and (
            "just a moment" in body_lower
            or "cf-chl" in body_lower
            or "/cdn-cgi/challenge-platform" in body_lower
        )
    )


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class OuoResolverConfig:
    flaresolverr_url: str = "http://localhost:8191"

    # Allowed hosts for the *final* URL (the one we persist).
    allowed_download_hosts: Tuple[str, ...] = ("1fichier.com",)
    # Intermediate redirect hosts (e.g. frdl.my, freedl.ink) accepted as final
    # when accept_intermediate_hosts is True.
    allowed_intermediate_hosts: Tuple[str, ...] = ("frdl.my", "freedl.ink")
    accept_intermediate_hosts: bool = True

    # Retry / pacing
    max_retries: int = 5
    retry_base_delay: float = 5.0
    retry_max_delay: float = 30.0
    resolve_delay: float = 2.0
    resolve_jitter: float = 1.5

    # Legacy OuoBypass fallback
    legacy_first: bool = True
    fallback_timeout: int = 45

    # DB cache
    cache_enabled: bool = True
    success_ttl_hours: int = 168
    failure_cooldown_base: int = 600
    failure_cooldown_max: int = 86400

    # Behavior
    preserve_unresolved_ouo_links: bool = True

    # FlareSolverr per-request budget. ouo.io now (2026-05) puts a real
    # Cloudflare challenge in front of every cold request — 60s is needed for
    # the first cold hit. Within a reused session subsequent requests return
    # in ~1-3s because the CF clearance cookie is reused.
    fs_max_timeout_ms: int = 60000
    fs_request_timeout_s: int = 80

    # When the caller doesn't provide an fs_session_id, resolve() will
    # transparently create one and reuse it across all sub-requests for this
    # ouo URL — vital for performance because each cold session pays the full
    # CF challenge cost.
    auto_session: bool = True

    # Resolver backends to try in this order. Names must exist in
    # BACKEND_REGISTRY. Drop a name to disable a backend; reorder to change
    # priority. The first backend returning a valid final URL wins.
    backend_order: Tuple[str, ...] = (
        "curl_impersonate",
        "flaresolverr_form",
        "undetected_chromedriver",
        "ouo_bypass_legacy",
    )

    @classmethod
    def from_crawling_dict(
        cls,
        crawling_config: Dict[str, Any],
        flaresolverr_url: str,
    ) -> "OuoResolverConfig":
        """Build from the dict-style ``crawling`` block in config.json.

        Mirrors the ContentExtractor.__init__ defaults so callers can swap in
        the resolver without changing their config schema.
        """
        cfg = crawling_config or {}
        allowed_hosts_raw = cfg.get("allowed_download_hosts", ["1fichier.com", "freedl", "datanodes"])
        if not isinstance(allowed_hosts_raw, list):
            allowed_hosts_raw = ["1fichier.com"]
        allowed_hosts = tuple(
            str(h).strip().lower() for h in allowed_hosts_raw if str(h).strip()
        ) or ("1fichier.com",)

        intermediate_raw = cfg.get("allowed_intermediate_hosts", ["frdl.my", "freedl.ink"])
        if not isinstance(intermediate_raw, list):
            intermediate_raw = ["frdl.my", "freedl.ink"]
        intermediate_hosts = tuple(
            str(h).strip().lower() for h in intermediate_raw if str(h).strip()
        ) or ("frdl.my", "freedl.ink")

        failure_base = max(30, int(cfg.get("ouo_failure_cooldown_base", 600)))
        failure_max = max(failure_base, int(cfg.get("ouo_failure_cooldown_max", 86400)))

        return cls(
            flaresolverr_url=flaresolverr_url,
            allowed_download_hosts=allowed_hosts,
            allowed_intermediate_hosts=intermediate_hosts,
            accept_intermediate_hosts=bool(cfg.get("accept_intermediate_hosts", True)),
            max_retries=max(1, int(cfg.get("max_retries", 5))),
            retry_base_delay=float(cfg.get("retry_base_delay", 5.0)),
            retry_max_delay=max(
                float(cfg.get("retry_base_delay", 5.0)),
                float(cfg.get("ouo_retry_max_delay", 30.0)),
            ),
            resolve_delay=max(0.0, float(cfg.get("ouo_resolve_delay", 2.0))),
            resolve_jitter=max(0.0, float(cfg.get("ouo_resolve_jitter", 1.5))),
            legacy_first=bool(cfg.get("ouo_legacy_first", True)),
            fallback_timeout=max(10, int(cfg.get("ouo_fallback_timeout", 45))),
            cache_enabled=bool(cfg.get("ouo_cache_enabled", True)),
            success_ttl_hours=max(1, int(cfg.get("ouo_success_ttl_hours", 168))),
            failure_cooldown_base=failure_base,
            failure_cooldown_max=failure_max,
            preserve_unresolved_ouo_links=bool(cfg.get("preserve_unresolved_ouo_links", True)),
            fs_max_timeout_ms=max(2000, int(cfg.get("ouo_fs_max_timeout_ms", 60000))),
            fs_request_timeout_s=max(5, int(cfg.get("ouo_fs_request_timeout_s", 80))),
            auto_session=bool(cfg.get("ouo_auto_session", True)),
            backend_order=cls._normalize_backend_order(cfg.get("ouo_backend_order")),
        )

    @staticmethod
    def _normalize_backend_order(raw: Any) -> Tuple[str, ...]:
        if raw is None:
            return (
                "curl_impersonate",
                "flaresolverr_form",
                "undetected_chromedriver",
                "ouo_bypass_legacy",
            )
        if isinstance(raw, (list, tuple)):
            cleaned = tuple(str(name).strip() for name in raw if str(name).strip())
            return cleaned or ("curl_impersonate",)
        return ("curl_impersonate",)


# ---------------------------------------------------------------------------
# Cache store protocol
# ---------------------------------------------------------------------------

class OuoCacheStore(Protocol):
    def get_ouo_resolution_cache(self, ouo_url: str) -> Optional[Dict[str, Any]]: ...
    def upsert_ouo_resolution_success(self, ouo_url: str, final_url: str) -> bool: ...
    def upsert_ouo_resolution_failure(
        self, ouo_url: str, error_code: str, next_retry_at: datetime
    ) -> bool: ...


# ---------------------------------------------------------------------------
# Legacy OuoBypass (kept as a fallback option inside OuoResolver)
# ---------------------------------------------------------------------------

class OuoBypass:
    """ouo.io / ouo.press bypass via FlareSolverr POST.

    Flow: ``/go/{id}`` POST init=1 → extract _token → ``/xreallcygo/{id}``
    POST. With long FlareSolverr timeouts this is brittle (FlareSolverr will
    burn the budget hunting for a CF challenge that doesn't exist), so
    OuoResolver uses request.get with a short timeout as the primary path
    and only falls back here. Browser fallback uses undetected-chromedriver
    when reCAPTCHA blocks the POST flow.
    """

    DEFAULT_FLARE_URL = "http://localhost:8191/v1"
    _flare_url = DEFAULT_FLARE_URL  # class-level override for tests / DI

    @classmethod
    def configure(cls, flaresolverr_base_url: str) -> None:
        """Point at a non-default FlareSolverr instance (e.g. ``http://flaresolverr:8191``)."""
        base = flaresolverr_base_url.rstrip("/")
        cls._flare_url = f"{base}/v1" if not base.endswith("/v1") else base

    @classmethod
    def _fs_post(
        cls,
        url: str,
        post_data: str,
        max_timeout: int = 60000,
        session_id: str = "",
        headers: Optional[Dict[str, str]] = None,
    ) -> Optional[dict]:
        try:
            payload: Dict[str, Any] = {
                "cmd": "request.post",
                "url": url,
                "postData": post_data,
                "maxTimeout": max_timeout,
            }
            if session_id:
                payload["session"] = session_id
            if headers:
                payload["headers"] = headers
            resp = requests.post(
                cls._flare_url,
                json=payload,
                timeout=max_timeout / 1000 + 10,
            )
            return resp.json()
        except Exception as exc:
            logging.getLogger(__name__).warning(f"OuoBypass FlareSolverr POST failed: {exc}")
            return None

    @classmethod
    def _destroy_session(cls, session_id: str) -> None:
        if not session_id:
            return
        try:
            requests.post(
                cls._flare_url,
                json={"cmd": "sessions.destroy", "session": session_id},
                timeout=20,
            )
        except Exception:
            pass

    @classmethod
    def _bypass_with_browser(cls, ouo_url: str, timeout: int = 45) -> Optional[str]:
        driver = None
        try:
            import undetected_chromedriver as uc
            from selenium.webdriver.common.by import By
            from selenium.webdriver.common.action_chains import ActionChains

            options = uc.ChromeOptions()
            options.add_argument("--headless=new")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--disable-blink-features=AutomationControlled")
            options.add_argument("--window-size=1366,768")
            options.add_argument(
                "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            )
            driver = uc.Chrome(options=options, version_main=None)
            driver.set_page_load_timeout(timeout)
            driver.get(ouo_url)

            end_time = time.time() + timeout
            last_url = ""
            while time.time() < end_time:
                current_url = (driver.current_url or "").strip()
                if current_url and current_url != last_url:
                    last_url = current_url
                    parsed = urlparse(current_url)
                    if parsed.netloc and "ouo.io" not in parsed.netloc and "ouo.press" not in parsed.netloc:
                        if current_url.startswith("http"):
                            return current_url

                try:
                    forms = driver.find_elements(
                        By.CSS_SELECTOR,
                        "form#form, form[action*='xreallcygo'], form[action*='/go/']",
                    )
                    for form in forms:
                        driver.execute_script("arguments[0].submit();", form)
                        time.sleep(1.5)
                except Exception:
                    pass

                selectors = [
                    "#btn-main",
                    "button[type='submit']",
                    "input[type='submit']",
                    "a[href*='/go/']",
                    "a[href*='xreallcygo']",
                ]
                for selector in selectors:
                    try:
                        elements = driver.find_elements(By.CSS_SELECTOR, selector)
                        for element in elements[:2]:
                            if not element.is_displayed():
                                continue
                            driver.execute_script(
                                "arguments[0].scrollIntoView({block:'center'});", element
                            )
                            ActionChains(driver).move_to_element(element).pause(0.2).click(element).perform()
                            time.sleep(1.5)
                    except Exception:
                        continue

                time.sleep(1.0)

            return None
        except Exception:
            return None
        finally:
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass

    @classmethod
    def bypass(
        cls,
        ouo_url: str,
        timeout: int = 30,
        enable_browser_fallback: bool = False,
    ) -> Optional[str]:
        """Resolve a single ouo.io / ouo.press shortlink to its real destination."""
        if "ouo.press" in ouo_url:
            ouo_url = ouo_url.replace("ouo.press", "ouo.io")

        match = re.search(r"ouo\.io/([a-zA-Z0-9]+)", ouo_url)
        if not match:
            return None
        ouo_id = match.group(1)
        session_id = f"ouo-bp-{int(time.time())}-{ouo_id[:6]}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://ouo.io/",
        }

        try:
            go_url = f"https://ouo.io/go/{ouo_id}"
            result = cls._fs_post(
                go_url,
                "init=1",
                max_timeout=max(timeout * 1000, 60000),
                session_id=session_id,
                headers=headers,
            )
            if not result or "solution" not in result:
                return None
            html = result["solution"]["response"]

            token_match = re.search(r'name="_token"[^>]*value="([^"]+)"', html)
            if not token_match:
                return None
            token = token_match.group(1)

            xreal_url = f"https://ouo.io/xreallcygo/{ouo_id}"
            result2 = cls._fs_post(
                xreal_url,
                f"_token={token}&x-token=",
                max_timeout=max(timeout * 1000, 60000),
                session_id=session_id,
                headers=headers,
            )
            if not result2 or "solution" not in result2:
                return None

            final_url = result2["solution"].get("url", "")
            for host in ("1fichier", "mega.nz", "mediafire", "pixeldrain", "gofile", "katfile", "datanodes", "frdl.my", "freedl"):
                if host in final_url.lower():
                    return final_url
            html2 = result2["solution"]["response"]
            for host in ("1fichier", "mega.nz", "mediafire", "pixeldrain", "gofile", "katfile", "datanodes", "frdl.my", "freedl"):
                m = re.search(rf'https?://[^\s"\'>]*{re.escape(host)}[^\s"\'>]*', html2, re.I)
                if m:
                    return m.group(0)

            if final_url and final_url != xreal_url:
                return final_url

            if enable_browser_fallback:
                return cls._bypass_with_browser(ouo_url, timeout=max(timeout, 45))
            return None
        finally:
            cls._destroy_session(session_id)


# ---------------------------------------------------------------------------
# OuoResolver
# ---------------------------------------------------------------------------

_OUO_HOST_PATTERN = re.compile(r"ouo\.(?:io|press)/([a-zA-Z0-9]+)", re.I)


class OuoResolver:
    """Resolve ouo.io shortlinks to final download URLs.

    Strategy (tried in order, with DB cache short-circuiting at the start):
      1. DB success cache hit (within TTL) → return cached final URL.
      2. DB failure cooldown active → return None.
      3. Legacy OuoBypass.bypass() (browser fallback off).
      4. Browser-preflight OuoBypass.bypass() (only for primary+base links).
      5. FlareSolverr request.get loop (max_retries with exponential backoff).
      6. OuoBypass.bypass() final fallback (browser fallback if challenge seen).
      7. Detached-session retry of step 5 (if a session was being reused).
      8. Persist failure with cooldown.
    """

    def __init__(
        self,
        config: OuoResolverConfig,
        *,
        db_manager: Optional[OuoCacheStore] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.config = config
        self.db_manager = db_manager
        self.logger = logger or logging.getLogger(__name__)
        # Make sure the OuoBypass fallback talks to the same FlareSolverr.
        OuoBypass.configure(config.flaresolverr_url)

    # === public URL helpers ===

    @classmethod
    def normalize_url(cls, url: str) -> str:
        normalized = (url or "").strip()
        if "ouo.press" in normalized:
            normalized = normalized.replace("ouo.press", "ouo.io")
        return normalized

    @classmethod
    def is_ouo_url(cls, url: Optional[str]) -> bool:
        if not url:
            return False
        host = (urlparse(url).netloc or "").lower()
        return "ouo.io" in host or "ouo.press" in host

    def is_valid_final_url(self, url: Optional[str]) -> bool:
        if not url:
            return False
        parsed = urlparse(url)
        host = (parsed.netloc or "").lower()
        path = (parsed.path or "").lower()
        if not host:
            return False
        if "ouo.io" in host or "ouo.press" in host:
            return False

        # freedl/frdl: reject the bare landing/upload/go pages even when listed
        # as an allowed host — we want a real file URL.
        if (
            any("freedl" in h or "frdl" in h for h in self.config.allowed_download_hosts)
            and ("freedl" in host or "frdl.my" in host)
        ):
            if path in ("", "/", "/upload", "/upload/", "/go", "/go/"):
                return False

        if self.config.accept_intermediate_hosts and any(
            inter in host for inter in self.config.allowed_intermediate_hosts
        ):
            return path not in ("", "/", "/go", "/go/", "/upload", "/upload/")

        return any(allowed in host for allowed in self.config.allowed_download_hosts)

    def is_persistable_download_url(self, url: Optional[str]) -> bool:
        if self.is_valid_final_url(url):
            return True
        return self.config.preserve_unresolved_ouo_links and self.is_ouo_url(url)

    def extract_allowed_url_from_text(self, text: str) -> Optional[str]:
        if not text:
            return None
        for allowed in self.config.allowed_download_hosts:
            pattern = rf'https?://[^\s"\']*{re.escape(allowed)}[^\s"\']*'
            match = re.search(pattern, text, re.I)
            if match:
                candidate = match.group(0)
                if self.is_valid_final_url(candidate):
                    return candidate
        return None

    def get_wait_seconds(self) -> float:
        if self.config.resolve_delay <= 0:
            return 0.0
        jitter = random.uniform(0.0, self.config.resolve_jitter) if self.config.resolve_jitter > 0 else 0.0
        return self.config.resolve_delay + jitter

    # === public entry ===

    def resolve(
        self,
        ouo_url: str,
        *,
        filename: str = "",
        title_id: str = "",
        post_url: str = "",
        phase: str = "primary",
        link_tier: str = "unknown",
        fs_session_id: str = "",
        ignore_cooldown: bool = False,
    ) -> Optional[str]:
        normalized = self.normalize_url(ouo_url)
        if not normalized:
            return None

        # Auto-session: if caller didn't pass one, create a per-resolve session
        # so all sub-requests share the CF clearance cookie (60s cold start is
        # paid once instead of N times).
        owns_session = False
        if not fs_session_id and self.config.auto_session:
            fs_session_id = f"ouo-auto-{uuid.uuid4().hex[:12]}"
            try:
                requests.post(
                    f"{self.config.flaresolverr_url}/v1",
                    json={"cmd": "sessions.create", "session": fs_session_id},
                    timeout=30,
                )
                owns_session = True
            except Exception as exc:
                self.logger.warning(f"Failed to create FlareSolverr session: {exc}")
                fs_session_id = ""

        try:
            return self._resolve_inner(
                normalized,
                filename=filename,
                title_id=title_id,
                post_url=post_url,
                phase=phase,
                link_tier=link_tier,
                fs_session_id=fs_session_id,
                ignore_cooldown=ignore_cooldown,
            )
        finally:
            if owns_session and fs_session_id:
                self._destroy_session(fs_session_id)

    def _resolve_inner(
        self,
        normalized: str,
        *,
        filename: str,
        title_id: str,
        post_url: str,
        phase: str,
        link_tier: str,
        fs_session_id: str,
        ignore_cooldown: bool,
    ) -> Optional[str]:

        context_parts = [
            f"phase={phase}",
            f"tier={link_tier}",
            f"title_id={(title_id or '-').upper()}",
            f"filename={filename or 'Unknown'}",
        ]
        if post_url:
            context_parts.append(f"post_url={post_url}")
        context = " | ".join(context_parts)

        cache_state = self._get_cache_state(normalized)
        now = datetime.utcnow()
        if cache_state:
            last_status = str(cache_state.get("last_status") or "").lower()
            cached_final_url = str(cache_state.get("final_url") or "").strip()
            next_retry_at = self._parse_cache_dt(cache_state.get("next_retry_at"))
            last_success_at = self._parse_cache_dt(cache_state.get("last_success_at"))

            if (
                (not ignore_cooldown)
                and last_status == "failure"
                and next_retry_at
                and now < next_retry_at
            ):
                wait = int((next_retry_at - now).total_seconds())
                self.logger.info(
                    f"Skipping OUO due to cooldown ({context}) for {normalized}: retry_in={wait}s"
                )
                return None

            if (
                last_status == "success"
                and cached_final_url
                and self.is_valid_final_url(cached_final_url)
            ):
                if last_success_at and (now - last_success_at) <= timedelta(
                    hours=self.config.success_ttl_hours
                ):
                    self.logger.info(
                        f"Using OUO success cache ({context}): {cached_final_url}"
                    )
                    return cached_final_url

        # Try each configured backend in order. First valid final URL wins.
        # See BACKEND_REGISTRY for the available names. To swap algorithms,
        # change OuoResolverConfig.backend_order — no code edit needed.
        last_failure = "no_backends_configured"
        for backend_name in self.config.backend_order:
            method_name = BACKEND_REGISTRY.get(backend_name)
            if not method_name:
                self.logger.warning(f"Unknown ouo backend '{backend_name}' (skipping)")
                continue
            method = getattr(self, method_name, None)
            if not callable(method):
                self.logger.warning(f"Backend '{backend_name}' method missing (skipping)")
                continue

            try:
                final_url = method(
                    normalized,
                    fs_session_id=fs_session_id,
                    referer=post_url,
                )
            except Exception as exc:
                self.logger.warning(
                    f"Backend {backend_name} threw ({context}) for {normalized}: {exc}"
                )
                last_failure = f"{backend_name}_exception"
                continue

            if final_url and self.is_valid_final_url(final_url):
                self.logger.info(
                    f"Resolved via {backend_name} ({context}): {final_url}"
                )
                self._persist_success(normalized, final_url)
                return final_url

            last_failure = f"{backend_name}_no_url"

        self.logger.warning(
            f"All backends exhausted ({context}) for {normalized}: last={last_failure}"
        )
        self._persist_failure(normalized, last_failure, cache_state, context)
        return None

    # === internals ===

    def _resolve_once_with_context(
        self,
        ouo_url: str,
        *,
        fs_session_id: str = "",
        referer: str = "",
        diagnostics: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """Form-chain bypass: POST /go/{id} → extract _token (+ optional reCAPTCHA
        v3 token if a sitekey is present) → POST /xreallcygo/{id} → extract final
        URL from the response.

        Empirically (2026-05) ouo.io's anti-bot challenge for ``request.get``
        cannot be solved by FlareSolverr within 60s, but the same challenge for
        ``request.post`` to ``/go/{id}`` solves in ~10s. So we skip the GET
        entirely and start with the POST chain.
        """
        match = _OUO_HOST_PATTERN.search(ouo_url)
        if not match:
            return None
        ouo_id = match.group(1)

        # Step 1: POST /go/{id} with init=1 to bootstrap _token.
        go_url = f"https://ouo.io/go/{ouo_id}"
        go_payload: Dict[str, Any] = {
            "cmd": "request.post",
            "url": go_url,
            "postData": "init=1",
            "maxTimeout": self.config.fs_max_timeout_ms,
        }
        if fs_session_id:
            go_payload["session"] = fs_session_id
        go_resp = requests.post(
            f"{self.config.flaresolverr_url}/v1",
            json=go_payload,
            timeout=self.config.fs_request_timeout_s,
        )
        go_resp.raise_for_status()
        go_result = go_resp.json()
        if go_result.get("status") != "ok":
            if diagnostics is not None:
                diagnostics["reason"] = "go_post_failed"
            return None

        go_html = go_result.get("solution", {}).get("response", "") or ""
        if diagnostics is not None:
            diagnostics["reason"] = self._detect_failure_reason(go_html)

        token_match = re.search(r'name="_token"[^>]*value="([^"]+)"', go_html)
        if not token_match:
            return None
        token = token_match.group(1)

        # Step 1.5: if ouo embedded a reCAPTCHA v3 sitekey, solve it via Google's
        # API (xcscxr-style — no paid solver). Sitekey embedding is intermittent;
        # most resolves currently work without it.
        sitekey_match = re.search(r"(6L[A-Za-z0-9_-]{38})", go_html)
        x_token = ""
        if sitekey_match:
            x_token = self._solve_recaptcha_v3_token(sitekey_match.group(1), referer or ouo_url) or ""

        # Step 2: POST /xreallcygo/{id} to receive the final destination.
        xreal_url = f"https://ouo.io/xreallcygo/{ouo_id}"
        xreal_payload: Dict[str, Any] = {
            "cmd": "request.post",
            "url": xreal_url,
            "postData": f"_token={token}&x-token={x_token}",
            "maxTimeout": self.config.fs_max_timeout_ms,
        }
        if fs_session_id:
            xreal_payload["session"] = fs_session_id
        xreal_resp = requests.post(
            f"{self.config.flaresolverr_url}/v1",
            json=xreal_payload,
            timeout=self.config.fs_request_timeout_s,
        )
        xreal_resp.raise_for_status()
        xreal_result = xreal_resp.json()
        if xreal_result.get("status") != "ok":
            return None

        solution = xreal_result.get("solution", {})
        # FlareSolverr's solution.url reflects the final URL after browser-side
        # redirects, so this is the most reliable source.
        candidate = solution.get("url")
        if self.is_valid_final_url(candidate):
            return candidate

        # Fall back to scanning the response body — ouo sometimes returns an
        # interstitial with the destination as plain text or in an anchor href.
        html = solution.get("response", "") or ""
        extracted = self.extract_allowed_url_from_text(html)
        if extracted:
            return extracted

        soup = BeautifulSoup(html, "html.parser")
        for anchor in soup.find_all("a", href=True):
            href = anchor["href"]
            if self.is_valid_final_url(href):
                return href

        meta = soup.find("meta", attrs={"http-equiv": re.compile("refresh", re.I)})
        if meta and meta.get("content"):
            refresh_match = re.search(r"url=(\S+)", meta["content"], re.I)
            if refresh_match and self.is_valid_final_url(refresh_match.group(1)):
                return refresh_match.group(1)

        return None

    # === backend wrappers (each one must accept (ouo_url, *, fs_session_id, referer)) ===

    def _resolve_via_flaresolverr_form(
        self, ouo_url: str, *, fs_session_id: str = "", referer: str = ""
    ) -> Optional[str]:
        """FlareSolverr POST /go/{id} → /xreallcygo/{id} form chain backend."""
        return self._resolve_once_with_context(
            ouo_url, fs_session_id=fs_session_id, referer=referer,
        )

    def _resolve_via_browser(
        self, ouo_url: str, *, fs_session_id: str = "", referer: str = ""
    ) -> Optional[str]:
        """undetected-chromedriver browser backend (heaviest, last resort)."""
        return OuoBypass.bypass(
            ouo_url,
            timeout=self.config.fallback_timeout,
            enable_browser_fallback=True,
        )

    def _resolve_via_legacy_bypass(
        self, ouo_url: str, *, fs_session_id: str = "", referer: str = ""
    ) -> Optional[str]:
        """Legacy OuoBypass form-chain (FlareSolverr POST without browser)."""
        return OuoBypass.bypass(
            ouo_url,
            timeout=self.config.fallback_timeout,
            enable_browser_fallback=False,
        )

    def _resolve_via_curl_impersonate(
        self, ouo_url: str, *, fs_session_id: str = "", referer: str = ""
    ) -> Optional[str]:
        """Primary backend: curl_cffi with multi-profile browser impersonation.

        Adapted from B3H1Z/ouo-link-bypass and xcscxr/ouo-bypass. Flow:
          1. Try each impersonation profile (safari first — Chrome is currently
             rate-limited from datacenter IPs by ouo's Cloudflare).
          2. Warm cookies with a GET to the host root before hitting the slug.
          3. Parse the form, harvest *_token inputs, fetch a fresh reCAPTCHA v3
             token from Google's anchor/reload API (the form's hardcoded
             sitekey works site-wide).
          4. POST the form to /go/{id}, then /xreallcygo/{id}. The 302
             Location header is the final destination URL.

        Returns the final destination URL, or None if every profile is blocked
        or the form chain fails.
        """
        try:
            from curl_cffi import requests as curl_requests
        except ImportError:
            self.logger.warning("curl_cffi not installed — skipping curl_impersonate backend")
            return None

        try:
            from bs4 import FeatureNotFound  # noqa: F401  # used in except below
        except ImportError:
            FeatureNotFound = Exception  # type: ignore[misc, assignment]

        ouo_url = ouo_url.replace("ouo.press", "ouo.io")
        parsed = urlparse(ouo_url)
        ouo_id = ouo_url.split('/')[-1]
        home_url = f"{parsed.scheme}://{parsed.hostname}/"

        client = curl_requests.Session()
        res = None
        selected_profile = None

        for profile in _IMPERSONATION_PROFILES:
            client.headers.update(_curl_browser_headers(parsed.hostname, referer=home_url))
            try:
                client.get(home_url, impersonate=profile, timeout=30)
                candidate = client.get(ouo_url, impersonate=profile, timeout=30)
            except Exception as exc:
                self.logger.debug(f"curl profile {profile} threw: {exc}")
                continue

            if _is_cloudflare_challenge(candidate):
                res = candidate
                continue

            selected_profile = profile
            res = candidate
            break

        if selected_profile is None or res is None:
            return None

        # ouo's anchor reCAPTCHA sitekey is hardcoded in their JS and works
        # for both ouo.io and ouo.press. We don't need to scrape it per page.
        ouo_sitekey = "6Lcr1ncUAAAAAH3cghg6cOTPGARa8adOf-y9zv2x"

        next_url = f"{parsed.scheme}://{parsed.hostname}/go/{ouo_id}"
        for _ in range(2):
            if res.headers.get('Location'):
                break

            try:
                soup = BeautifulSoup(res.content, 'lxml')
            except Exception:
                soup = BeautifulSoup(res.content, 'html.parser')

            form = soup.find("form")
            if form is None:
                return None

            inputs = form.find_all("input", {"name": re.compile(r"token$")})
            if not inputs:
                return None

            data = {i.get('name'): i.get('value') for i in inputs}
            x_token = self._solve_recaptcha_v3_token(ouo_sitekey, ouo_url)
            if not x_token:
                return None
            data['x-token'] = x_token

            res = client.post(
                next_url,
                data=data,
                headers={'content-type': 'application/x-www-form-urlencoded'},
                allow_redirects=False,
                impersonate=selected_profile,
                timeout=30,
            )
            next_url = f"{parsed.scheme}://{parsed.hostname}/xreallcygo/{ouo_id}"

        return res.headers.get('Location')

    def _solve_recaptcha_v3_token(self, sitekey: str, page_url: str) -> Optional[str]:
        """Get a reCAPTCHA v3 token via Google's anchor + reload API.

        Adapted verbatim from B3H1Z/ouo-link-bypass — no external solver
        service needed. ouo's anchor params (sitekey, co, version) are
        hardcoded by them too because Google's anchor endpoint validates the
        ``co`` (origin) parameter against the registered domain — using the
        wrong origin gets you a 200 with an empty rresp. Returns None on any
        failure.
        """
        try:
            anchor_url = (
                "https://www.google.com/recaptcha/api2/anchor"
                f"?ar=1&k={sitekey}"
                "&co=aHR0cHM6Ly9vdW8ucHJlc3M6NDQz"  # b64('https://ouo.press:443')
                "&hl=en&v=pCoGBhjs9s8EhFOHJFe8cqis&size=invisible&cb=ahgyd1gkfkhe"
            )
            url_base = "https://www.google.com/recaptcha/"
            client = requests.Session()
            client.headers.update({"content-type": "application/x-www-form-urlencoded"})

            matches = re.findall(r"(api2|enterprise)/anchor\?(.*)", anchor_url)[0]
            url_base += matches[0] + "/"
            params_str = matches[1]

            anchor_resp = client.get(url_base + "anchor", params=params_str, timeout=15)
            token_match = re.search(r'"recaptcha-token" value="(.*?)"', anchor_resp.text)
            if not token_match:
                return None
            recaptcha_token = token_match.group(1)

            params = dict(pair.split("=", 1) for pair in params_str.split("&") if "=" in pair)
            post_data = (
                f"v={params['v']}&reason=q&c={recaptcha_token}"
                f"&k={params['k']}&co={params['co']}"
            )
            reload_resp = client.post(
                url_base + "reload",
                params=f"k={params['k']}",
                data=post_data,
                timeout=15,
            )
            answer_match = re.search(r'"rresp","(.*?)"', reload_resp.text)
            return answer_match.group(1) if answer_match else None
        except Exception as exc:
            self.logger.warning(f"reCAPTCHA v3 solve failed for sitekey {sitekey}: {exc}")
            return None

    def _try_go_xreal_bypass(
        self,
        ouo_url: str,
        *,
        fs_session_id: str = "",
        referer: str = "",
    ) -> Optional[str]:
        match = _OUO_HOST_PATTERN.search(ouo_url)
        if not match:
            return None

        ouo_id = match.group(1)
        session_id = fs_session_id or f"ouo-{uuid.uuid4().hex[:12]}"
        created_session = not bool(fs_session_id)
        go_url = f"https://ouo.io/go/{ouo_id}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        }
        if referer:
            headers["Referer"] = referer

        try:
            go_resp = requests.post(
                f"{self.config.flaresolverr_url}/v1",
                json={
                    "cmd": "request.post",
                    "url": go_url,
                    "postData": "init=1",
                    "maxTimeout": self.config.fs_max_timeout_ms,
                    "session": session_id,
                    "headers": headers,
                },
                timeout=self.config.fs_request_timeout_s,
            )
            go_resp.raise_for_status()
            go_result = go_resp.json()
            if go_result.get("status") != "ok":
                return None

            go_html = go_result.get("solution", {}).get("response", "")
            token_match = re.search(r'name="_token"[^>]*value="([^"]+)"', go_html)
            if not token_match:
                return None
            token = token_match.group(1)

            xreal_url = f"https://ouo.io/xreallcygo/{ouo_id}"
            xreal_resp = requests.post(
                f"{self.config.flaresolverr_url}/v1",
                json={
                    "cmd": "request.post",
                    "url": xreal_url,
                    "postData": f"_token={token}&x-token=",
                    "maxTimeout": self.config.fs_max_timeout_ms,
                    "session": session_id,
                    "headers": headers,
                },
                timeout=self.config.fs_request_timeout_s,
            )
            xreal_resp.raise_for_status()
            xreal_result = xreal_resp.json()
            if xreal_result.get("status") != "ok":
                return None

            solution = xreal_result.get("solution", {})
            candidate = solution.get("url")
            if self.is_valid_final_url(candidate):
                return candidate

            html = solution.get("response", "")
            extracted = self.extract_allowed_url_from_text(html)
            if extracted:
                return extracted

            return None
        finally:
            if created_session:
                self._destroy_session(session_id)

    def _destroy_session(self, session_id: str) -> None:
        if not session_id:
            return
        try:
            requests.post(
                f"{self.config.flaresolverr_url}/v1",
                json={"cmd": "sessions.destroy", "session": session_id},
                timeout=30,
            )
        except Exception:
            pass

    # === cache helpers ===

    def _get_cache_state(self, normalized_ouo_url: str) -> Optional[Dict[str, Any]]:
        if not self.config.cache_enabled or not self.db_manager:
            return None
        try:
            return self.db_manager.get_ouo_resolution_cache(normalized_ouo_url)
        except Exception:
            return None

    def _persist_success(self, normalized_ouo_url: str, final_url: str) -> None:
        if not self.config.cache_enabled or not self.db_manager:
            return
        try:
            self.db_manager.upsert_ouo_resolution_success(normalized_ouo_url, final_url)
        except Exception as exc:
            self.logger.warning(
                f"Failed to persist OUO success cache for {normalized_ouo_url}: {exc}"
            )

    def _persist_failure(
        self,
        normalized_ouo_url: str,
        failure_reason: str,
        prev_cache_state: Optional[Dict[str, Any]],
        context: str,
    ) -> None:
        if not self.config.cache_enabled or not self.db_manager:
            return
        previous_failures = 0
        if (
            prev_cache_state
            and str(prev_cache_state.get("last_status") or "").lower() == "failure"
        ):
            previous_failures = int(prev_cache_state.get("consecutive_failures") or 0)
        cooldown_seconds = min(
            self.config.failure_cooldown_base * (2 ** previous_failures),
            self.config.failure_cooldown_max,
        )
        next_retry_at = datetime.utcnow() + timedelta(seconds=cooldown_seconds)
        try:
            self.db_manager.upsert_ouo_resolution_failure(
                normalized_ouo_url,
                error_code=failure_reason,
                next_retry_at=next_retry_at,
            )
            self.logger.info(
                f"Stored OUO failure cooldown ({context}) for {normalized_ouo_url}: next_retry_at={next_retry_at}"
            )
        except Exception as exc:
            self.logger.warning(
                f"Failed to persist OUO failure cache for {normalized_ouo_url}: {exc}"
            )

    @staticmethod
    def _parse_cache_dt(raw_value: Any) -> Optional[datetime]:
        if raw_value is None:
            return None
        if isinstance(raw_value, datetime):
            return raw_value
        text = str(raw_value).strip()
        if not text:
            return None
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            pass
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
            try:
                return datetime.strptime(text, fmt)
            except Exception:
                continue
        return None

    @staticmethod
    def _detect_failure_reason(response_html: str) -> str:
        html = (response_html or "").lower()
        if not html:
            return "empty_response"
        if "cf-turnstile" in html or "g-recaptcha" in html or "captcha" in html:
            return "captcha_or_challenge"
        if "just a moment" in html or "checking your browser" in html or "cloudflare" in html:
            return "cloudflare_challenge"
        if "rate limit" in html or "too many requests" in html:
            return "rate_limited"
        if "/go/" in html and "_token" not in html:
            return "token_missing"
        return "no_final_url"
