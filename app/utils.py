import unicodedata


def normalized(value: str | None) -> str:
    """NFKC + casefold + 공백 정리. 곡 식별과 질문 분석에서 같은 규칙을 씁니다."""
    return " ".join(unicodedata.normalize("NFKC", value or "").casefold().split())
