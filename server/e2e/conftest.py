"""
프록시 경유 E2E (M4-1) — 실제 Caddy → uvicorn 경로, **운영 이미지·운영 설정**(prod 타깃, 워커 2개, ENVIRONMENT=production,
오리진 없음). 로컬과 CI 가 같은 명령이다(scripts/e2e-proxy.sh):

    bash scripts/e2e-proxy.sh

`E2E_BASE_URL` 이 없으면 전부 건너뛴다(기본 `pytest` 는 testpaths=tests 라 여기를 모으지도 않는다).
정상 세션 중 닫힘 코드(1012·4000)·다중 워커 경합·장애는 하네스(server/harness/multiworker)가 맡는다.
"""

import os

import pytest

BASE = os.environ.get("E2E_BASE_URL")


def pytest_collection_modifyitems(config, items):
    if BASE:
        return
    skip = pytest.mark.skip(reason="E2E_BASE_URL not set — proxy E2E runs only against a live stack")
    for item in items:
        item.add_marker(skip)


@pytest.fixture
def base() -> str:
    return BASE.rstrip("/")


@pytest.fixture
def ws_base(base) -> str:
    return "ws" + base[len("http"):]
