"""LLM에 넘기는 Tool 목록과 분류 프롬프트.

Tool 본문은 실행하지 않습니다. LLM이 고른 도구 이름(metric)과 `title` 인자만
사용하고, SQL은 서버가 고정·검증한 것만 실행합니다.
"""
from app.ai.api_use.query.validator import Metric


def get_first_listen(title: str = "") -> None:
    """사용자가 곡을 처음 들은 날짜(최초 기록일)를 묻는 질문에 사용한다.

    Args:
        title: 질문에 나온 곡명만 그대로. '이 노래'처럼 곡명이 없으면 빈 문자열.
    """


def get_total_listen_time(title: str = "") -> None:
    """사용자가 곡을 총 얼마나 들었는지(총 재생 시간)를 묻는 질문에 사용한다.

    Args:
        title: 질문에 나온 곡명만 그대로. '이 노래'처럼 곡명이 없으면 빈 문자열.
    """


def get_listen_summary(title: str = "") -> None:
    """최초 기록일과 총 재생 시간을 함께 묻는 질문에 사용한다.

    Args:
        title: 질문에 나온 곡명만 그대로. '이 노래'처럼 곡명이 없으면 빈 문자열.
    """


TOOLS = [get_first_listen, get_total_listen_time, get_listen_summary]
TOOL_METRIC: dict[str, Metric] = {"get_first_listen": "first", "get_total_listen_time": "total", "get_listen_summary": "both"}
SYSTEM_PROMPT = (
    "너는 음악 청취 기록 앱의 질문 분류기다. 사용자 본인의 특정 곡에 대한 최초 기록일 또는 총 재생 시간 질문이면 "
    "알맞은 도구 하나를 호출하고, 그 외 질문(기간 한정, 다른 사용자, 순위, 수정·삭제, 잡담 등)에는 도구를 호출하지 마라."
)
