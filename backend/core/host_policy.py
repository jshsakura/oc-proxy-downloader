"""Host identity and transfer caps, independent of parser/browser imports.

A browser resolution being serialized does not imply that file transfers must
be serialized. Only the caps below restrict the entire parse/transfer lifetime.
"""

import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse


SITE_DOWNLOAD_LIMITS = {
    "1fichier.com": 1,  # free flow, including proxy downloads
    "megaup.net": 1,
    "datanodes.to": 1,
    "multiup.io": 1,
    "gofile.io": 3,  # three overlapping full guest-web transfers, 2026-09-30
    "rapidgator.net": 1,
    "send.now": 1,
    # Three overlapping direct transfers observed on 2026-09-30; two complete
    # binary files checked on disk. This is evidence for this route, not a
    # guarantee that every file or egress supports three.
    "vikingfile.com": 3,
    "akirabox.com": 1,
    "rootz.so": 1,
    "mediafire.com": 1,
    "pixeldrain.com": 1,
    "bunkr.si": 1,
    "mixdrop.ag": 1,
    "datavaults.co": 1,
    "mega.nz": 1,
    "filecrypt.cc": 1,
    "linkcuy.com": 1,
    "momerybox.com": 1,
    "filekeeper.net": 1,
    "send.cm": 1,
    "uptobox.com": 1,
    "clicknupload.to": 1,
    "filerio.in": 1,
    "frdl.my": 1,
    "letsupload.io": 1,
    "bowfile.com": 1,
    "doodrive.com": 1,
    "solidfiles.com": 1,
    "bayfiles.com": 1,
    "qiwi.gg": 1,
    "zippyshare.com": 1,
    "teraboxapp.com": 1,
    "ouo.io": 1,
    "drive.google.com": 1,
}

BUNKR_HOSTS = (
    "bunkr.si", "bunkr.ru", "bunkr.la", "bunkr.is", "bunkr.to", "bunkr.ax",
    "bunkr.black", "bunkr.cr", "bunkr.fi", "bunkr.pk", "bunkr.ph", "bunkr.sk",
    "bunkr.ci", "bunkr.ws", "bunkr.site", "bunkr.media", "bunkrr.su", "bunkrr.ru",
)

HOST_ALIASES = {
    "drive.usercontent.google.com": "drive.google.com",
    "ouo.press": "ouo.io",
    "send.cm": "send.now",
    "tusfiles.com": "send.now",
    "tusfiles.net": "send.now",
    "clicknupload.cc": "clicknupload.to",
    "clicknupload.red": "clicknupload.to",
    "clicknupload.co": "clicknupload.to",
    "clicknupload.click": "clicknupload.to",
    "clickndownload.org": "clicknupload.to",
    "filerio.com": "filerio.in",
    "frdl.to": "frdl.my",
    "frdl.io": "frdl.my",
    "terabox.app": "teraboxapp.com",
    "1024terabox.com": "teraboxapp.com",
    "terabox.com": "teraboxapp.com",
    "filecrypt.co": "filecrypt.cc",
    "filecrypt.to": "filecrypt.cc",
    "vik1ngfile.site": "vikingfile.com",
    "akirabox.to": "akirabox.com",
    "mixdrop.top": "mixdrop.ag",
    "mxdrop.top": "mixdrop.ag",
    **{host: "bunkr.si" for host in BUNKR_HOSTS},
}


def canonical_host(host: str) -> str:
    """Group known aliases and storage subdomains without substring matching."""
    host = (host or "").lower().rstrip(".").removeprefix("www.")
    for domain in (*SITE_DOWNLOAD_LIMITS, *HOST_ALIASES, "mixdrop.ag"):
        if host == domain or host.endswith("." + domain):
            return HOST_ALIASES.get(domain, domain)
    return host


def host_key_for_url(url: str | None) -> str:
    return canonical_host(urlparse(url or "").hostname or "") or "_default"


def is_single_download_refusal(raw: str) -> bool:
    """Require an explicit single-file refusal, not a generic quota/429."""
    return bool(re.search(
        r"(?:only (?:one|1) (?:file|download) at a time|"
        r"only (?:one|1) download|"
        r"(?:one|1) (?:file|download) at a time|"
        r"already downloading (?:a|some) file|"
        r"limited to 1 download|한 번에 (?:하나|1개)|동시 다운로드.{0,12}1개)",
        raw or "", re.IGNORECASE,
    ))


def is_host_rate_limit(raw: str) -> bool:
    """Some hosts return a rate-limit API body with HTTP 200."""
    text = (raw or "").lower()
    return any(marker in text for marker in (
        "http 429", "too many requests", "error-ratelimit", "무료 조회 속도 제한",
    ))


def http_failure_message(status: int, reason: str, headers) -> str:
    """Preserve Retry-After for the failure classifier (seconds or HTTP date)."""
    message = f"HTTP {status}: {reason}"
    if status != 429:
        return message
    value = (headers.get("Retry-After") or "").strip()
    try:
        seconds = int(value)
    except ValueError:
        try:
            target = parsedate_to_datetime(value)
            seconds = max(0, int((target - datetime.now(timezone.utc)).total_seconds()) + 1)
        except (ValueError, TypeError, OverflowError):
            return message
    return f"{message}; you must wait {max(0, seconds)} seconds"
