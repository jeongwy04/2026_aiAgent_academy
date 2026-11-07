"""LLM에 넘기는 Tool 목록과 분류 프롬프트.

Tool 본문은 실행하지 않습니다. LLM이 고른 도구 이름(metric)과 `title` 인자만
사용합니다. 곡별 지표는 서버 고정 SQL, 자유 통계는 Text-to-SQL 경로(text_to_sql.py)로 갑니다.
"""
from typing import Literal

from app.ai.api_use.query.validator import Metric

Intent = Metric | Literal["stats"]


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


def query_listening_stats() -> None:
    """기간·순위·집계 등 사용자 본인 청취 기록에 대한 자유로운 통계 질문에 사용한다.
    예: '이번 달 제일 많이 들은 곡', '월별 청취 시간', '지난주에 들은 곡 수', '지난달 입춘 재생 시간'.
    """


TOOLS = [get_first_listen, get_total_listen_time, get_listen_summary, query_listening_stats]
TOOL_METRIC: dict[str, Intent] = {
    "get_first_listen": "first", "get_total_listen_time": "total", "get_listen_summary": "both",
    "query_listening_stats": "stats",
}
SYSTEM_PROMPT = (
    "너는 음악 청취 기록 앱의 질문 분류기다. 기간 조건이 없는 특정 곡 하나의 전체 최초 기록일·총 재생 시간 질문이면 "
    "get_first_listen/get_total_listen_time/get_listen_summary 중 하나를, 기간·순위·여러 곡 집계 등 본인 청취 기록 통계 질문이면 "
    "query_listening_stats를 호출하라. 다른 사용자, 수정·삭제, 잡담 등 그 외 질문에는 도구를 호출하지 마라."
)
