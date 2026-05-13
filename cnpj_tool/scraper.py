from __future__ import annotations


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"
)


class CnpjBizError(Exception):
    status = "fetch_error"


class CnpjBizBlockedError(CnpjBizError):
    status = "blocked_by_cloudflare"


class CnpjBizNotFoundError(CnpjBizError):
    status = "not_found"


def is_cloudflare_challenge(html: str) -> bool:
    lowered = (html or "").casefold()
    markers = [
        "just a moment",
        "verify you are human",
        "cloudflare security challenge",
        "cf_chl",
        "challenge-platform",
        "turnstile",
        "aguarde um momento",
        "navegador desatualizado",
    ]
    return any(marker in lowered for marker in markers)
