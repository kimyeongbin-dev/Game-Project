"""prod CMD 의 uvicorn 플래그 ↔ settings 기본값 — 한쪽만 바꾸면 설계상 감지 지연과 실제 서버가 어긋난다 (M3 7단계)"""

import json
import re
from pathlib import Path

from app.core.config import Settings

DOCKERFILE = Path(__file__).resolve().parents[1] / "Dockerfile"


def prod_cmd() -> list[str]:
    text = DOCKERFILE.read_text(encoding="utf-8")
    prod = text[text.index("FROM base AS prod"):].replace("\\\n", " ")
    match = re.search(r"^CMD (\[.*?\])\s*$", prod, re.M)
    assert match, "prod CMD not found"
    return json.loads(match.group(1))


def flag(cmd: list[str], name: str) -> str:
    assert name in cmd, f"{name} missing from prod CMD"
    return cmd[cmd.index(name) + 1]


def test_ws_flags_match_settings():
    cmd = prod_cmd()
    defaults = Settings(_env_file=None)
    assert float(flag(cmd, "--ws-ping-interval")) == defaults.ws_ping_interval_sec
    assert float(flag(cmd, "--ws-ping-timeout")) == defaults.ws_ping_timeout_sec
    assert int(flag(cmd, "--ws-max-size")) == defaults.ws_max_size_bytes
