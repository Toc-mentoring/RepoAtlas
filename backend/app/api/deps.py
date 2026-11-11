"""API에서 공통으로 쓰는 의존성(DB 세션, GitHub 클라이언트)."""

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from backend.app.db.session import make_engine
from backend.app.services.github import GitHubClient


@lru_cache
def get_engine() -> Engine:
    # 처음 요청이 들어올 때 한 번만 DB 연결 도구를 만들고 재사용한다.
    return make_engine()


def get_db() -> Iterator[Session]:
    # 요청 하나마다 DB 세션을 열고, 응답이 끝나면 자동으로 닫는다.
    with Session(get_engine()) as session:
        yield session


def get_github_client() -> Iterator[GitHubClient]:
    client = GitHubClient()
    try:
        yield client
    finally:
        client.close()
