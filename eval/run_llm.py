"""AI 분석가(Gemini) 평가: 평가셋 36문항을 실제로 물어보고 채점한다.

dashboard 폴더에서:  python eval/run_llm.py   (또는 eval_llm.bat 더블클릭)
키: .streamlit/secrets.toml 또는 환경변수 GEMINI_API_KEY
결과: eval/llm_results.md (사람이 읽는 표), eval/llm_results.json

채점 기준
- 숫자 질문(check_tools.py에 검사가 있는 22문항): 기대 도구를 불렀고, 그 결과가 정답과 같으면 정답
- 그 밖의 지원 질문: 기대 도구를 불렀으면 정답(답변 내용은 사람이 확인)
- 미지원·범위 밖 질문(9문항): 지원하지 않거나 데이터에 없다고 밝혔으면 정답
- 20번(함정): 위 조건 + 매출이 늘었다는 사실을 답변에서 바로잡아야 정답
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from core import llm  # noqa: E402
from core import tools as T  # noqa: E402
from core.data import build_all  # noqa: E402
from eval.cases import CASES, OUT_OF_SCOPE  # noqa: E402
from eval.check_tools import CHECKS  # noqa: E402

UNSUPPORTED = {16, 17, 26}
REFUSE_CUES = ("없습니다", "없어", "지원하지", "제공하지", "제공되지", "존재하지", "확인할 수 없", "알 수 없", "포함되어 있지",
               "포함되지", "수집되지", "어렵습니다", "불가")
LEAK_RE = re.compile(r"규칙 ?\d+번|지시문|분석 지침|get_[a-z_]+|rank_items|detect_changes|design_experiment|"
                     r"find_potential_products|segment_preference|segment_repeat|explain_revenue_change")
EXPECTED_TOOLS = {12: {"get_retention"}, 27: {"get_themes"},
                  28: {"get_funnel"}, 29: {"get_segments"}, 30: {"design_experiment"}}


def load_key() -> str:
    k = os.getenv("GEMINI_API_KEY", "")
    f = ROOT / ".streamlit" / "secrets.toml"
    if not k and f.exists():
        m = re.search(r'^\s*GEMINI_API_KEY\s*=\s*"([^"]*)"', f.read_text(encoding="utf-8"), re.M)
        k = m.group(1) if m else ""
    if not k or "붙여넣기" in k:
        sys.exit("GEMINI_API_KEY를 찾지 못했습니다. .streamlit/secrets.toml을 확인해 주세요.")
    return k.strip()


def grade(qid, exp, r) -> tuple[bool, str]:
    calls = r["calls"]
    used = [c["tool"] for c in calls]
    text = r["text"]
    leak = sorted(set(LEAK_RE.findall(text)))
    if leak:
        return False, f"내부 지시문·도구 이름 노출: {', '.join(leak)}"
    if qid in UNSUPPORTED or str(qid).startswith("X"):
        ok = any(c in text for c in REFUSE_CUES)
        return ok, "범위 밖·미지원을 밝힘" if ok else "범위 밖인데 그렇다고 말하지 않음"
    if qid in CHECKS:
        tool, _, fn = CHECKS[qid]
        tried = [c for c in calls if c["tool"] == tool and "result" in c]
        if not tried:
            return False, f"기대 도구 {tool} 미사용 (사용: {', '.join(used) or '없음'})"
        whys = [fn(c["result"], exp) for c in tried]
        if all(w is not None for w in whys):
            return False, f"{tool} 결과 불일치({whys[0]}) - 기간 해석 확인: {tried[0]['params']}"
        if qid == 20 and not any(w in text for w in ("늘", "증가", "올랐", "상승")):
            return False, "매출이 늘었다는 사실을 바로잡지 않음"
        return True, "숫자 일치"
    want = EXPECTED_TOOLS.get(qid, set())
    ok = bool(want & set(used))
    return ok, "기대 도구 사용(내용은 사람 확인)" if ok else f"기대 도구 {'/'.join(sorted(want))} 미사용 (사용: {', '.join(used) or '없음'})"


def main(delay: float = 7.0):
    key = load_key()
    m = build_all()
    print(f"시작 모델: {llm.pick_model(key)} (거절되면 자동 교체)\n")
    exp = {c["id"]: c["expected"](m) for c in CASES}
    qs = [(c["id"], c["level"], c["q"]) for c in CASES] + [(x["id"], "범위 밖", x["q"]) for x in OUT_OF_SCOPE]
    rows = []
    for qid, level, q in qs:
        t0 = time.time()
        for attempt in range(3):
            try:
                r = llm.ask(key, q, lambda name, p: T.run(m, name, **p))   # 교체된 모델을 이어서 쓴다
                ok, why = grade(qid, exp.get(qid), r)
                break
            except llm.LLMError as e:
                r, ok, why = {"text": "", "calls": []}, False, f"API 오류: {e}"
                if e.code != 429:
                    break
                print(f"  (사용량 한도 - 30초 기다렸다 다시 시도)")
                time.sleep(30)
        rows.append({"id": qid, "level": level, "q": q, "ok": ok, "why": why, "answer": r["text"],
                     "calls": [{"tool": c["tool"], "params": c["params"], "error": c.get("error")} for c in r["calls"]],
                     "sec": round(time.time() - t0, 1)})
        print(f"{'O' if ok else 'X'} #{qid:<3} {why}")
        time.sleep(delay)

    n_ok = sum(r["ok"] for r in rows)
    by = {}
    for r in rows:
        by.setdefault(r["level"], [0, 0])
        by[r["level"]][0] += r["ok"]
        by[r["level"]][1] += 1
    summary = " · ".join(f"{k} {a}/{b}" for k, (a, b) in by.items())
    model = llm.pick_model(key)
    print(f"\n정답 {n_ok}/{len(rows)} ({summary})")
    (HERE / "llm_results.json").write_text(json.dumps({"model": model, "rows": rows}, ensure_ascii=False, indent=1),
                                           encoding="utf-8")
    md = [f"# AI 분석가 평가 결과", "", f"모델 `{model}` · 정답 **{n_ok}/{len(rows)}** ({summary})", "",
          "| # | 레벨 | 질문 | 판정 | 사유 | 사용한 도구 | 답변 (앞부분) |", "| --- | --- | --- | --- | --- | --- | --- |"]
    for r in rows:
        tools_ = "; ".join(f"{c['tool']}{json.dumps(c['params'], ensure_ascii=False)}" for c in r["calls"]) or "-"
        ans = r["answer"].replace("\n", " ").replace("|", "/")[:160]
        md.append(f"| {r['id']} | {r['level']} | {r['q']} | {'O' if r['ok'] else 'X'} | {r['why']} | {tools_} | {ans} |")
    (HERE / "llm_results.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("→ eval/llm_results.md 저장")


if __name__ == "__main__":
    main(float(sys.argv[1]) if len(sys.argv) > 1 else 7.0)
