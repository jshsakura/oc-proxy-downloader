"""Validate URL syntax. Host support is decided by the actual parser response."""

from urllib.parse import urlsplit


def enqueue_link_error(url):
    try:
        parsed = urlsplit(url)
        port = parsed.port
        host = parsed.hostname
    except ValueError:
        return "올바른 HTTP 다운로드 URL이 필요합니다."
    if (parsed.scheme not in {"http", "https"} or not host
            or parsed.username is not None or parsed.password is not None
            or any(char.isspace() for char in host) or port == 0):
        return "올바른 HTTP 다운로드 URL이 필요합니다."
    return None
