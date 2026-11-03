"""AI 분석가(GPT 또는 Gemini) 평가: 평가셋 문항을 실제로 물어보고 채점한다.

dashboard 폴더에서
  python eval/run_llm.py                          기본 36문항 (eval_llm.bat)
  python eval/run_llm.py --set holdout --repeat 3 처음 보는 질문 28문항을 3번 (eval_holdout.bat)
키: .streamlit/secrets.toml 또는 환경변수 OPENAI_API_KEY (없으면 GEMINI_API_KEY)
결과: eval/llm_results[_holdout].md (사람이 읽는 표), .json

엄격 확인(점수와 별도): 답변 문장 속 숫자(원·%·건·명 등)가 도구 결과에 있는지 대조해 '근거 없는 숫자'를 표시한다.

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
from eval import holdout as H  # noqa: E402
from eval import holdout2 as H2  # noqa: E402

CLARIFY = {x["id"] for x in OUT_OF_SCOPE if x.get("clarify")}
UNSUPPORTED = {17, 26}      # 16(연령·성별·지역)은 2026-11-03 고객 조건 필터로 지원
REFUSE_CUES = ("없습니다", "없어", "지원하지", "지원되지", "미지원", "제공하지", "제공되지", "존재하지", "확인할 수 없", "알 수 없",
               "포함되어 있지", "포함되지", "수집되지", "어렵습니다", "불가")
LEAK_RE = re.compile(r"규칙 ?\d+번|지시문|분석 지침|get_[a-z_]+|rank_items|detect_changes|design_experiment|"
                     r"find_potential_products|segment_preference|segment_repeat|explain_revenue_change")
EXPECTED_TOOLS = {12: {"get_retention"}, 27: {"get_themes"},
                  28: {"get_funnel"}, 29: {"get_segments"}, 30: {"design_experiment"}}


def load_key() -> str:
    """OPENAI_API_KEY가 있으면 GPT, 없으면 GEMINI_API_KEY (환경변수 → .streamlit/secrets.toml 순)."""
    f = ROOT / ".streamlit" / "secrets.toml"
    text = f.read_text(encoding="utf-8") if f.exists() else ""
    for name in ("OPENAI_API_KEY", "GEMINI_API_KEY"):
        k = os.getenv(name, "")
        if not k:
            m = re.search(rf'^\s*{name}\s*=\s*"([^"]*)"', text, re.M)
            k = m.group(1) if m else ""
        if k and "붙여넣기" not in k:
            for mn in ("OPENAI_MODEL", "GEMINI_MODEL"):     # secrets.toml의 모델 고정도 반영
                mm = re.search(rf'^\s*{mn}\s*=\s*"([^"]*)"', text, re.M)
                if mm and not os.getenv(mn):
                    os.environ[mn] = mm.group(1)
            return k.strip()
    sys.exit("OPENAI_API_KEY(또는 GEMINI_API_KEY)를 찾지 못했습니다. .streamlit/secrets.toml을 확인해 주세요.")


def grade(qid, exp, r) -> tuple[bool, str]:
    calls = r["calls"]
    used = [c["tool"] for c in calls]
    text = r["text"]
    leak = sorted(set(LEAK_RE.findall(text)))
    if leak:
        return False, f"내부 지시문·도구 이름 노출: {', '.join(leak)}"
    if qid in CLARIFY:
        ok = bool(r.get("clarify"))
        return ok, "애매한 기간을 되물음" if ok else "애매한 기간인데 추측해서 답함"
    if qid in UNSUPPORTED or str(qid).startswith("X"):
        ok = any(c in text for c in REFUSE_CUES)
        return ok, "범위 밖·미지원을 밝힘" if ok else "범위 밖인데 그렇다고 말하지 않음"
    if qid == 16:
        ok = any((c["params"] or {}).get("filters") for c in calls if "result" in c)
        return ok, "고객 조건으로 나눠 봄(내용은 사람 확인)" if ok else "고객 조건(filters)을 쓰지 않음"
    if qid == 20 and not any(c["tool"] == "explain_revenue_change" for c in calls):
        # 매출 분해 대신 핵심 지표로 답해도, 최근 2주 매출이 늘었다는 사실을 바로잡으면 정답
        k = [c for c in calls if c["tool"] == "get_kpis" and "result" in c and c["result"]["period"].startswith("2026-09-17")]
        up = exp["매출 변화"] >= 0
        if k and any(T.won(exp["최근 2주 매출"]) in " ".join(c["result"]["facts"]) for c in k) \
                and any(w in text for w in (("늘", "증가", "올랐", "상승") if up else ("줄", "감소", "하락"))):
            return True, "숫자 일치(핵심 지표로 전제 바로잡음)"
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


HYPO_CUES = ("가설", "확정할 수 없", "단정", "알 수 없", "추정", "확인할 수 없", "데이터만으로는", "직접 알 수", "알기 어렵")


def grade_holdout(c, exp, r) -> tuple[bool, str]:
    ok, why = _grade_holdout(c, exp, r)
    if ok and c.get("text_fn"):
        need = c["text_fn"](exp)
        if not any(w in r["text"] for w in need):
            return False, f"답변에 필요한 표현 없음(예: {', '.join(w for w in need if w)[:40]})"
    return ok, why


def _grade_holdout(c, exp, r) -> tuple[bool, str]:
    calls, text = r["calls"], r["text"]
    used = [x["tool"] for x in calls]
    leak = sorted(set(LEAK_RE.findall(text)))
    if leak:
        return False, f"내부 지시문·도구 이름 노출: {', '.join(leak)}"
    if c["kind"] == "clarify":
        ok = bool(r.get("clarify"))
        return ok, "애매한 기간을 되물음" if ok else "애매한 기간인데 추측해서 답함"
    if c["kind"] == "hypo":
        ok = any(x in text for x in HYPO_CUES + REFUSE_CUES)
        return ok, "확정할 수 없음·가설임을 밝힘" if ok else "원인을 단정함(가설·한계 표시 없음)"
    if c["kind"] == "refuse":
        ok = any(x in text for x in REFUSE_CUES)
        return ok, "범위 밖·미지원을 밝힘" if ok else "범위 밖인데 그렇다고 말하지 않음"
    if c["kind"] == "tool":
        ok = bool(c["tools"] & set(used))
        return ok, "기대 도구 사용(내용은 사람 확인)" if ok else f"기대 도구 {'/'.join(sorted(c['tools']))} 미사용 (사용: {', '.join(used) or '없음'})"
    whys = []
    for tool, _ in c["checks"]:
        fn = H.check_fn(c, tool)
        for x in calls:
            if x["tool"] == tool and "result" in x:
                w = fn(x["result"], exp)
                if w is None:
                    return True, "숫자 일치"
                whys.append(f"{tool}: {w} {x['params']}")
    if not whys:
        want = "/".join(t for t, _ in c["checks"])
        return False, f"기대 도구 {want} 미사용 (사용: {', '.join(used) or '없음'})"
    return False, " | ".join(whys)[:200]


# ---------------------------------------------------------------------------
# 엄격 확인: 답변 속 숫자가 도구 결과에 있는가
# ---------------------------------------------------------------------------
def unsupported_numbers(r) -> list[str]:
    """답변 속 숫자 중 도구 결과에 없는 것 (llm.unsupported_in_answer: 앱 화면 경고와 같은 기준)."""
    return llm.unsupported_in_answer(r["text"], r["calls"])


# ---------------------------------------------------------------------------
# 실행
# ---------------------------------------------------------------------------
def questions(which, m):
    out = []
    if which in ("main", "all"):
        exp = {c["id"]: c["expected"](m) for c in CASES}
        out += [(c["id"], c["level"], c["q"], (lambda r, qid=c["id"]: grade(qid, exp.get(qid), r))) for c in CASES]
        out += [(x["id"], "범위 밖", x["q"], (lambda r, qid=x["id"]: grade(qid, None, r))) for x in OUT_OF_SCOPE]
    sets = {"holdout": H.ALL_CASES, "holdout2": H2.ALL_CASES}
    for name, cases in sets.items():
        if which not in (name, "all"):
            continue
        for c in cases:
            e = c["expected"](m) if c["kind"] == "check" else None
            out.append((c["id"], c["level"], c["q"], (lambda r, c=c, e=e: grade_holdout(c, e, r))))
    return out


def run_once(key, m, qs, delay):
    rows, total = [], llm.new_usage()
    for qid, level, q, grader in qs:
        t0 = time.time()
        for attempt in range(3):
            try:
                r = llm.ask(key, q, lambda name, p: T.run(m, name, **p))   # 교체된 모델을 이어서 쓴다
                ok, why = grader(r)
                break
            except llm.LLMError as e:
                r, ok, why = {"text": "", "calls": []}, False, f"API 오류: {e}"
                if e.code != 429:
                    break
                print("  (사용량 한도 - 30초 기다렸다 다시 시도)")
                time.sleep(30)
        u = r.get("usage") or llm.new_usage()
        for k in total:
            total[k] += u[k]
        loose = unsupported_numbers(r)
        rows.append({"id": qid, "level": level, "q": q, "ok": ok, "why": why, "answer": r["text"], "usage": u,
                     "unsupported_numbers": loose,
                     "calls": [{"tool": c["tool"], "params": c["params"], "error": c.get("error")} for c in r["calls"]],
                     "sec": round(time.time() - t0, 1)})
        print(f"{'O' if ok else 'X'} #{qid:<4} {why}" + (f"   [근거 없는 숫자: {', '.join(loose)}]" if loose else ""))
        time.sleep(delay)
    return rows, total


def summarize_run(rows):
    by = {}
    for r in rows:
        by.setdefault(r["level"], [0, 0])
        by[r["level"]][0] += r["ok"]
        by[r["level"]][1] += 1
    return sum(r["ok"] for r in rows), " · ".join(f"{k} {a}/{b}" for k, (a, b) in by.items())


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", default="main", choices=["main", "holdout", "holdout2", "all"])
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--delay", type=float, default=None)
    a = ap.parse_args()

    key = load_key()
    delay = a.delay if a.delay is not None else (1.0 if llm.provider(key) == "openai" else 7.0)  # Gemini 무료 등급은 분당 한도가 낮음
    m = build_all()
    print(f"시작 모델: {llm.pick_model(key)} ({llm.provider(key)}, 거절되면 자동 교체) · 문항 세트: {a.set} · {a.repeat}회\n")
    qs = questions(a.set, m)
    runs, total = [], llm.new_usage()
    for i in range(a.repeat):
        if a.repeat > 1:
            print(f"--- {i + 1}회차 ---")
        rows, u = run_once(key, m, qs, delay)
        for k in total:
            total[k] += u[k]
        n_ok, summary = summarize_run(rows)
        n_num = sum(1 for r in rows if r["unsupported_numbers"])
        print(f"{i + 1}회차 정답 {n_ok}/{len(rows)} ({summary}) · 근거 없는 숫자가 나온 답변 {n_num}개\n")
        runs.append({"rows": rows, "ok": n_ok, "summary": summary, "unsupported": n_num})

    model = llm.pick_model(key)
    use = llm.usage_label(model, total) or "토큰 정보 없음"
    n = len(qs)
    scores = [r["ok"] for r in runs]
    per_q = {}
    for run in runs:
        for r in run["rows"]:
            per_q.setdefault(r["id"], []).append(r)
    unstable = [qid for qid, rs in per_q.items() if 0 < sum(x["ok"] for x in rs) < len(rs)]
    always_bad = [qid for qid, rs in per_q.items() if not any(x["ok"] for x in rs)]
    secs = [r["sec"] for run in runs for r in run["rows"]]
    print("=" * 60)
    print(f"정답 {' / '.join(str(s) for s in scores)} (각 {n}문항) · 평균 {sum(scores) / len(scores):.1f}/{n}")
    if a.repeat > 1:
        print(f"회차마다 결과가 달라진 문항: {', '.join(map(str, unstable)) or '없음'}")
    print(f"매번 틀린 문항: {', '.join(map(str, always_bad)) or '없음'}")
    print(f"사용량: {use} · 문항당 평균 {sum(secs) / max(len(secs), 1):.1f}초")

    suffix = "" if a.set == "main" else f"_{a.set}"
    (HERE / f"llm_results{suffix}.json").write_text(
        json.dumps({"model": model, "set": a.set, "usage": total, "scores": scores, "runs": runs},
                   ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    md = [f"# AI 분석가 평가 결과 ({a.set})", "", f"모델 `{model}` · 정답 **{' / '.join(map(str, scores))}** (각 {n}문항, {a.repeat}회)",
          "", f"사용량: {use}", ""]
    if a.repeat > 1:
        md += [f"회차마다 달라진 문항: {', '.join(map(str, unstable)) or '없음'} · 매번 틀린 문항: {', '.join(map(str, always_bad)) or '없음'}", ""]
    md += ["| # | 레벨 | 질문 | 정답 횟수 | 사유(마지막 회차) | 근거 없는 숫자 | 사용한 도구 | 답변 (앞부분) |",
           "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for qid, rs in per_q.items():
        r = rs[-1]
        tools_ = "; ".join(f"{c['tool']}{json.dumps(c['params'], ensure_ascii=False)}" for c in r["calls"]) or "-"
        ans = r["answer"].replace("\n", " ").replace("|", "/")[:160]
        md.append(f"| {qid} | {r['level']} | {r['q']} | {sum(x['ok'] for x in rs)}/{len(rs)} | {r['why']} | "
                  f"{', '.join(r['unsupported_numbers']) or '-'} | {tools_} | {ans} |")
    (HERE / f"llm_results{suffix}.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"→ eval/llm_results{suffix}.md 저장")


if __name__ == "__main__":
    main()
