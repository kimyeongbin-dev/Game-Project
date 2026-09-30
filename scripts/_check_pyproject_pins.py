r"""server/pyproject.toml 의 모든 직접 의존성이 == 로 고정되었는지 검사.

grep ERE 의 브래킷 표현식은 백슬래시 이스케이프를 지원하지 않아
"[A-Za-z0-9_.\[\]-]+" 같은 패턴이 조용히 깨진다. 실제 TOML 을 파싱해 확인한다.

위반이 있으면 한 줄씩 stdout 에 출력한다 (호출자가 비어있는지로 판정).
"""

import pathlib
import sys
import tomllib


def main() -> int:
    path = pathlib.Path("server/pyproject.toml")
    if not path.is_file():
        print(f"{path}: 파일이 없습니다")
        return 0

    data = tomllib.loads(path.read_text(encoding="utf-8"))
    project = data.get("project", {})

    groups: dict[str, list] = {"dependencies": project.get("dependencies") or []}
    for extra, deps in (project.get("optional-dependencies") or {}).items():
        groups[f"optional-dependencies.{extra}"] = deps or []
    for name, deps in (data.get("dependency-groups") or {}).items():
        groups[f"dependency-groups.{name}"] = deps or []

    for where, deps in groups.items():
        for dep in deps:
            if not isinstance(dep, str):
                continue
            spec = dep.split(";", 1)[0].strip()  # 환경 마커 제거
            if "==" not in spec:
                print(f"{where}: {dep}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
