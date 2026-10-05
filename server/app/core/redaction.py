"""
로그에서 access token 을 가린다 (M3 7단계, maze.md §2)

WS 인증은 쿼리 파라미터(`?token=`)로 한다 — 브라우저가 핸드셰이크에 헤더를 못 붙인다. uvicorn 은 WS 접속을 경로와
**쿼리 문자열까지** 로그에 남기므로 그대로 두면 토큰이 로그로 샌다(만료 전이면 재사용 가능). 레코드가 출력되기 전에
`token=` 값을 `***` 로 바꾼다.
"""

import logging
import re

_TOKEN = re.compile(r"(token=)[^&\s\"']+")
LOGGERS = ("", "uvicorn", "uvicorn.error", "uvicorn.access", "app")


class TokenRedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        if "token=" in message:
            record.msg, record.args = _TOKEN.sub(r"\1***", message), ()
        return True


_filter = TokenRedactingFilter()


def install() -> None:
    """로거와 그 핸들러에 건다. 로거 필터는 그 로거에 직접 남긴 레코드에만 돌고(자식 로거 `app.ws.…` 는 빠진다),
    핸들러 필터는 그 핸들러를 지나는 모든 레코드에 돈다 — 둘 다 건다. 기동 시 한 번(main.py), 로깅 설정 뒤에"""
    for name in LOGGERS:
        logger = logging.getLogger(name)
        for target in (logger, *logger.handlers):
            if _filter not in target.filters:
                target.addFilter(_filter)
