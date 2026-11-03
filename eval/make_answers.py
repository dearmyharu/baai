"""평가셋 정답 만들기.

dashboard 폴더에서:  python eval/make_answers.py
→ eval/answers.json (챗봇 자동 채점용), eval/answers.md (사람이 보는 표)
데이터가 바뀌면 다시 실행한다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from core.data import build_all  # noqa: E402
from eval.cases import CASES, OUT_OF_SCOPE  # noqa: E402


def short(v, limit=220) -> str:
    s = json.dumps(v, ensure_ascii=False)
    return s if len(s) <= limit else s[:limit] + "…"


def main(data_dir=None):
    m = build_all(data_dir)
    out = []
    for c in CASES:
        out.append({k: c[k] for k in ("id", "level", "q", "period", "tool", "check")} | {"expected": c["expected"](m)})
    for x in OUT_OF_SCOPE:
        out.append({"id": x["id"], "level": "범위 밖", "q": x["q"], "period": "-", "tool": "(없음)",
                    "check": "범위 밖 처리: 데이터에 없다고 밝히고 대체 지표를 제시해야 정답. 숫자를 지어내면 오답",
                    "expected": {"없는 데이터": x["missing"], "대체": x["alternative"]}})
    (HERE / "answers.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    lines = ["# 챗봇 평가셋 정답", "",
             "`python eval/make_answers.py`로 생성. 기간 규칙: 데이터 마지막 날 2026-09-30 기준, "
             "오늘=9/30(수), 이번 달=9월, 지난달=8월, 이번 주=9/28~9/30(달력 주, 비교 9/21~9/23), 최근 2주=9/17~9/30, "
             "비교=직전 같은 길이(달 단위는 직전 달).", "",
             "| # | 레벨 | 질문 | 기준 기간 | 도구 | 정답 (요약) |", "| --- | --- | --- | --- | --- | --- |"]
    for r in out:
        lines.append(f"| {r['id']} | {r['level']} | {r['q']} | {r['period']} | {r['tool']} | "
                     f"{short(r['expected']).replace('|', '/')} |")
    lines += ["", "## 채점 방법", ""]
    for r in out:
        lines.append(f"- **{r['id']}** {r['check']}")
    (HERE / "answers.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{len(out)}개 질문 정답 생성 → eval/answers.json, eval/answers.md")
    return out


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
