"""질문 해석 평가 실행 (실제 GPT). DATA_BACKEND=csv python eval_v2/run_parse.py [--repeat N]"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine import ai, data as D, interpret as I, validate as V  # noqa: E402
from engine.data import as_of, build_all  # noqa: E402
from eval_v2 import holdout_cases, parse_cases  # noqa: E402


def grade(d: V.Decision, exp: dict) -> list[str]:
    bad = []
    kinds = exp["kind"] if isinstance(exp["kind"], set) else {exp["kind"]}
    if d.kind not in kinds:
        return [f"kind {d.kind} (기대 {exp['kind']})"]
    if d.kind != "query":
        return bad
    q = d.query
    for k in ("intent", "category", "product", "measure", "n"):
        if k in exp and getattr(q, k) != exp[k]:
            bad.append(f"{k}={getattr(q, k)} (기대 {exp[k]})")
    if "axis" in exp:
        ok = q.axis in exp["axis"] if isinstance(exp["axis"], set) else q.axis == exp["axis"]
        if not ok:
            bad.append(f"axis={q.axis} (기대 {exp['axis']})")
    if "filters" in exp and q.filters != exp["filters"]:
        bad.append(f"filters={q.filters} (기대 {exp['filters']})")
    if "period" in exp and q.period != exp["period"]:
        bad.append(f"period={q.period} (기대 {exp['period']})")
    if "why" in exp and d.why != exp["why"]:
        bad.append(f"why={d.why}")
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--set", default="tune", choices=["tune", "holdout"])
    args = ap.parse_args()
    D.set_cutoff(D.TODAY)
    m = as_of(build_all(), D.TODAY)
    prod = m["raw"]["product"][["product_name", "category"]]
    cats = sorted(prod["category"].unique())
    key = ai.api_key()
    src = parse_cases if args.set == "tune" else holdout_cases
    items = [(cid, None, q, e) for cid, q, e in src.CASES] + list(src.FOLLOW)
    total = passed = 0
    usage = {"input": 0, "output": 0}
    model = ""
    fails = []
    t0 = time.time()
    for rep in range(args.repeat):
        for cid, prev, q, exp in items:
            pre = V.out_of_data(q)
            if pre:
                d, draft = pre, None
            else:
                draft, model, u = I.draft(key, q, cats, prev)
                usage = {k: usage[k] + u[k] for k in usage}
                d = V.validate(q, draft, D.TODAY, prod, prev)
            bad = grade(d, exp)
            total += 1
            passed += not bad
            mark = "O" if not bad else "X"
            print(f"{mark} {cid} {q}  → {d.kind}" + (f" {d.query.intent} cat={d.query.category} axis={d.query.axis} "
                                                     f"f={d.query.filters} why={d.why}" if d.query else f" {d.text[:50]}")
                  + ("" if not bad else f"   ✗ {'; '.join(bad)}"))
            if bad:
                fails.append((cid, q, bad, json.dumps(draft, ensure_ascii=False)[:400] if draft else "(AI 호출 안 함)"))
    print(f"\n정답 {passed}/{total} ({passed / total:.0%}) · 모델 {model} · 토큰 입력 {usage['input']:,} 출력 {usage['output']:,}"
          f" · {time.time() - t0:.0f}초")
    for f in fails:
        print("\n", f[0], f[1], f[2], "\n   초안:", f[3])


if __name__ == "__main__":
    main()
