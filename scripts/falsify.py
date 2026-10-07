"""
반증(검증 관문 G4) — 구현을 일부러 틀리게 바꿔 테스트가 실패하는지 본다. 변이 하나씩, **항상 원문 복원**.

    python scripts/falsify.py <cases.json>

cases.json — 목록. 항목마다:
    {"name": "설명", "file": "server 기준 경로(예: app/ws/bus.py)", "old": "정확히 한 번 나오는 원문",
     "new": "바꿀 문자열", "tests": ["tests/...::test_x"]}
  또는 셸 검사(예: 가드 스크립트):
    {"name": "...", "file": "저장소 루트 기준 경로", "root": true, "old": "...", "new": "...", "cmd": ["bash", "scripts/x.sh"]}

판정은 사람이 한다 — 출력의 "N failed"(pytest) 또는 "exit 1"(cmd)이 기대한 결과다. 통과해 버리면 등가 변이인지(다른 방어가
겹침) 판별력 공백인지 가린다(docs/plans/README.md "검증 관문과 독립 검토").

왜 스크립트인가: 여러 변이를 한 셸 명령에 몰면 중간에 끊길 때(137 강제 종료) 변이가 작업 사본에 남는다(M3 6단계). 셸 함수
안의 백업·복원(mv) 루프는 Claude Code 안전 검사에 막힌다(M4-1). 이 스크립트는 메모리에 원문을 들고 finally 로 복원한다.
"""

import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASH = shutil.which("bash") or "bash"


def run_case(case: dict) -> str:
    base = ROOT if case.get("root") else os.path.join(ROOT, "server")
    path = os.path.join(base, case["file"])
    original = open(path, encoding="utf-8").read()
    try:
        if original.count(case["old"]) != 1:
            return f"SETUP FAIL — 'old' must appear exactly once (found {original.count(case['old'])})"
        open(path, "w", encoding="utf-8", newline="\n").write(original.replace(case["old"], case["new"]))
        if "cmd" in case:
            cmd = [BASH if c == "bash" else c for c in case["cmd"]]
            code = subprocess.run(cmd, cwd=ROOT, capture_output=True).returncode
            return f"exit {code}"
        out = subprocess.run(
            ["docker", "compose", "run", "--rm", "server-test", "pytest", *case["tests"], "-q", "-p", "no:cacheprovider"],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600,
        ).stdout
        tail = [line for line in out.splitlines() if " passed" in line or " failed" in line or "error" in line.lower()]
        return tail[-1] if tail else out[-300:]
    finally:
        open(path, "w", encoding="utf-8", newline="\n").write(original)


def main() -> None:
    cases = json.load(open(sys.argv[1], encoding="utf-8"))
    for case in cases:
        print(f"{case['name']} -> {run_case(case)}", flush=True)
    print("restored all")


if __name__ == "__main__":
    main()
