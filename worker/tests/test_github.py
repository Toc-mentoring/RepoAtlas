import socket

import httpx
import pytest

from worker.github import AnalysisError, GitHubClient, LimitExceeded, parse_repository_url


@pytest.mark.parametrize("url", [
    "http://github.com/owner/repo", "https://github.com.evil.test/owner/repo",
    "https://user@github.com/owner/repo", "https://github.com:443/owner/repo",
    "https://github.com/owner/../repo", "https://github.com/owner/repo?x=1",
    "https://github.com/owner/repo#fragment", "https://github.com/owner/repo/extra",
])
def test_rejects_untrusted_repository_urls(url):
    with pytest.raises(AnalysisError):
        parse_repository_url(url)


def public_dns(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("1.1.1.1", 443))])


def test_resolves_commit_and_downloads_sha_pinned_archive(monkeypatch, tmp_path):
    public_dns(monkeypatch)
    sha = "a" * 40
    requested = []

    def handle(request):
        requested.append(str(request.url))
        if request.url.host == "api.github.com" and request.url.path == "/repos/example/repo":
            return httpx.Response(200, json={"private": False, "default_branch": "main"})
        if request.url.host == "api.github.com":
            return httpx.Response(200, json={"object": {"type": "commit", "sha": sha}})
        assert request.url.host == "codeload.github.com"
        assert "authorization" not in request.headers
        return httpx.Response(200, content=b"archive")

    with httpx.Client(transport=httpx.MockTransport(handle)) as transport:
        github = GitHubClient(token="secret", client=transport)
        repo = parse_repository_url("https://github.com/example/repo")
        assert github.resolve_default_commit(repo) == sha
        assert requested[1] == "https://api.github.com/repos/example/repo/git/ref/heads/main"
        destination = tmp_path / "snapshot.zip"
        github.download_archive(repo, sha, destination, max_bytes=20)
        assert destination.read_bytes() == b"archive"
        assert requested[-1] == f"https://codeload.github.com/example/repo/zip/{sha}"


def test_rejects_redirects_to_arbitrary_hosts(monkeypatch):
    public_dns(monkeypatch)
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(302, headers={"location": "https://127.0.0.1/private"}))) as transport:
        github = GitHubClient(client=transport)
        with pytest.raises(AnalysisError, match="disallowed host"):
            github.resolve_default_commit(parse_repository_url("https://github.com/example/repo"))


def test_rejects_private_dns_and_oversized_download(monkeypatch, tmp_path):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))])
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"123456"))) as transport:
        github = GitHubClient(client=transport)
        repo = parse_repository_url("https://github.com/example/repo")
        with pytest.raises(AnalysisError, match="non-public address"):
            github.download_archive(repo, "a" * 40, tmp_path / "snapshot.zip", max_bytes=3)
        public_dns(monkeypatch)
        with pytest.raises(LimitExceeded, match="MAX_ARCHIVE_BYTES"):
            github.download_archive(repo, "a" * 40, tmp_path / "snapshot.zip", max_bytes=3)


def test_branch_names_with_slashes_resolve_using_git_ref(monkeypatch):
    public_dns(monkeypatch)
    def handle(request):
        if request.url.path == "/repos/example/repo":
            return httpx.Response(200, json={"private": False, "default_branch": "release/stable"})
        assert request.url.path == "/repos/example/repo/git/ref/heads/release/stable"
        return httpx.Response(200, json={"object": {"type": "commit", "sha": "b" * 40}})
    with httpx.Client(transport=httpx.MockTransport(handle)) as transport:
        assert GitHubClient(client=transport).resolve_default_commit(parse_repository_url("https://github.com/example/repo")) == "b" * 40
