"""ver.2 계산 엔진 확인: 이전 버전 평가셋 정답(4~9월 원본 데이터로 계산)과 같은 숫자가 나오는지.

실행: python tests/check_engine.py   (dashboard_v2 폴더에서)
- 4~9월 행은 원본과 같으므로, 기간을 4~9월로 정한 질문은 정답이 같아야 한다.
- '현재 등급'을 쓰는 질문은 10/31 기준 등급으로 바뀌어 달라질 수 있다(예상된 차이).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import engine  # noqa: E402
from engine import metrics  # noqa: E402

sys.modules["core"] = engine            # 이전 평가셋 코드가 'from core import metrics' 를 쓰므로
sys.modules["core.metrics"] = metrics
from engine.data import build_all  # noqa: E402

sys.path.insert(0, str(ROOT / "tests" / "legacy"))
from cases import CASES  # noqa: E402


def same(a, b):
    if isinstance(a, float) or isinstance(b, float):
        try:
            return abs(float(a) - float(b)) <= 1e-6 * max(1.0, abs(float(b)))
        except (TypeError, ValueError):
            return a == b
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(same(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
    return a == b


def main():
    m = build_all()
    old = {r["id"]: r for r in json.loads((ROOT / "tests/legacy/answers.json").read_text(encoding="utf-8"))}
    ok = bad = 0
    for c in CASES:
        got = json.loads(json.dumps(c["expected"](m), ensure_ascii=False, default=str))
        if c["id"] not in old:
            print(f"[정답 없음] {c['id']} {c['q']} (이전 answers.json에 없는 문항)")
            continue
        exp = old[c["id"]]["expected"]
        if same(got, exp):
            ok += 1
        else:
            bad += 1
            print(f"[다름] {c['id']} {c['q']}\n   이전: {json.dumps(exp, ensure_ascii=False)[:160]}\n   지금: {json.dumps(got, ensure_ascii=False)[:160]}")
    print(f"같음 {ok} / 다름 {bad} (전체 {len(CASES)})")


if __name__ == "__main__":
    main()
