# -*- coding: utf-8 -*-
"""
ui_theme.py — NBEDL 공용 디자인 토큰과 tkinter 테마 적용
==========================================================
NBEDL-Exp-Assistant / Photodetector I-V Studio(둘 다 Streamlit)와 색·폰트를
맞추기 위한 모듈. 토큰 값은 그 두 앱의 실제 코드에서 확인한 값이다.

  #ed542b  주 강조색   (Exp-Assistant 19회, I-V Studio ACCENT 상수)
  #f68b21  보조 주황   (Exp-Assistant)
  #c53a17  진한 강조   (호버/눌림)
  #1a1a1a  본문 텍스트
  #9a8f89 / #7a716c    흐린 텍스트
  Pretendard           UI 폰트 (양쪽 공통)
  Myriad Pro           그래프 폰트 (I-V Studio)

⚠ tkinter의 한계(정직하게):
  둥근 모서리·그림자·애니메이션·글래스모피즘은 재현할 수 없다. 웹앱과
  '똑같이'가 아니라 **같은 색·같은 폰트·같은 톤**까지가 목표다.

sv-ttk(Sun Valley 테마)가 있으면 그걸 바탕으로 쓰고, 없으면 내장 'clam'
테마로 자동 대체한다 — 즉 sv-ttk가 없어도 프로그램은 정상 동작한다.
"""

from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

# ---------------- 디자인 토큰 ----------------
ACCENT = "#ed542b"
ACCENT_HOVER = "#c53a17"
ACCENT_SOFT = "#f68b21"
TEXT = "#1a1a1a"
TEXT_MUTED = "#7a716c"
TEXT_FAINT = "#9a8f89"
BG = "#ffffff"
BG_SUBTLE = "#f7f5f4"
BORDER = "#e3dedb"

OK_FG = "#0a7d28"
WARN_BG = "#fff3cd"
WARN_FG = "#7a5b00"
DANGER_BG = "#f8d7da"
DANGER_FG = "#7a1c1c"

# 폰트 우선순위 — 설치돼 있는 첫 번째를 쓴다
UI_FONT_STACK = ["Pretendard", "Malgun Gothic", "맑은 고딕", "Segoe UI"]
PLOT_FONT_STACK = ["Myriad Pro", "Pretendard", "Segoe UI"]

SIZE_BODY = 10
SIZE_SMALL = 9
SIZE_H1 = 15
SIZE_H2 = 11


def pick_font(root, stack, default="TkDefaultFont"):
    """설치된 폰트 중 우선순위가 가장 높은 것을 고른다."""
    try:
        fams = set(tkfont.families(root))
    except Exception:  # noqa: BLE001
        return default
    for f in stack:
        if f in fams:
            return f
    return default


def apply(root):
    """루트 창에 테마를 적용하고, 쓸 수 있는 폰트 이름들을 돌려준다.

    반환: {"ui": <UI 폰트명>, "plot": <그래프 폰트명>, "themed": bool}
    """
    ui_font = pick_font(root, UI_FONT_STACK)
    plot_font = pick_font(root, PLOT_FONT_STACK, default=ui_font)

    themed = False
    try:
        import sv_ttk  # 순수 파이썬(.py/.tcl/.png) — 32비트에서도 안전
        sv_ttk.set_theme("light")
        themed = True
    except Exception:  # noqa: BLE001 — 미설치/로드 실패 모두 여기로
        try:
            ttk.Style(root).theme_use("clam")
        except Exception:  # noqa: BLE001
            pass

    # tk 기본 폰트들을 한 번에 교체 — Text/Label 등 비-ttk 위젯까지 적용된다
    for name, size in (("TkDefaultFont", SIZE_BODY), ("TkTextFont", SIZE_BODY),
                       ("TkMenuFont", SIZE_BODY), ("TkHeadingFont", SIZE_H2),
                       ("TkFixedFont", SIZE_SMALL)):
        try:
            f = tkfont.nametofont(name)
            f.configure(family=ui_font, size=size)
        except Exception:  # noqa: BLE001
            pass

    st = ttk.Style(root)

    # 강조 버튼 — 주요 동작(측정 실행/내보내기 등)에만 쓴다
    st.configure("Accent.TButton", font=(ui_font, SIZE_BODY, "bold"))
    st.map("Accent.TButton",
           background=[("active", ACCENT_HOVER), ("!disabled", ACCENT)],
           foreground=[("!disabled", "#ffffff")])

    # 위험 동작(삭제)
    st.configure("Danger.TButton", font=(ui_font, SIZE_SMALL))

    # 제목/부제
    st.configure("H1.TLabel", font=(ui_font, SIZE_H1, "bold"), foreground=TEXT)
    st.configure("H2.TLabel", font=(ui_font, SIZE_H2, "bold"), foreground=TEXT)
    st.configure("Muted.TLabel", font=(ui_font, SIZE_SMALL), foreground=TEXT_MUTED)
    st.configure("Faint.TLabel", font=(ui_font, SIZE_SMALL), foreground=TEXT_FAINT)
    st.configure("Accent.TLabel", font=(ui_font, SIZE_BODY, "bold"), foreground=ACCENT)

    # 표 헤더는 굵게 (sv-ttk에서도 유지되도록 명시)
    st.configure("Treeview.Heading", font=(ui_font, SIZE_SMALL, "bold"))

    return {"ui": ui_font, "plot": plot_font, "themed": themed}


def status_colors(kind):
    """상태 배지 색 (배경, 전경)."""
    return {
        "ok": (None, OK_FG),
        "warn": (WARN_BG, WARN_FG),
        "danger": (DANGER_BG, DANGER_FG),
        "idle": (None, TEXT_MUTED),
    }.get(kind, (None, TEXT_MUTED))
