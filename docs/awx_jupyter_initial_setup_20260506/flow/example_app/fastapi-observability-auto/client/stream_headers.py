from __future__ import annotations

def normalize_headers_for_stream_mode(
    headers: list[tuple[bytes, bytes]],
    *,
    stream_enabled: bool,
) -> list[tuple[bytes, bytes]]:
    _ = stream_enabled
    # Preserve user intent: middleware does not rewrite AWX headers.
    return headers


class StreamModeHeaderMiddleware:
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        await self.app(scope, receive, send)
