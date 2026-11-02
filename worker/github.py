"""Fetch only public GitHub repositories and commit-pinned archives."""

import ipaddress
import os
import re
import socket
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urljoin, urlsplit

import httpx

_OWNER = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")
_REPO = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")
_SHA = re.compile(r"^[0-9a-f]{40}$")
_HOSTS = {"api.github.com", "codeload.github.com"}


class AnalysisError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class LimitExceeded(AnalysisError):
    def __init__(self, message: str):
        super().__init__("LIMIT_EXCEEDED", message)


@dataclass(frozen=True)
class RepositoryAddress:
    owner: str
    name: str

    @property
    def url(self) -> str:
        return f"https://github.com/{self.owner}/{self.name}"


def parse_repository_url(url: str) -> RepositoryAddress:
    parts = urlsplit(url)
    if (parts.scheme != "https" or parts.netloc.lower() != "github.com" or
            parts.query or parts.fragment or "?" in url or "#" in url):
        raise AnalysisError("INVALID_REPOSITORY_URL", "Expected https://github.com/owner/repository")
    path = parts.path.strip("/").split("/")
    if (len(path) != 2 or not _OWNER.fullmatch(path[0]) or not _REPO.fullmatch(path[1]) or
            path[0].endswith("-") or path[1] in {".", ".."} or ".." in path[1]):
        raise AnalysisError("INVALID_REPOSITORY_URL", "Invalid GitHub owner or repository name")
    return RepositoryAddress(*path)


def validate_sha(sha: str) -> str:
    if not _SHA.fullmatch(sha):
        raise AnalysisError("INVALID_COMMIT_SHA", "Commit SHA must contain 40 lowercase hexadecimal characters")
    return sha


def _validate_destination(url: str) -> str:
    parts = urlsplit(url)
    if (parts.scheme != "https" or parts.hostname not in _HOSTS or
            parts.netloc.lower() != parts.hostname or parts.fragment):
        raise AnalysisError("UNSAFE_REDIRECT", "GitHub request attempted to access a disallowed host")
    try:
        addresses = socket.getaddrinfo(parts.hostname, 443, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise AnalysisError("GITHUB_UNAVAILABLE", "GitHub DNS lookup failed") from exc
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise AnalysisError("UNSAFE_REDIRECT", "GitHub hostname resolved to a non-public address")
    return parts.hostname


class GitHubClient:
    def __init__(self, *, token: str | None = None, client: httpx.Client | None = None):
        self.token = token if token is not None else os.environ.get("GITHUB_TOKEN")
        self.client = client or httpx.Client(timeout=30, follow_redirects=False, trust_env=False)
        self._owns_client = client is None

    def close(self):
        if self._owns_client:
            self.client.close()

    def _get(self, url: str, *, max_bytes: int, destination: Path | None = None,
             deadline: float | None = None) -> bytes | None:
        size_error = (f"Archive exceeds the size limit ({max_bytes} bytes; MAX_ARCHIVE_BYTES)" if destination else
                      f"GitHub API response exceeds the size limit ({max_bytes} bytes)")
        for _ in range(4):
            if deadline is not None and time.monotonic() >= deadline:
                raise LimitExceeded("Analysis time limit exceeded")
            host = _validate_destination(url)
            headers = {"Accept": "application/vnd.github+json", "User-Agent": "RepoAtlas/0.1"}
            if self.token and host == "api.github.com":
                headers["Authorization"] = f"Bearer {self.token}"
            try:
                with self.client.stream("GET", url, headers=headers, follow_redirects=False) as response:
                    if response.status_code in (301, 302, 303, 307, 308):
                        location = response.headers.get("location")
                        if not location:
                            raise AnalysisError("GITHUB_UNAVAILABLE", "GitHub returned an invalid redirect")
                        url = urljoin(url, location)
                        continue
                    if response.status_code in (403, 429):
                        raise AnalysisError("GITHUB_RATE_LIMITED", "GitHub denied or rate-limited the request")
                    if response.status_code == 404:
                        raise AnalysisError("GITHUB_NOT_FOUND", "Public repository or commit was not found")
                    if response.status_code != 200:
                        raise AnalysisError("GITHUB_UNAVAILABLE", f"GitHub returned HTTP {response.status_code}")
                    length = response.headers.get("content-length")
                    if length and length.isdigit() and int(length) > max_bytes:
                        raise LimitExceeded(size_error)
                    chunks = []
                    size = 0
                    output = destination.open("wb") if destination else None
                    try:
                        for chunk in response.iter_bytes():
                            if deadline is not None and time.monotonic() >= deadline:
                                raise LimitExceeded("Analysis time limit exceeded")
                            size += len(chunk)
                            if size > max_bytes:
                                raise LimitExceeded(size_error)
                            if output:
                                output.write(chunk)
                            else:
                                chunks.append(chunk)
                    finally:
                        if output:
                            output.close()
                    return None if destination else b"".join(chunks)
            except httpx.HTTPError as exc:
                raise AnalysisError("GITHUB_UNAVAILABLE", "GitHub request failed") from exc
        raise AnalysisError("UNSAFE_REDIRECT", "Too many GitHub redirects")

    def resolve_default_commit(self, repo: RepositoryAddress, deadline: float | None = None) -> str:
        import json

        repo = parse_repository_url(repo.url)
        prefix = f"https://api.github.com/repos/{repo.owner}/{repo.name}"
        try:
            metadata = json.loads(self._get(prefix, max_bytes=2_000_000, deadline=deadline))
            if metadata.get("private") is not False:
                raise AnalysisError("GITHUB_NOT_PUBLIC", "Only public GitHub repositories are supported")
            branch = metadata["default_branch"]
            ref = json.loads(self._get(f"{prefix}/git/ref/heads/{quote(branch, safe='/')}", max_bytes=2_000_000, deadline=deadline))
            if ref["object"]["type"] != "commit":
                raise ValueError("Default branch does not reference a commit")
            return validate_sha(ref["object"]["sha"].lower())
        except (KeyError, TypeError, ValueError) as exc:
            raise AnalysisError("GITHUB_UNAVAILABLE", "GitHub returned invalid repository metadata") from exc

    def download_archive(self, repo: RepositoryAddress, sha: str, destination: Path, *,
                         max_bytes: int, deadline: float | None = None) -> None:
        validate_sha(sha)
        repo = parse_repository_url(repo.url)
        url = f"https://codeload.github.com/{repo.owner}/{repo.name}/zip/{sha}"
        self._get(url, max_bytes=max_bytes, destination=destination, deadline=deadline)
