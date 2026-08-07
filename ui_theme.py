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
  #9a8f89 / #7a716c    흐린 텍스트 (따뜻한 회색 계열)
  Pretendard           UI 폰트 (양쪽 공통)
  Myriad Pro           그래프 폰트 (I-V Studio)

⚠ 왜 sv-ttk(Sun Valley)를 안 쓰는가 — 실측으로 확인한 사실:
   sv-ttk의 위젯은 **미리 렌더링된 PNG 스프라이트**로 그려진다.
   `Style.element_options('AccentButton.button')` 이 빈 튜플 `()` 이라
   background/foreground 를 설정해도 **그대로 무시되고 파란색이 유지된다.**
   (설정값은 스타일 DB에 저장돼 lookup 으로는 보이지만 그리기에 안 쓰인다)
   반면 'clam' 은 색으로 직접 그리는 테마라
   Button.border -> ('bordercolor','lightcolor','darkcolor',...)
   Entry.field   -> ('bordercolor','lightcolor','fieldbackground')
   처럼 색 옵션을 노출한다. 그래서 **주황/회색 팔레트를 실제로 반영하려면
   clam 이 맞다.** 모양은 sv-ttk가 더 현대적이지만 색을 못 바꾸면 디자인
   룰을 맞춘다는 목적 자체가 무너진다.

⚠ tkinter의 한계(정직하게):
   둥근 모서리·그림자·애니메이션·글래스모피즘은 재현할 수 없다. 웹앱과
   '똑같이'가 아니라 **같은 색·같은 폰트·같은 톤**까지가 목표다.
"""

from __future__ import annotations

import sys
import tkinter.font as tkfont
from tkinter import ttk


# ---------------- 고해상도(HiDPI) ----------------
def enable_hidpi():
    """⚠ Tk() 를 만들기 **전에** 호출해야 한다.

    DPI 인식을 안 하면 Windows가 그 프로세스에게 "화면은 96 DPI"라고 거짓말한
    뒤, 1배로 그려진 창을 배율만큼 **비트맵 확대**해 버린다. 그래서 글자·선이
    뭉개져 '해상도가 낮아 보이는' 증상이 생긴다.
    (이 PC 실측: 레지스트리 AppliedDPI=144(150%)인데 DPI 비인식 프로세스에는
     96으로 보고됨 — 정확히 이 현상)

    DPI 인식을 켜면 화면 픽셀 그대로 그려서 선명해진다. 대신 1논리픽셀 =
    1실제픽셀이 되어 UI가 작아지므로, apply()에서 배율만큼 다시 키운다.
    """
    if sys.platform != "win32":
        return
    import ctypes
    # PER_MONITOR_AWARE_V2 (Win10 1703+) — 모니터마다 배율이 달라도 대응
    try:
        if ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return
    except Exception:  # noqa: BLE001
        pass
    try:  # PROCESS_PER_MONITOR_DPI_AWARE (Win8.1+)
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except Exception:  # noqa: BLE001
        pass
    try:  # 시스템 전역 DPI 인식 (Vista+)
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:  # noqa: BLE001
        pass


def dpi_scale(root):
    """이 창의 실제 배율. 1.0 = 100%, 1.5 = 150%."""
    try:
        return float(root.winfo_fpixels("1i")) / 96.0
    except Exception:  # noqa: BLE001
        return 1.0


def sx(root, px):
    """픽셀 값을 화면 배율에 맞게 환산 (창 크기·캔버스 크기 등에 사용)."""
    return int(round(px * dpi_scale(root)))

# ---------------- 디자인 토큰 ----------------
ACCENT = "#ed542b"          # 주 강조 (버튼, 선택, 강조 텍스트)
ACCENT_HOVER = "#c53a17"    # 호버/눌림
ACCENT_SOFT = "#f68b21"     # 보조 주황
ACCENT_TINT = "#fdece7"     # 아주 옅은 주황 (선택 배경)

TEXT = "#1a1a1a"
TEXT_MUTED = "#7a716c"      # 따뜻한 회색
TEXT_FAINT = "#9a8f89"

# 표면(따뜻한 회색 계열 — 파란빛 도는 기본 회색 대신)
BG = "#faf8f7"
SURFACE = "#ffffff"
SURFACE_ALT = "#f2efed"
BORDER = "#ddd6d2"
BORDER_STRONG = "#c9c0bb"
DISABLED_FG = "#b3aaa5"

OK_FG = "#0a7d28"
WARN_BG = "#fff3cd"
WARN_FG = "#7a5b00"
DANGER_BG = "#f8d7da"
DANGER_FG = "#7a1c1c"

UI_FONT_STACK = ["Pretendard", "Malgun Gothic", "맑은 고딕", "Segoe UI"]
PLOT_FONT_STACK = ["Myriad Pro", "Pretendard", "Segoe UI"]

SIZE_BODY = 10
SIZE_SMALL = 9
SIZE_H1 = 15
SIZE_H2 = 11


def pick_font(root, stack, default="TkDefaultFont"):
    try:
        fams = set(tkfont.families(root))
    except Exception:  # noqa: BLE001
        return default
    for f in stack:
        if f in fams:
            return f
    return default


def apply(root):
    """루트 창에 테마를 적용하고 폰트 정보를 돌려준다.
    반환: {"ui": UI폰트, "plot": 그래프폰트, "themed": bool}"""
    ui = pick_font(root, UI_FONT_STACK)
    plot = pick_font(root, PLOT_FONT_STACK, default=ui)

    st = ttk.Style(root)
    try:
        st.theme_use("clam")   # 색을 실제로 반영할 수 있는 테마
        themed = True
    except Exception:  # noqa: BLE001
        themed = False

    # Tk 의 포인트→픽셀 환산 기준을 실제 화면 DPI에 맞춘다.
    # 이렇게 해야 폰트 크기를 포인트로 지정한 것이 어떤 배율의 모니터에서도
    # 같은 물리적 크기로 보인다. (숫자를 배율만큼 곱하면 이중 확대가 된다)
    scale = dpi_scale(root)
    try:
        root.tk.call("tk", "scaling", root.winfo_fpixels("1i") / 72.0)
    except Exception:  # noqa: BLE001
        pass

    for name, size in (("TkDefaultFont", SIZE_BODY), ("TkTextFont", SIZE_BODY),
                       ("TkMenuFont", SIZE_BODY), ("TkHeadingFont", SIZE_H2),
                       ("TkFixedFont", SIZE_SMALL)):
        try:
            tkfont.nametofont(name).configure(family=ui, size=size)
        except Exception:  # noqa: BLE001
            pass

    try:
        root.configure(background=BG)
    except Exception:  # noqa: BLE001
        pass

    # ---------- 기본 표면 ----------
    st.configure(".", background=BG, foreground=TEXT,
                 fieldbackground=SURFACE, bordercolor=BORDER,
                 lightcolor=BG, darkcolor=BG, font=(ui, SIZE_BODY))
    st.configure("TFrame", background=BG)
    st.configure("TLabel", background=BG, foreground=TEXT)
    st.configure("TLabelframe", background=BG, bordercolor=BORDER,
                 lightcolor=BG, darkcolor=BG)
    st.configure("TLabelframe.Label", background=BG, foreground=TEXT_MUTED,
                 font=(ui, SIZE_SMALL, "bold"))
    st.configure("TPanedwindow", background=BG)
    st.configure("TSeparator", background=BORDER)

    # ---------- 일반 버튼 ----------
    st.configure("TButton", background=SURFACE_ALT, foreground=TEXT,
                 bordercolor=BORDER, lightcolor=SURFACE_ALT, darkcolor=SURFACE_ALT,
                 focuscolor=ACCENT, padding=(10, 5), relief="flat")
    st.map("TButton",
           background=[("disabled", SURFACE_ALT), ("pressed", BORDER_STRONG),
                       ("active", BORDER)],
           foreground=[("disabled", DISABLED_FG)],
           bordercolor=[("active", ACCENT), ("focus", ACCENT)])

    # ---------- 강조 버튼(주요 동작) ----------
    st.configure("Accent.TButton", background=ACCENT, foreground="#ffffff",
                 bordercolor=ACCENT, lightcolor=ACCENT, darkcolor=ACCENT,
                 font=(ui, SIZE_BODY, "bold"), padding=(12, 6), relief="flat")
    st.map("Accent.TButton",
           background=[("disabled", "#e8c7bc"), ("pressed", ACCENT_HOVER),
                       ("active", ACCENT_HOVER)],
           foreground=[("disabled", "#ffffff")],
           bordercolor=[("disabled", "#e8c7bc"), ("active", ACCENT_HOVER)],
           lightcolor=[("pressed", ACCENT_HOVER), ("active", ACCENT_HOVER)],
           darkcolor=[("pressed", ACCENT_HOVER), ("active", ACCENT_HOVER)])

    # ---------- 입력 ----------
    st.configure("TEntry", fieldbackground=SURFACE, bordercolor=BORDER,
                 lightcolor=BORDER, darkcolor=BORDER, insertcolor=TEXT, padding=4)
    st.map("TEntry", bordercolor=[("focus", ACCENT)],
           lightcolor=[("focus", ACCENT)], darkcolor=[("focus", ACCENT)])
    st.configure("TSpinbox", fieldbackground=SURFACE, bordercolor=BORDER,
                 arrowcolor=TEXT_MUTED, padding=3)
    st.map("TSpinbox", bordercolor=[("focus", ACCENT)],
           arrowcolor=[("active", ACCENT)])
    st.configure("TCombobox", fieldbackground=SURFACE, bordercolor=BORDER,
                 arrowcolor=TEXT_MUTED, padding=3)
    st.map("TCombobox", bordercolor=[("focus", ACCENT)],
           arrowcolor=[("active", ACCENT)],
           fieldbackground=[("readonly", SURFACE)])

    # ---------- 체크/스케일 ----------
    st.configure("TCheckbutton", background=BG, foreground=TEXT, focuscolor=ACCENT)
    st.map("TCheckbutton", background=[("active", BG)],
           indicatorcolor=[("selected", ACCENT), ("!selected", SURFACE)])
    st.configure("TScale", background=BG, troughcolor=SURFACE_ALT,
                 bordercolor=BORDER, lightcolor=ACCENT, darkcolor=ACCENT)
    st.map("TScale", background=[("active", BG)])

    # ---------- 탭 ----------
    st.configure("TNotebook", background=BG, bordercolor=BORDER, tabmargins=(2, 4, 2, 0))
    st.configure("TNotebook.Tab", background=SURFACE_ALT, foreground=TEXT_MUTED,
                 bordercolor=BORDER, lightcolor=SURFACE_ALT, darkcolor=SURFACE_ALT,
                 padding=(14, 7), font=(ui, SIZE_BODY))
    st.map("TNotebook.Tab",
           background=[("selected", ACCENT), ("active", BORDER)],
           foreground=[("selected", "#ffffff"), ("active", TEXT)],
           lightcolor=[("selected", ACCENT)], darkcolor=[("selected", ACCENT)],
           font=[("selected", (ui, SIZE_BODY, "bold"))])

    # ---------- 표 ----------
    st.configure("Treeview", background=SURFACE, fieldbackground=SURFACE,
                 foreground=TEXT, bordercolor=BORDER, rowheight=24)
    st.map("Treeview", background=[("selected", ACCENT_TINT)],
           foreground=[("selected", TEXT)])
    st.configure("Treeview.Heading", background=SURFACE_ALT, foreground=TEXT_MUTED,
                 bordercolor=BORDER, relief="flat", font=(ui, SIZE_SMALL, "bold"))
    st.map("Treeview.Heading", background=[("active", BORDER)])

    # ---------- 스크롤바 ----------
    st.configure("Vertical.TScrollbar", background=SURFACE_ALT, troughcolor=BG,
                 bordercolor=BG, arrowcolor=TEXT_MUTED)
    st.map("Vertical.TScrollbar", background=[("active", BORDER_STRONG)])

    # ---------- 텍스트 스타일 ----------
    st.configure("H1.TLabel", font=(ui, SIZE_H1, "bold"), foreground=TEXT, background=BG)
    st.configure("H2.TLabel", font=(ui, SIZE_H2, "bold"), foreground=TEXT, background=BG)
    st.configure("Muted.TLabel", font=(ui, SIZE_SMALL), foreground=TEXT_MUTED, background=BG)
    st.configure("Faint.TLabel", font=(ui, SIZE_SMALL), foreground=TEXT_FAINT, background=BG)
    st.configure("Accent.TLabel", font=(ui, SIZE_BODY, "bold"), foreground=ACCENT, background=BG)

    return {"ui": ui, "plot": plot, "themed": themed, "scale": scale}


def status_colors(kind):
    """상태 배지 색 (배경, 전경)."""
    return {
        "ok": (None, OK_FG),
        "warn": (WARN_BG, WARN_FG),
        "danger": (DANGER_BG, DANGER_FG),
        "idle": (None, TEXT_MUTED),
    }.get(kind, (None, TEXT_MUTED))
