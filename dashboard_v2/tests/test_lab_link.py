"""AI 분석가 ↔ Growth Lab 연결 시험. 실행: DATA_BACKEND=csv python tests/test_lab_link.py

1) lab_link 순수 함수  2) 화면 시험(AppTest): 챗봇 넘김 → 입력칸 채움, Growth Lab → 챗봇 요약 카드
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DATA_BACKEND", "csv")

from engine import lab_link as LL  # noqa: E402

ok = n = 0


def check(name, cond, d=None):
    global ok, n
    n += 1
    ok += bool(cond)
    print(("OK  " if cond else "FAIL") + " " + name + ("" if cond or d is None else f"  → {d}"))


CATS = ["과일", "정육", "채소"]
REQ = {"type": "plan", "target": {"type": "category", "value": "정육"}, "lever": {"policy": "price", "value": -10}}

# ---- 1) 순수 함수 -----------------------------------------------------------
s, notes = LL.planner_state(REQ, CATS)
check("판매가: 음수 요청 → 할인율 양수", s.get("gl_price_pct") == 10.0 and s.get("gl_policy") == "price", s)
check("카테고리 채움", s.get("gl_cat") == "정육" and not notes, s)
s, _ = LL.planner_state({**REQ, "lever": {"policy": "discount", "value": 5}}, CATS)
check("쿠폰: 할인율 모드 + 5%", s.get("gl_coupon_mode") == "할인율 (%)" and s.get("gl_coupon_pct") == 5.0, s)
s, _ = LL.planner_state({**REQ, "lever": {"policy": "shipping", "value": 20000}}, CATS)
check("무료배송 기준 2만원", s.get("gl_ship_threshold") == 20000, s)
s, notes = LL.planner_state({**REQ, "target": {"type": "category", "value": "없는카테고리"},
                             "lever": {"policy": "bundle", "value": 5}}, CATS)
check("지원 안 하는 대상·수단은 넣지 않고 안내", "gl_cat" not in s and "gl_policy" not in s and len(notes) == 2, (s, notes))

card = LL.context_card(None)
check("요약 없음 → 안내 카드", "프로모션 분석하기" in card.conclusion)
ctx = {"화면": "Growth Lab 프로모션 검토", "카테고리": "정육", "프로모션": "판매가 10% 할인", "손익 기준": "최근 28일",
       "주문 반응 가정": (-0.05, 0.10, 0.30), "운영 일수": 14, "예상 매출 중앙값": 4_200_000,
       "예상 이익률 중앙값": 0.213, "본전 주문 증가율": 0.184}
card = LL.context_card(ctx)
check("검토 카드: 본전 문장", "18.4%" in card.conclusion, card.conclusion)
check("검토 카드: 숫자 3개", len(card.numbers) == 3 and card.numbers[2].value == "21.3%", card.numbers)
check("검토 카드: 가정 표시", "가정값" in card.note and "예측 아님" in card.note, card.note)
check("본전 계산 불가", "계산할 수 없습니다" in LL.context_card({**ctx, "본전 주문 증가율": None}).conclusion)
card = LL.context_card({"화면": "Growth Lab 프로모션 결과", "프로모션": "정육 5% 할인", "판정": "불분명", "카테고리": "정육"})
check("결과 카드: 판정", "'불분명'" in card.conclusion, card.conclusion)

# ---- 2) 화면 시험 (data/ CSV 또는 DB가 있어야 함) --------------------------------
if os.environ.get("DATA_BACKEND") == "csv" and not (ROOT / "data").is_dir():
    print(f"\n{ok}/{n} 통과 · 화면 시험은 data/ 폴더가 없어 건너뜀")
    sys.exit(0 if ok == n else 1)
from streamlit.testing.v1 import AppTest  # noqa: E402

from engine import ui  # noqa: E402

cats = sorted(ui.get_mart()["raw"]["product"]["category"].dropna().astype(str).unique().tolist())
target = cats[-1]                     # 기본값(첫 카테고리)과 다른 것으로 넘겨야 채움 여부가 보인다
at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=120)
at.run()
check("앱 첫 화면 오류 없음", not at.exception, at.exception)
at.session_state["lab_request"] = {"type": "plan", "target": {"type": "category", "value": target},
                                   "lever": {"policy": "price", "value": -10}}
at.session_state["goto"] = "lab"
at.run()
check("Growth Lab 이동 오류 없음", not at.exception, at.exception)
sel = [w for w in at.selectbox if w.key == "gl_cat"]
check("넘겨받은 카테고리 채움", sel and sel[0].value == target, sel and sel[0].value)
num = [w for w in at.number_input if w.key == "gl_price_pct"]
check("넘겨받은 판매가 할인율 10% 채움", num and num[0].value == 10.0, num and num[0].value)
check("넘김 안내 표시", any("넘겨받은 조건" in i.value for i in at.info), [i.value for i in at.info])
check("위젯 값 경고 없음", not any("Session State API" in w.value for w in at.warning), [w.value for w in at.warning])

btn = [b for b in at.button if b.key == "lab_summary"]
check("챗봇 패널에 요약 버튼", bool(btn))
analyze = [b for b in at.button if "프로모션 분석하기" in (b.label or "")]
analyze[0].click().run()
check("분석 실행 오류 없음", not at.exception, at.exception)
ctx = at.session_state["growth_context"] if "growth_context" in at.session_state else None
check("growth_context 생성", ctx and ctx.get("카테고리") == target, ctx)
[b for b in at.button if b.key == "lab_summary"][0].click().run()
log = at.session_state["chat_log"]
check("챗봇에 Growth Lab 요약 카드", log and log[-1]["role"] == "lab" and target in " ".join(log[-1]["card"].tags),
      log[-1] if log else None)
check("카드 숫자 = 화면 값", log[-1]["card"].numbers[2].value == f"{ctx['예상 이익률 중앙값']:.1%}")

# 같은 요청으로 다시 들어와도 사용자가 바꾼 값을 덮지 않는다
[w for w in at.number_input if w.key == "gl_price_pct"][0].set_value(7.0).run()
at.run()
check("한 번만 채움(사용자 수정 유지)", [w for w in at.number_input if w.key == "gl_price_pct"][0].value == 7.0)

print(f"\n{ok}/{n} 통과")
sys.exit(0 if ok == n else 1)
