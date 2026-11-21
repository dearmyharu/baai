"""4~9월 원본 데이터는 그대로 두고 2026년 10월 데이터를 이어 붙인다.

방식
- 고객·상품·큐레이션의 잠재 성향은 원본 생성기와 같은 설정·시드로 다시 만든다(고객·상품 표가 원본과 같은지 확인).
- 9/30 시점 상태(등급, 월별 구매액, 마지막 방문, 탈퇴)는 원본 CSV에서 읽는다.
  (원본 4~9월은 이 환경에서 재실행하면 똑같이 재현되지 않으므로 상태를 데이터에서 이어받는다.)
- 10월 시뮬레이션은 별도 난수(seed + 1010)를 쓴다.
- 모의 프로모션 3건: 대상 카테고리 판매가 할인 + 노출·관심 증가(심은 효과). 결과는 '모의'다.

실행: python extend_october.py --gen <ecommerce_generation_blueprint 경로> --src <원본 CSV 폴더> --out <출력 폴더>
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

OCT_START = datetime(2026, 10, 1)
OCT_END = datetime(2026, 11, 1)
SEED_OFFSET = 1010

# 모의 프로모션. boost = 대상 카테고리 관심도(시즌 효과 항)에 더하는 값. 할인율은 판매가 기준.
PROMOTIONS = [
    {"promotion_id": "PR001", "promotion_name": "정육 5% 할인", "category": "정육", "discount_pct": 5,
     "start": date(2026, 10, 1), "end": date(2026, 10, 15), "boost": 0.35,
     "primary_metric": "정육 일평균 매출", "guard_metric": "정육 이익률",
     "stop_rule": "정육 이익률이 시작 전보다 8%p 넘게 떨어지면 중단"},
    {"promotion_id": "PR002", "promotion_name": "음료·커피 5% 할인", "category": "음료·커피", "discount_pct": 5,
     "start": date(2026, 10, 8), "end": date(2026, 10, 22), "boost": -0.12,
     "primary_metric": "음료·커피 일평균 매출", "guard_metric": "음료·커피 이익률",
     "stop_rule": "음료·커피 이익률이 시작 전보다 8%p 넘게 떨어지면 중단"},
    {"promotion_id": "PR003", "promotion_name": "캠핑·바비큐 20% 할인", "category": "캠핑·바비큐", "discount_pct": 20,
     "start": date(2026, 10, 15), "end": date(2026, 10, 29), "boost": 0.45,
     "primary_metric": "캠핑·바비큐 일평균 매출", "guard_metric": "캠핑·바비큐 이익률",
     "stop_rule": "캠핑·바비큐 이익률이 시작 전보다 8%p 넘게 떨어지면 중단"},
]
ALWAYS_ON_COUPONS = ["CP001", "CP002", "CP003", "CP005"]  # 4/1~10/1 상시 쿠폰 → 10월에도 유지


def read_src(src: Path, name: str) -> pd.DataFrame:
    return pd.read_csv(src / f"{name}.csv", encoding="utf-8-sig", dtype=str, keep_default_na=False)


def shift_id(s: str, prefix: str, width: int, off: int) -> str:
    return f"{prefix}{int(s[len(prefix):]) + off:0{width}d}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gen", required=True)
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    gen, src, out = Path(a.gen), Path(a.src), Path(a.out)
    sys.path.insert(0, str(gen))
    from src.generation.common import Period, load_config, month_key
    from src.generation.coupons import CouponBook, coupon_frame
    from src.generation.curation import build_curation
    from src.generation.customers import build_customers
    from src.generation.finalize import TABLE_COLUMNS, _fmt, finalize
    from src.generation.grades import GradeEngine
    from src.generation.products import build_products, product_frame
    from src.generation.simulate import Simulator

    cfg = load_config(str(gen / "config/scenario_config_v2.yaml"))
    seed = cfg["seed"]
    scale = cfg["scales"]["full"]
    period = Period.from_cfg(cfg)
    rng = np.random.default_rng(seed)

    # ---------------- 1) 잠재 성향 재구성 (원본과 같은 순서로 난수 사용)
    ps = build_products(cfg, scale, period, rng)
    cur = build_curation(cfg, period, ps, rng)
    theme_cat_w = {t: cfg["themes"][t]["categories"] for t in cur.theme_ids}
    cs = build_customers(cfg, scale, period, rng, cur.theme_ids, theme_cat_w, ps.cat_codes)

    T = {n: read_src(src, n) for n in TABLE_COLUMNS}
    pf = _fmt(product_frame(ps, cfg), TABLE_COLUMNS["product"], "%Y-%m-%d %H:%M:%S", "%Y-%m-%d").astype(str)
    assert pf.reset_index(drop=True).equals(T["product"].reset_index(drop=True)), "상품 표가 원본과 다름"
    static = ["customer_id", "signup_date", "signup_channel", "gender", "region"]
    cf = _fmt(cs.df, static, "%Y-%m-%d %H:%M:%S", "%Y-%m-%d").astype(str)
    assert cf.reset_index(drop=True).equals(T["customer"][static].reset_index(drop=True)), "고객 표가 원본과 다름"
    # 큐레이션 편성은 동점 정렬 차이로 일부가 다르게 나올 수 있음 → 원본 편성표를 그대로 사용
    pidx = {p: k for k, p in enumerate(ps.df["product_id"])}
    cpa = T["curation_product"]
    n_diff = int((cur.cp_df.astype(str).reset_index(drop=True) != cpa.reset_index(drop=True)).any(axis=1).sum())
    for t in cur.theme_ids:
        sub = cpa[cpa["theme_id"] == t]
        cur.products[t] = np.array([pidx[p] for p in sub["product_id"]])
        cur.ranks[t] = sub["display_rank"].astype(int).values
    print(f"재구성 확인: 상품·고객 표 원본과 같음 / 큐레이션 편성 {n_diff}행 차이 → 원본 편성 사용")

    n = cs.n
    cid = list(cs.df["customer_id"])
    cidx = {c: i for i, c in enumerate(cid)}
    off_days = (OCT_START - period.start).days  # 183
    D = (OCT_END - OCT_START).days

    # ---------------- 2) 9/30 상태를 원본 데이터에서 이어받기
    snap = T["customer_initial_snapshot"].set_index("customer_id").reindex(cid).fillna("")  # 신규 가입자는 스냅샷 없음
    cs.prior_visit_count = snap["prior_visit_count"].replace("", "0").astype(int).values
    cs.last_visit = [None if v == "" else date.fromisoformat(v) for v in snap["last_visit_date"]]

    ev0 = T["event_log"][["customer_id", "session_id", "event_time"]].copy()
    ev0["t"] = pd.to_datetime(ev0["event_time"])
    last_t = ev0.groupby("customer_id")["t"].max()
    n_ses = ev0.groupby("customer_id")["session_id"].nunique()

    status_sep = T["customer"].set_index("customer_id").reindex(cid)["account_status"].values
    withdrawn = status_sep == "WITHDRAWN"
    cs.withdraw_time = [datetime(2000, 1, 1) if w else None for w in withdrawn]

    ge = GradeEngine.__new__(GradeEngine)
    ge.th, ge.window, ge.cs = cfg["grade"]["thresholds_krw"], cfg["grade"]["window_months"], cs
    ge.signup = list(cs.df["signup_date"])
    ge.monthly = {}
    pm = T["customer_prior_monthly_sales"]
    for c, m, v in zip(pm["customer_id"], pm["sales_month"], pm["completed_purchase_amount"]):
        k = (cidx[c], month_key(date.fromisoformat(m)))
        ge.monthly[k] = ge.monthly.get(k, 0) + int(float(v))
    od0 = T["orders"]
    done = od0[od0["order_status"] == "COMPLETED"]
    for c, t, ia, cd in zip(done["customer_id"], done["order_time"], done["items_amount"], done["coupon_discount_amount"]):
        k = (cidx[c], month_key(datetime.fromisoformat(t)))
        ge.monthly[k] = ge.monthly.get(k, 0) + int(ia) - int(cd)
    gh0 = T["customer_grade_history"]
    ge.current = list(T["customer"].set_index("customer_id").reindex(cid)["membership_grade"])
    ge.rows, ge.open_row = [], [None] * n
    open_gh = {}  # i -> grade_history_id (열린 구간)
    for gid, c, g, f, to in zip(gh0["grade_history_id"], gh0["customer_id"], gh0["membership_grade"],
                                gh0["effective_from"], gh0["effective_to"]):
        if to == "":
            i = cidx[c]
            assert g == ge.current[i]
            ge.rows.append([i, g, datetime.fromisoformat(f), None])
            ge.open_row[i] = len(ge.rows) - 1
            open_gh[i] = gid
    n_open_rows = len(ge.rows)

    # ---------------- 3) 10월 설정·가격·큐레이션
    cfg2 = copy.deepcopy(cfg)
    cfg2["analysis_start"], cfg2["analysis_end_exclusive"] = OCT_START.isoformat(), OCT_END.isoformat()
    cfg2["scenarios"] = []
    cfg2["time"]["month_traffic"][10] = 0.98
    # 쿠폰 목록 위치 찾기
    def find_coupons(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if isinstance(v, list) and v and isinstance(v[0], dict) and "coupon_id" in v[0]:
                    return v
                r = find_coupons(v)
                if r is not None:
                    return r
        return None
    coupons = find_coupons(cfg2)
    for c in coupons:
        if c["coupon_id"] in ALWAYS_ON_COUPONS:
            c["end"] = "2026-11-01 00:00:00"
    period2 = Period(start=OCT_START, end=OCT_END, snapshot=period.snapshot,
                     prior_month_start=period.prior_month_start, prior_month_end=period.prior_month_end)

    ps2 = copy.copy(ps)
    last_list = ps.list_px[:, -1]
    last_sale = ps.sale_px[:, -1]
    ps2.list_px = np.repeat(last_list[:, None], D, axis=1)
    ps2.sale_px = np.repeat(last_sale[:, None], D, axis=1)
    ps2.avail_from_day = np.minimum(ps.avail_from_day - off_days, 0)
    names = {k: v["name"] for k, v in cfg["products"]["categories"].items()}
    code_of = {v: k for k, v in names.items()}
    promos = []
    for pr in PROMOTIONS:
        code = code_of[pr["category"]]
        ci = ps.cat_codes.index(code)
        s, e = (pr["start"] - OCT_START.date()).days, (pr["end"] - OCT_START.date()).days
        for p in np.where((ps.cat_idx == ci) & ps.on_sale)[0]:
            new = int(round(ps2.list_px[p, s] * (1 - pr["discount_pct"] / 100) / 100) * 100)
            ps2.sale_px[p, s:e] = np.minimum(ps2.sale_px[p, s:e], new)
        promos.append(dict(pr, ci=ci))

    cur2 = copy.copy(cur)
    cur2.start_day = {t: min(d - off_days, 0) for t, d in cur.start_day.items()}

    # ---------------- 4) 10월 방문 강도 (별도 난수)
    rng2 = np.random.default_rng(seed + SEED_OFFSET)
    tc, lat = cfg2["time"], cfg2["latent"]
    days = [period2.day(d) for d in range(D)]
    dow = np.array([d.weekday() for d in days])
    dowm = np.tile(np.array(tc["weekday_traffic"]), (n, 1))
    dowm[:, 5:] *= cs.weekend_pref[:, None]
    dowm = dowm / dowm.mean(1, keepdims=True)
    ar = np.zeros(D // 7 + 1)
    for k in range(1, len(ar)):
        ar[k] = tc["weekly_ar_rho"] * ar[k - 1] + rng2.normal(0, tc["weekly_ar_sd"])
    common = tc["month_traffic"][10] * np.exp(ar[np.arange(D) // 7]) * np.exp(rng2.normal(0, tc["daily_shock_sd"], D))
    drift = cs.month_drift[:, -1] * np.exp(rng2.normal(0, lat["monthly_activity_drift_sd"], n))
    R = cs.visit_raw[:, None] * dowm[:, dow] * common[None, :] * drift[:, None]
    since = (np.arange(D) + off_days)[None, :] - cs.signup_day_idx[:, None]
    R = np.where(since < 0, 0.0, R)
    boost = 1 + (lat["new_signup_onboarding_boost"] - 1) * np.exp(-np.maximum(since, 0) / lat["new_signup_onboarding_days"])
    R = np.where(cs.is_new[:, None] & (since >= 0), R * boost, R)
    R[cs.lapsed] *= cfg["customers"]["prior_history"]["lapsed_period_visit_multiplier"]
    R[cs.never_visited] *= 0.35
    R[withdrawn] = 0.0
    sep = ev0[(ev0["t"] >= "2026-09-01") & (ev0["t"] < "2026-10-01")]
    sep_daily = sep["session_id"].nunique() / 30
    R *= sep_daily * D * tc["month_traffic"][10] / tc["month_traffic"][9] / R.sum()
    counts = rng2.poisson(R)

    # ---------------- 5) 시뮬레이션
    cb = CouponBook(cfg2)

    class PromoSim(Simulator):
        def run_session(self, i, t):
            d = t.date()
            row = self.base_season[t.month].copy()
            for pr in promos:
                if pr["start"] <= d < pr["end"]:
                    row[pr["ci"]] += pr["boost"]
            self.season[t.month] = row
            return super().run_session(i, t)

    sim = PromoSim(cfg2, period2, cs, ps2, cur2, cb, ge, counts, rng2)
    sim.base_season = sim.season.copy()
    for c, t in last_t.items():
        i = cidx[c]
        sim.last_end[i] = t.to_pydatetime()
        sim.last_session_date[i] = t.date()
        sim.obs_sessions[i] = int(n_ses[c])
    ge.monthly_update(OCT_START.date())
    ge.updated_through = month_key(OCT_START)
    sim.run()
    print(f"10월 세션 {len(sim.sessions)} / 주문 {len(sim.orders)} / 이벤트 {len(sim.events)}")

    tables, _ = finalize(cfg2, period2, cs, ps2, cur2, sim, ge)

    # ---------------- 6) ID 이어 붙이기
    def offset(name, col, prefix):
        ids = T[name][col]
        return len(ids), int(ids.iloc[-1][len(prefix):]) if len(ids) else 0

    fmt = lambda df, name: _fmt(df, TABLE_COLUMNS[name], "%Y-%m-%d %H:%M:%S", "%Y-%m-%d")
    o_off = len(T["orders"]); s_off = T["event_log"]["session_id"].str[1:].astype(int).max()
    e_off = len(T["event_log"]); it_off = len(T["order_items"]); oc_off = len(T["order_coupon"])
    for name, col, prefix in [("orders", "order_id", "O"), ("order_items", "order_item_id", "OI"),
                              ("order_coupon", "order_coupon_id", "OC"), ("event_log", "event_id", "E")]:
        assert T[name][col].iloc[-1] == f"{prefix}{len(T[name]):0{len(T[name][col].iloc[-1]) - len(prefix)}d}", f"{name} ID가 연속이 아님"

    new = {}
    od = fmt(tables["orders"], "orders").copy()
    od["order_id"] = [shift_id(x, "O", 6, o_off) for x in od["order_id"]]
    new["orders"] = od
    it = fmt(tables["order_items"], "order_items").copy()
    it["order_item_id"] = [shift_id(x, "OI", 7, it_off) for x in it["order_item_id"]]
    it["order_id"] = [shift_id(x, "O", 6, o_off) for x in it["order_id"]]
    new["order_items"] = it
    oc = fmt(tables["order_coupon"], "order_coupon").copy()
    oc["order_coupon_id"] = [shift_id(x, "OC", 6, oc_off) for x in oc["order_coupon_id"]]
    oc["order_id"] = [shift_id(x, "O", 6, o_off) for x in oc["order_id"]]
    new["order_coupon"] = oc
    ev = fmt(tables["event_log"], "event_log").copy()
    ev["event_id"] = [shift_id(x, "E", 7, e_off) for x in ev["event_id"]]
    ev["session_id"] = [shift_id(x, "S", 7, s_off) for x in ev["session_id"]]
    ev["order_id"] = ["" if x is None or pd.isna(x) else shift_id(x, "O", 6, o_off) for x in ev["order_id"]]
    ev["position"] = ["" if v is None or pd.isna(v) else str(int(v)) for v in ev["position"]]
    for c in ("theme_id", "product_id"):
        ev[c] = ["" if v is None or pd.isna(v) else str(v) for v in ev[c]]
    new["event_log"] = ev

    # 등급 이력: 열린 구간 닫기 + 새 구간 추가 (기존 ID 유지)
    gh = T["customer_grade_history"].copy()
    gid_pos = {g: k for k, g in enumerate(gh["grade_history_id"])}
    gh_n = len(gh)
    add_rows = []
    for r_i, (i, g, f, to) in enumerate(ge.rows):
        if r_i < n_open_rows:
            if to is not None:
                gh.at[gid_pos[open_gh[i]], "effective_to"] = to.strftime("%Y-%m-%d %H:%M:%S")
        else:
            gh_n += 1
            add_rows.append({"grade_history_id": f"GH{gh_n:06d}", "customer_id": cid[i], "membership_grade": g,
                             "effective_from": f.strftime("%Y-%m-%d %H:%M:%S"),
                             "effective_to": "" if to is None else to.strftime("%Y-%m-%d %H:%M:%S")})
    gh = pd.concat([gh, pd.DataFrame(add_rows)], ignore_index=True)

    # 고객 현재 상태 (10/31 기준)
    cust = T["customer"].copy()
    fin = tables["customer"].set_index("customer_id").reindex(cust["customer_id"])
    cust["membership_grade"] = list(fin["membership_grade"])
    cust["account_status"] = np.where(cust["account_status"] == "WITHDRAWN", "WITHDRAWN", fin["account_status"].values)

    # 가격 이력: 10월 할인 구간 추가
    ph = T["product_price_history"].copy()
    ph_n = len(ph)
    open_ph = {p: k for k, (p, to) in enumerate(zip(ph["product_id"], ph["effective_to"])) if to == ""}
    add_ph = []
    for p in range(len(ps.df)):
        pid = ps.df.at[p, "product_id"]
        if pid not in open_ph:
            continue
        segs, s = [], 0
        for d in range(1, D + 1):
            if d == D or ps2.sale_px[p, d] != ps2.sale_px[p, s] or ps2.list_px[p, d] != ps2.list_px[p, s]:
                segs.append((s, d)); s = d
        if len(segs) == 1:
            continue
        k0 = open_ph[pid]
        prev = k0
        for j, (s, e) in enumerate(segs):
            if j == 0:
                ph.at[k0, "effective_to"] = (OCT_START + timedelta(days=e)).strftime("%Y-%m-%d %H:%M:%S")
                continue
            ph_n += 1
            add_ph.append({"price_history_id": f"PH{ph_n:05d}", "product_id": pid,
                           "list_price": str(int(ps2.list_px[p, s])), "sale_price": str(int(ps2.sale_px[p, s])),
                           "effective_from": (OCT_START + timedelta(days=s)).strftime("%Y-%m-%d %H:%M:%S"),
                           "effective_to": "" if j == len(segs) - 1 else (OCT_START + timedelta(days=e)).strftime("%Y-%m-%d %H:%M:%S")})
    ph = pd.concat([ph, pd.DataFrame(add_ph)], ignore_index=True)

    # 쿠폰·테마 기간 연장
    cp = T["coupon"].copy()
    cp.loc[cp["coupon_id"].isin(ALWAYS_ON_COUPONS), "end_date"] = "2026-11-01 00:00:00"
    th = T["curation_theme"].copy()
    th.loc[th["end_date"] == "2026-09-30", "end_date"] = "2026-10-31"

    # ---------------- 7) 저장
    out.mkdir(parents=True, exist_ok=True)
    final = dict(T)
    for name in ("orders", "order_items", "order_coupon", "event_log"):
        final[name] = pd.concat([T[name], new[name].astype(object).where(new[name].notna(), "")], ignore_index=True)
    final.update({"customer": cust, "customer_grade_history": gh, "product_price_history": ph,
                  "coupon": cp, "curation_theme": th})
    counts_out = {}
    for name, cols in TABLE_COLUMNS.items():
        df = final[name][cols].fillna("")
        df.to_csv(out / f"{name}.csv", index=False, encoding="utf-8-sig", lineterminator="\r\n")
        counts_out[name] = len(df)
    promo = pd.DataFrame([{k: (v.isoformat() if isinstance(v, date) else v) for k, v in pr.items()
                           if k not in ("boost",)} for pr in PROMOTIONS])
    promo = promo.rename(columns={"start": "start_date", "end": "end_date"})
    promo["end_date"] = [(date.fromisoformat(x) - timedelta(days=1)).isoformat() for x in promo["end_date"]]
    promo["lever"] = "price"
    promo["status"] = "RUNNING"
    promo["is_simulated"] = "TRUE"
    promo = promo[["promotion_id", "promotion_name", "category", "lever", "discount_pct", "start_date", "end_date",
                   "primary_metric", "guard_metric", "stop_rule", "status", "is_simulated"]]
    promo.to_csv(out / "promotion.csv", index=False, encoding="utf-8-sig", lineterminator="\r\n")
    counts_out["promotion"] = len(promo)
    manifest = {
        "source": str(src), "base_seed": seed, "october_seed": seed + SEED_OFFSET,
        "analysis_period": ["2026-04-01T00:00:00", "2026-11-01T00:00:00"],
        "october_appended": True, "generated_at": datetime.now().isoformat(timespec="seconds"),
        "row_counts": counts_out,
        "note": "4~9월 행은 원본과 동일. 10월은 9/30 상태를 이어받아 별도 난수로 생성. 프로모션 효과는 모의로 심은 것.",
    }
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print("저장 완료", counts_out)


if __name__ == "__main__":
    main()
