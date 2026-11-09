"""목록 API에서 쓰는 불투명(opaque) cursor."""

import base64
import json

from backend.app.api.errors import ApiError


def encode_cursor(offset: int) -> str:
    raw = json.dumps({"o": offset}, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str | None) -> int:
    if not cursor:
        return 0
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        offset = json.loads(base64.urlsafe_b64decode(padded.encode()))["o"]
        if not isinstance(offset, int) or offset < 0:
            raise ValueError
        return offset
    except (ValueError, KeyError, TypeError):
        raise ApiError(422, "INVALID_FILTER", "cursor 값이 올바르지 않습니다.", {"cursor": cursor}) from None


def page(rows: list, offset: int, limit: int) -> tuple[list, str | None]:
    """limit+1개를 읽어온 결과에서 다음 페이지가 있는지 판단한다."""
    if len(rows) > limit:
        return rows[:limit], encode_cursor(offset + limit)
    return rows, None
