"""질문 분류: 범위 가드 → LLM Tool Calling → 실패 시 정규식 fallback.

자유 통계(stats)는 Text-to-SQL이 필요하므로 LLM이 있을 때만 지원합니다.
"""
import logging
import re
from functools import lru_cache

from app.ai.api_use.intent_list import SYSTEM_PROMPT, TOOL_METRIC, TOOLS, Intent
from app.ai.api_use.query.validator import Metric
from app.config import get_settings
from app.utils import normalized

logger = logging.getLogger(__name__)

# Always rejected, before any classifier: modifications, third-party data, SQL markers.
OUT_OF_SCOPE = re.compile(r"다른\s*(사용자|사람|회원)|타인|(전체|모든)\s*(사용자|회원)|삭제|수정|변경|업데이트|drop|insert|update|delete|;|--|/\*")
# Period/ranking questions: Text-to-SQL path only (fixed per-track SQL would ignore the period).
STATS_HINT = re.compile(r"이번\s*달|지난\s*달|월별|기간별|가장|제일|랭킹|순위|오늘|어제|작년|올해|지난주|이번주|지난달|이번달|지난\s*주|이번\s*주|\d+\s*년|\d+\s*월|\d+\s*일|부터.*까지")


def classify(question: str) -> Metric | None:
    """Regex fallback used when the LLM is unavailable."""
    q = normalized(question)
    first = bool(re.search(r"최초|처음|언제.*(듣|들|기록)|언제부터", q))
    total = bool(re.search(r"총.*(시간|재생|들었|듣)|얼마나|몇\s*(시간|분|초)|재생\s*시간", q))
    if first and total:
        return "both"
    if first:
        return "first"
    if total:
        return "total"
    return None


def extract_title(question: str) -> str:
    quoted = re.search(r"[\"'“‘](.+?)[\"'”’]", question)
    if quoted:
        return normalized(quoted.group(1))
    q = normalized(question).rstrip("?!., ")
    q = re.sub(r"^(저는|나는|제가|내가)\s+", "", q)
    q = re.split(r"\s+(?:언제|처음|최초|총|얼마나|몇\s*(?:시간|분|초)|재생\s*시간)", q, maxsplit=1)[0]
    q = re.sub(r"(?:의|은|는|을|를)$", "", q).strip()
    return q


@lru_cache
def chat_model(api_key: str, model: str, base_url: str, timeout: float = 10, max_retries: int = 1):
    from langchain_openai import ChatOpenAI  # optional at import time: missing package = regex fallback

    return ChatOpenAI(model=model, api_key=api_key, base_url=base_url, temperature=0,
                      timeout=timeout, max_retries=max_retries)


@lru_cache
def _llm(api_key: str, model: str, base_url: str):
    return chat_model(api_key, model, base_url).bind_tools(TOOLS)


def llm_classify(question: str) -> tuple[Intent | None, str] | None:
    """Returns (metric, title), or None when the regex fallback should be used."""
    settings = get_settings()
    if not settings.pickle_api_key:
        return None
    try:
        calls = _llm(settings.pickle_api_key, settings.chat_model, settings.llm_base_url).invoke(
            [("system", SYSTEM_PROMPT), ("human", question)]).tool_calls
    except Exception:
        logger.warning("LLM classification failed; using regex fallback", exc_info=True)
        return None
    calls = [c for c in calls if c["name"] in TOOL_METRIC]
    if not calls:
        return None, ""
    metrics = {TOOL_METRIC[c["name"]] for c in calls}
    if "stats" in metrics:
        return "stats", ""
    metric: Metric = metrics.pop() if len(metrics) == 1 else "both"
    title = next((str(c["args"].get("title") or "") for c in calls if c["args"].get("title")), "")
    return metric, normalized(title)


def classify_question(question: str) -> tuple[Intent | None, str]:
    """(intent, title). intent가 None이면 지원하지 않는 질문입니다."""
    q = normalized(question)
    if OUT_OF_SCOPE.search(q):
        return None, ""
    result = llm_classify(question)
    if result is None:  # No LLM: fixed metrics only; period questions can't be answered safely.
        return (None, "") if STATS_HINT.search(q) else (classify(question), extract_title(question))
    intent, title = result
    if intent in ("first", "total", "both") and STATS_HINT.search(q):
        return "stats", ""  # e.g. "지난달 입춘 얼마나": an all-time answer would be wrong.
    return intent, title
