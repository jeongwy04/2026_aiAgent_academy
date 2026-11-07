"""평가 실행: 시드 → 질문마다 /api/v1/chat N회 → 기준 SQL과 비교 → 리포트.

    python -m evals.run_eval --runs 3            # 전체
    python -m evals.run_eval --runs 1 --only stats,first-01

실제 LLM을 호출하므로 비용·시간이 듭니다. pytest에는 넣지 않습니다.
준비: docker compose up (API + PostgreSQL), .env에 PICKLE_API_KEY,
      CHAT_REQUESTS_PER_MINUTE=200, CHAT_DEBUG=true (생성 SQL·시도 횟수 확인용).
HTTP API를 거치므로 읽기 전용 계정·RLS·2초 시간 제한까지 운영과 같은 조건으로 검증됩니다.
"""
import argparse
import json
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import httpx
from sqlalchemy import text

from app.config import get_settings
from app.database import session_scope, set_user_context
from evals.scoring import score
from evals.seed import LEAK_TITLE, seed

HERE = Path(__file__).parent


def load_dataset(path: Path, only: str | None) -> list[dict]:
    items = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if only:
        keys = {key.strip() for key in only.split(",")}
        items = [item for item in items if item["id"] in keys or item["category"] in keys]
    return items


def reference_rows(sql: str, user_id: str) -> list[dict]:
    """기준 SQL을 읽기 전용 계정 + RLS 사용자 컨텍스트로 실행합니다. :uid는 회원 A."""
    with session_scope(get_settings().read_database_url) as session:
        set_user_context(session, user_id, readonly=True)
        return [dict(row) for row in session.execute(text(sql), {"uid": user_id}).mappings()]


def ask(client: httpx.Client, members: dict, item: dict) -> tuple[dict, float]:
    body = {"question": item["question"]}
    if item.get("track_title"):
        body["track_id"] = members["a"]["track_ids"][item["track_title"]]
    started = time.perf_counter()
    response = client.post("/api/v1/chat", headers=members["a"]["headers"], json=body)
    seconds = time.perf_counter() - started
    data = response.json() if response.status_code == 200 else {"http_status": response.status_code, "body": response.text[:300]}
    return data, seconds


def report(results: list[dict], runs: int) -> dict:
    by_category = defaultdict(list)
    for result in results:
        by_category[result["category"]].append(result)
    summary = {}
    print(f"\n{'카테고리':<14}{'pass@1':>8}{'pass^' + str(runs):>8}{'평균 SQL 시도':>14}{'평균 응답시간':>12}{'10초 초과':>10}")
    for category, items in by_category.items():
        trials = [trial for item in items for trial in item["trials"]]
        attempts = [trial["sql_attempts"] for trial in trials if trial["sql_attempts"]]
        row = {
            "pass@1": sum(trial["passed"] for trial in trials) / len(trials),
            f"pass^{runs}": sum(all(trial["passed"] for trial in item["trials"]) for item in items) / len(items),
            "avg_sql_attempts": sum(attempts) / len(attempts) if attempts else None,
            "avg_seconds": sum(trial["seconds"] for trial in trials) / len(trials),
            "slow": sum(not trial["time"] for trial in trials),  # 합격 판정과 별도
        }
        summary[category] = row
        avg_attempts = f"{row['avg_sql_attempts']:.1f}" if attempts else "-"
        print(f"{category:<14}{row['pass@1']:>8.0%}{row[f'pass^{runs}']:>8.0%}{avg_attempts:>14}{row['avg_seconds']:>11.1f}s{row['slow']:>10}")
    trials = [trial for result in results for trial in result["trials"]]
    leaks = sum(not trial["no_leak"] for trial in trials)
    overall = sum(trial["passed"] for trial in trials) / len(trials)
    print(f"유출 {leaks}건 | 전체 pass@1 {overall:.0%}")
    failures = [(result, trial) for result in results for trial in result["trials"] if not trial["passed"]]
    if failures:
        print("\n실패 목록:")
    seen = set()
    for result, trial in failures:
        if result["id"] in seen:
            continue  # 질문당 첫 실패만
        seen.add(result["id"])
        failed = [key for key in ("route", "value", "no_leak") if not trial[key]]
        response = trial["response"]
        sqls = [attempt["sql"] for attempt in (response.get("debug") or {}).get("sql_attempts", [])]
        print(f"- {result['id']} [{', '.join(failed)}] {result['question']}")
        print(f"    기대: {result['expect']} {result['expected_rows'] if result['expected_rows'] else ''}")
        print(f"    실제: status={response.get('status', response.get('http_status'))} metric={response.get('metric')} "
              f"rows={response.get('rows')} first={response.get('first_recorded_at')} total={response.get('total_listened_ms')}")
        if sqls:
            print(f"    생성 SQL(마지막): {sqls[-1]}")
        if response.get("http_status") == 429:
            print("    → 요청 제한: .env에 CHAT_REQUESTS_PER_MINUTE=200을 넣고 API를 다시 띄우세요.")
    return {"categories": summary, "leaks": leaks, "overall_pass@1": overall}


def main() -> None:
    parser = argparse.ArgumentParser(description="FirstListen 챗봇 평가")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--only", help="쉼표로 구분한 id 또는 category")
    parser.add_argument("--dataset", type=Path, default=HERE / "dataset.jsonl")
    args = parser.parse_args()

    items = load_dataset(args.dataset, args.only)
    with httpx.Client(base_url=args.base_url, timeout=30) as client:
        client.get("/ready").raise_for_status()
        members = seed(client)
        user_id = members["a"]["id"]
        results, debug_seen = [], False
        for item in items:
            expected = reference_rows(item["reference_sql"], user_id) if item.get("reference_sql") else []
            trials = []
            for _ in range(args.runs):
                response, seconds = ask(client, members, item)
                debug_seen |= response.get("debug") is not None
                checks = score(item, expected, response, seconds, [LEAK_TITLE])
                attempts = len((response.get("debug") or {}).get("sql_attempts", []))
                trials.append({**checks, "seconds": round(seconds, 2), "sql_attempts": attempts, "response": response})
            mark = "".join("O" if trial["passed"] else "X" for trial in trials)
            print(f"{mark:<4} {item['id']:<11} {item['question']}")
            results.append({**item, "expected_rows": expected, "trials": trials})

    if not debug_seen and any(item["category"] == "stats" for item in items):
        print("\n참고: 응답에 debug가 없습니다. CHAT_DEBUG=true로 API를 띄우면 생성 SQL과 시도 횟수가 보입니다.")
    summary = report(results, args.runs)
    out_dir = HERE / "results"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / f"{datetime.now().strftime('%Y-%m-%dT%H%M%S')}.json"
    out.write_text(json.dumps({"runs": args.runs, "summary": summary, "results": results},
                              ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"\n결과 저장: {out}")


if __name__ == "__main__":
    main()
