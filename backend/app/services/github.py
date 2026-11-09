"""GitHub 저장소 주소 검사와 공개 저장소 정보 조회."""

import os
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

from backend.app.api.errors import ApiError

GITHUB_API = "https://api.github.com"

_OWNER = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")
_REPO = re.compile(r"^[A-Za-z0-9._-]{1,100}$")


def _invalid_url(url: str) -> ApiError:
    return ApiError(
        422,
        "INVALID_REPOSITORY_URL",
        "https://github.com/소유자/저장소 형식의 주소를 입력해 주세요.",
        {"url": url},
    )


@dataclass(frozen=True)
class RepoRef:
    owner: str
    name: str

    @property
    def canonical_url(self) -> str:
        return f"https://github.com/{self.owner}/{self.name}"


@dataclass(frozen=True)
class GitHubRepository:
    owner: str
    name: str
    default_branch: str

    @property
    def canonical_url(self) -> str:
        return f"https://github.com/{self.owner}/{self.name}"


def parse_github_url(url: str) -> RepoRef:
    """'https://github.com/소유자/저장소' 모양인지 검사하고 소유자·저장소 이름을 꺼낸다."""
    try:
        parts = urlsplit(url.strip())
        port = parts.port
    except ValueError:
        raise _invalid_url(url) from None

    if (
        parts.scheme != "https"
        or parts.hostname not in {"github.com", "www.github.com"}
        or port is not None
        or parts.username
        or parts.password
        or parts.query
        or parts.fragment
    ):
        raise _invalid_url(url)

    segments = [segment for segment in parts.path.split("/") if segment]
    if len(segments) != 2:
        raise _invalid_url(url)

    owner, name = segments
    if name.endswith(".git"):
        name = name[:-4]
    if not _OWNER.match(owner) or not _REPO.match(name) or name in {".", ".."}:
        raise _invalid_url(url)
    return RepoRef(owner=owner, name=name)


class GitHubClient:
    """GitHub REST API에 공개 저장소 정보를 물어본다."""

    def __init__(self, http: httpx.Client | None = None, token: str | None = None) -> None:
        self._http = http or httpx.Client(timeout=10.0, follow_redirects=True)
        self._token = token if token is not None else (os.environ.get("GITHUB_TOKEN") or None)

    def close(self) -> None:
        self._http.close()

    def get_repository(self, ref: RepoRef) -> GitHubRepository:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "RepoAtlas",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"

        try:
            response = self._http.get(f"{GITHUB_API}/repos/{ref.owner}/{ref.name}", headers=headers)
        except httpx.HTTPError:
            raise ApiError(502, "GITHUB_UNAVAILABLE", "GitHub에 연결하지 못했습니다.") from None

        status = response.status_code
        if status == 404:
            raise ApiError(
                404,
                "REPOSITORY_NOT_FOUND",
                "GitHub에서 공개 저장소를 찾을 수 없습니다.",
                {"owner": ref.owner, "name": ref.name},
            )
        if status == 429 or (status == 403 and response.headers.get("x-ratelimit-remaining") == "0"):
            retry_after = response.headers.get("retry-after") or "60"
            raise ApiError(
                429,
                "RATE_LIMITED",
                "GitHub 요청 한도를 초과했습니다. 잠시 후 다시 시도해 주세요.",
                headers={"Retry-After": retry_after},
            )
        if status in (401, 403):
            raise ApiError(403, "GITHUB_FORBIDDEN", "GitHub가 저장소 접근을 거부했습니다.")
        if status != 200:
            raise ApiError(502, "GITHUB_UNAVAILABLE", "GitHub 응답이 올바르지 않습니다.", {"status": status})

        data = response.json()
        if data.get("private"):
            # MVP는 공개 저장소만 지원한다.
            raise ApiError(404, "REPOSITORY_NOT_FOUND", "공개 저장소만 등록할 수 있습니다.")
        return GitHubRepository(
            owner=data["owner"]["login"],
            name=data["name"],
            default_branch=data.get("default_branch") or "main",
        )
