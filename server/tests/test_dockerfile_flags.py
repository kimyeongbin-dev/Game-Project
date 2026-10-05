"""uvicorn 플래그(dev·prod CMD) ↔ settings 기본값 — 한쪽만 바꾸면 설계상 감지 지연과 실제 서버가 어긋난다 (M3 7단계)"""

import json
import re
from pathlib import Path

import pytest

from app.core.config import Settings

DOCKERFILE = Path(__file__).resolve().parents[1] / "Dockerfile"


def stage_cmd(stage: str) -> list[str]:
    text = DOCKERFILE.read_text(encoding="utf-8")
    body = text[text.index(f"FROM base AS {stage}"):].replace("\\\n", " ")
    match = re.search(r"^CMD (\[.*?\])\s*$", body, re.M)
    assert match, f"{stage} CMD not found"
    return json.loads(match.group(1))


def flag(cmd: list[str], name: str) -> str:
    assert name in cmd, f"{name} missing from CMD"
    return cmd[cmd.index(name) + 1]


@pytest.mark.parametrize("stage", ["prod", "dev"])
def test_ws_flags_match_settings(stage):
    """dev 도 같은 값 — 개발 서버에서 4 KiB 상한과 반개방 감지 지연이 운영과 같게 재현된다(독립 검토 #1 R13)"""
    cmd = stage_cmd(stage)
    defaults = Settings(_env_file=None)
    assert float(flag(cmd, "--ws-ping-interval")) == defaults.ws_ping_interval_sec
    assert float(flag(cmd, "--ws-ping-timeout")) == defaults.ws_ping_timeout_sec
    assert int(flag(cmd, "--ws-max-size")) == defaults.ws_max_size_bytes
