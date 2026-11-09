"""GitHub 주소 검사와 GitHub 응답 처리 테스트 (네트워크·DB 없이 실행)."""

import httpx
import pytest

from backend.app.api.errors import ApiError
from backend.app.services.github import GitHubClient, RepoRef, parse_github_url


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/example-org/sample-web",
        "https://github.com/example-org/sample-web/",
        "https://github.com/example-org/sample-web.git",
        "https://www.github.com/example-org/sample-web",
        "  https://GitHub.com/example-org/sample-web  ",
    ],
)
def test_parse_valid_urls(url):
    assert parse_github_url(url) == RepoRef("example-org", "sample-web")


@pytest.mark.parametrize(
    "url",
    [
        "",
        "github.com/example-org/sample-web",
        "http://github.com/example-org/sample-web",
        "https://gitlab.com/example-org/sample-web",
        "https://github.com/example-org",
        "https://github.com/example-org/sample-web/tree/main",
        "https://github.com/example-org/sample-web?tab=readme",
        "https://github.com:8443/example-org/sample-web",
        "https://user@github.com/example-org/sample-web",
        "https://github.com/-bad/sample-web",
        "https://github.com/example-org/..",
    ],
)
def test_parse_invalid_urls(url):
    with pytest.raises(ApiError) as caught:
        parse_github_url(url)
    assert caught.value.status_code == 422
    assert caught.value.code == "INVALID_REPOSITORY_URL"


def make_client(handler, token=None):
    return GitHubClient(http=httpx.Client(transport=httpx.MockTransport(handler)), token=token)


REF = RepoRef("example-org", "sample-web")


def test_get_repository_success_uses_github_names():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(
            200,
            json={"owner": {"login": "Example-Org"}, "name": "Sample-Web", "default_branch": "develop", "private": False},
        )

    info = make_client(handler, token="secret").get_repository(REF)

    assert seen["url"] == "https://api.github.com/repos/example-org/sample-web"
    assert seen["auth"] == "Bearer secret"
    assert info.owner == "Example-Org"
    assert info.name == "Sample-Web"
    assert info.default_branch == "develop"
    assert info.canonical_url == "https://github.com/Example-Org/Sample-Web"


@pytest.mark.parametrize(
    ("response", "status_code", "code"),
    [
        (httpx.Response(404, json={}), 404, "REPOSITORY_NOT_FOUND"),
        (httpx.Response(200, json={"owner": {"login": "a"}, "name": "b", "private": True}), 404, "REPOSITORY_NOT_FOUND"),
        (httpx.Response(403, headers={"x-ratelimit-remaining": "0"}, json={}), 429, "RATE_LIMITED"),
        (httpx.Response(429, headers={"retry-after": "30"}, json={}), 429, "RATE_LIMITED"),
        (httpx.Response(403, json={}), 403, "GITHUB_FORBIDDEN"),
        (httpx.Response(500, json={}), 502, "GITHUB_UNAVAILABLE"),
    ],
)
def test_get_repository_errors(response, status_code, code):
    with pytest.raises(ApiError) as caught:
        make_client(lambda request: response).get_repository(REF)
    assert caught.value.status_code == status_code
    assert caught.value.code == code


def test_rate_limit_sets_retry_after():
    response = httpx.Response(429, headers={"retry-after": "30"}, json={})
    with pytest.raises(ApiError) as caught:
        make_client(lambda request: response).get_repository(REF)
    assert caught.value.headers == {"Retry-After": "30"}


def test_network_error_is_github_unavailable():
    def handler(request):
        raise httpx.ConnectError("boom", request=request)

    with pytest.raises(ApiError) as caught:
        make_client(handler).get_repository(REF)
    assert caught.value.status_code == 502
    assert caught.value.code == "GITHUB_UNAVAILABLE"
