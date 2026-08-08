from fastapi import Request

from app.config import get_settings


def client_ip(request: Request) -> str:
    """Resolve the customer's IP for rate-limiting purposes.

    `request.client.host` is the peer that opened the TCP connection. Behind
    nginx that is always the proxy, which would collapse every customer on the
    internet into a single rate-limit bucket — a limit meant to stop one
    attacker would instead lock out everyone at once.

    So when a trusted proxy is in front, read X-Real-IP, which nginx sets from
    $remote_addr and therefore cannot be forged by the browser. Never read
    X-Forwarded-For here: it is a client-supplied list, and trusting its
    leftmost entry is the standard way this control gets bypassed.

    With no trusted proxy the headers are ignored entirely, because anything a
    client can set, a client can lie about.
    """
    settings = get_settings()

    if settings.trust_proxy_headers:
        real_ip = request.headers.get("x-real-ip", "").strip()
        if real_ip:
            return real_ip

    return request.client.host if request.client else "unknown"
