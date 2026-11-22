"""Growth Lab 화면(views/growth_lab.py, 팀원 담당)이 쓰는 표기 함수.

예전 분석 흐름(진단→원인→가설→실험→판정)은 engine/flow.py로 바뀌었다(2026-11-22).
Growth Lab 화면이 이 모듈의 target_text만 쓰므로 그 함수만 남긴다.
"""
from __future__ import annotations


def target_text(target: dict | None) -> str:
    if not target:
        return ""
    return f"{target['value']} 카테고리" if target["type"] == "category" else target["value"]
