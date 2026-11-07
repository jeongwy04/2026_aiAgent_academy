"""질문 분류 정규식: 본인 곡 제목 지우기, 단어 경계, '이 노래' 판별. (LLM 키 없음 → 정규식 경로)"""
import pytest

from app.ai.api_use.chat_classify import classify_question, mask_titles
from app.config import get_settings
from app.services.chat_service import is_unspecified


@pytest.fixture(autouse=True)
def regex_only(monkeypatch):
    """.env에 PICKLE_API_KEY가 있어도 실제 LLM을 부르지 않게 정규식 경로로 고정."""
    monkeypatch.setenv("PICKLE_API_KEY", "")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_own_title_is_masked_before_stats_hint():
    assert classify_question("12월의 기적 언제부터 들었어?") == (None, "")  # 제목을 모르면 "12월"이 기간으로 걸림
    assert classify_question("12월의 기적 언제부터 들었어?", ["12월의 기적"]) == ("first", "12월의 기적")
    assert classify_question("오늘도 얼마나 들었어?", ["오늘도"]) == ("total", "오늘도")
    assert classify_question("지난달 입춘 얼마나 들었어?", ["입춘"]) == (None, "")  # 기간 표현은 그대로 남음


def test_out_of_scope_word_boundary():
    assert classify_question("Raindrop 총 몇 시간 들었어?") == ("total", "raindrop")
    assert classify_question("입춘'; DROP TABLE tracks; -- 얼마나 들었어")[0] is None
    assert classify_question("입춘 drop 얼마나 들었어")[0] is None
    assert classify_question("입춘 기록 삭제해줘", ["입춘"])[0] is None  # "삭제"는 제목을 지워도 남음


def test_mask_titles_longest_first_and_skips_single_char():
    assert mask_titles("봄날의 기억 언제부터", ["봄날", "봄날의 기억"]).split() == ["언제부터"]
    assert mask_titles("봄 3일 얼마나", ["봄"]) == "봄 3일 얼마나"


@pytest.mark.parametrize("title", ["", "이 노래", "이노래", "이 노래를", "그 곡은", "저 노래", "이 노래 제", "이 곡 내"])
def test_deictic_titles(title):
    assert is_unspecified(title)


@pytest.mark.parametrize("title", ["입춘", "이 노래가 좋아", "그곡의 끝", "사건의 지평선"])
def test_real_titles(title):
    assert not is_unspecified(title)
