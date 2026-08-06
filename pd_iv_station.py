# -*- coding: utf-8 -*-
"""
pd_iv_station.py — Keithley 4200(KXCI) + Mightex BioLED 통합 측정 스테이션 (KITE 스타일 GUI)
================================================================================
탭 구조: SMU 구성 / 측정 설정 / 측정 실행 / I-T 측정.
DLL(ctypes) 기반 KXCI 제어(HANDOFF_keithley_automation.md 4~5절 검증 내용 반영).

⚠ 32비트 파이썬 전용 (KXCIclient.dll이 32비트).
   py -3.13-32 pd_iv_station.py
   확인: python -c "import struct; print(struct.calcsize('P')*8)"  -> 32

pandas/numpy 미사용(32비트 휠 부재 위험). GUI는 표준 tkinter만 사용.
"""

from __future__ import annotations

import ctypes
import json
import math
import os
import re
import sys
import threading
import queue
import time
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, simpledialog, ttk

# ==========================================================
# 상수
# ==========================================================
IP = b"192.168.0.200"
PORT = 2105
DLL_NAME = "KXCIclient.dll"
BUF_SIZE = 4096

STATION_CONFIG_FILE = "station_config.json"
STATION_PRESETS_FILE = "station_presets.json"
BIOLED_SETTINGS_FILE = "bioled_settings.json"   # bioled_controller.py 와 공유
BIOLED_PRESETS_FILE = "bioled_presets.json"     # bioled_controller.py 와 공유
IT_CONFIG_FILE = "it_config.json"               # pd_it.py 와 공유
SESSIONS_DIR = "sessions"
IT_OUTPUT_DIR = "it_data"

BIT_DATA_READY = 0x01
BIT_SYNTAX_ERR = 0x02
BIT_BUSY = 0x10

# 고정 전류 레인지 사다리 (프리앰프 없을 때, Reference Manual 기준)
FIXED_RANGES_A = [1e-9, 1e-8, 1e-7, 1e-6, 1e-5, 1e-4, 1e-3, 1e-2, 1e-1]
RANGE_LABELS = {
    # 실제 KITE 산출물(예: example/15s_1 [dd876543].xls Settings 시트)의
    # 'Range I' 값이 "100uA"처럼 숫자·단위 사이에 공백이 없다 — 그 표기를 그대로 따른다.
    1e-9: "1nA", 1e-8: "10nA", 1e-7: "100nA",
    1e-6: "1uA", 1e-5: "10uA", 1e-4: "100uA",
    1e-3: "1mA", 1e-2: "10mA", 1e-1: "100mA",
}

# pd_app/constants.py의 SYMBOL_MAP과 반드시 동일해야 함 (엑셀 브래킷 코드용).
# 내부 설정 파일(it_config.json 등)은 공백 없는 "530nm" 형태를 그대로 쓰고,
# 엑셀에 적히는 라벨만 pd_app이 기대하는 "530 nm" 형태로 변환한다.
# 목록 순서는 파장이 큰 것(940)이 위로 오도록 요청받아 내림차순으로 둔다.
WAVELENGTHS = ["940nm", "850nm", "740nm", "625nm", "530nm", "470nm", "405nm", "365nm"]
PRETTY_LABEL = {wl: f"{wl[:-2]} {wl[-2:]}" for wl in WAVELENGTHS}
PRETTY_LABEL_TO_KEY = {v: k for k, v in PRETTY_LABEL.items()}
LABEL_TO_SYMBOL = {
    "Dark": "d",
    "940 nm": "8", "850 nm": "7", "740 nm": "6", "625 nm": "5",
    "530 nm": "4", "470 nm": "3", "405 nm": "2", "365 nm": "1",
}
# 드롭다운에 "8: 940 nm" 처럼 브래킷 코드 번호를 같이 보여주기 위한 표시용 문자열.
WL_DISPLAY = {wl: f"{LABEL_TO_SYMBOL[PRETTY_LABEL[wl]]}: {PRETTY_LABEL[wl]}" for wl in WAVELENGTHS}
WL_DISPLAY_TO_KEY = {v: k for k, v in WL_DISPLAY.items()}
SEP_TOKEN = "==================================" * 1  # pd_app 쪽 형태와 동일(개수 무관, "=====" 포함이면 됨)

# pd_app/constants.py의 DEFAULT_TRACE_COLORS/FALLBACK_CYCLE과 동일한 배색 —
# 여기서 본 그래프 색이 나중에 분석 앱에서도 그대로 보이게 맞춰둔다.
TRACE_COLORS = {
    "Dark": "#000000",
    "365 nm": "#800080", "405 nm": "#800080", "470 nm": "#0000FF",
    "530 nm": "#008000", "625 nm": "#FF0000", "740 nm": "#FF0080",
    "850 nm": "#8000FF", "940 nm": "#0000A0",
}
FALLBACK_TRACE_COLORS = ["#000000", "#FF0000", "#0000FF", "#00A000", "#FF00FF",
                         "#FF8000", "#008080", "#8000FF", "#808000", "#4169E1"]

# 콤보박스 표시 문자열은 한 곳에서만 정의한다 — 예전에 목록과 복원용 라벨을
# 따로 하드코딩해두는 바람에, 표기를 바꾸면 프리셋 불러오기가 조용히 깨졌다.
# 적분시간은 KITE의 "Speed"와 같은 것이라 그 이름을 병기한다.
IT_OPTS = ["1:Short(KITE Fast)", "2:Medium(KITE Normal)",
           "3:Long(KITE Quiet)", "4:Custom"]
SWEEP_OPTS = ["1:Linear", "2:Log10", "3:Log25", "4:Log50"]

# 그래프 작도 영역 비율 (가로:세로). 창 크기와 무관하게 이 비율을 유지한다.
ASPECT_W, ASPECT_H = 8, 10

_NUM = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")
# KXCI list-mode 응답 토큰은 "N-1.00000E+00"처럼 앞에 한 글자 상태 코드가
# 붙는다(공백 있는 경우도 있음: "N 0.00000E+00"). 그룹1=상태코드, 그룹2=숫자.
_TOK_STATUS = re.compile(r"([A-Za-z])\s*([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)")


# 컴플라이언스는 고정 레인지의 105%까지 설정할 수 있다.
# 근거: 실제 KITE 산출물(example/15s_1 [dd876543].xls)의 SMU1 컴플라이언스가
# 0.105 A = 105 mA 로, 최대 레인지 100 mA의 정확히 105%였다. 같은 파일에서
# SMU2는 컴플라이언스 11 uA인데 Range I가 10 uA가 아니라 100 uA인데, 이는
# 11 uA가 10 uA 레인지의 105%(=10.5 uA)를 넘어 담기지 않기 때문이다.
# ⚠ 105%는 위 실측값에서 역산한 것이고 매뉴얼 원문으로 확인한 값은 아니다.
COMPLIANCE_OVERRANGE = 1.05


def max_compliance_for(range_A: float) -> float:
    """이 레인지에서 설정 가능한 최대 컴플라이언스."""
    return range_A * COMPLIANCE_OVERRANGE


def min_range_for(compliance_A: float) -> float:
    """이 컴플라이언스를 담을 수 있는 가장 작은 레인지."""
    for r in FIXED_RANGES_A:
        if compliance_A <= max_compliance_for(r) * (1 + 1e-9):
            return r
    return FIXED_RANGES_A[-1]


def pick_fixed_range(i_max_A: float, margin: float = 3.0) -> float:
    need = abs(i_max_A) * margin
    for r in FIXED_RANGES_A:
        if r >= need:
            return r
    return FIXED_RANGES_A[-1]


def format_range_i(range_A):
    if range_A is None:
        return "N/A"
    return RANGE_LABELS.get(range_A, f"{range_A:g} A")


def _check_bitness():
    """⚠ 반드시 RuntimeError(=Exception 하위)를 던질 것.
    예전에는 SystemExit을 던졌는데, SystemExit은 BaseException 직속이라
    GUI의 `except Exception` 에 **안 잡힌다** — 그래서 실측 모드에서 연결
    버튼을 눌러도 오류창조차 안 뜨고 아무 반응이 없는 것처럼 보였다.
    (dry-run은 DLL을 아예 안 건드려서 '되는 것처럼' 보였던 것)"""
    bits = 8 * ctypes.sizeof(ctypes.c_void_p)
    if bits != 32:
        raise RuntimeError(
            f"KXCIClient.DLL은 32비트 전용인데 현재 파이썬은 {bits}비트입니다.\n"
            "  터미널에서: py -3.13-32 " + os.path.basename(__file__) + "\n"
            "  (VSCode라면 Ctrl+Shift+P -> Python: Select Interpreter -> 32비트 항목)"
        )


def find_dll(name: str) -> str:
    """DLL을 스크립트 위치 기준으로 자동 탐색한다.

    프로젝트 폴더를 어디에 두든(다른 PC로 통째로 복사/클론해도) 코드를 고칠
    필요가 없도록, 실행 중인 .py 파일 위치를 기준으로 찾는다. 못 찾으면
    어디를 뒤졌는지 전부 나열해서 알려준다 — '경로는 맞는 것 같은데 안 된다'는
    상황을 없애기 위함."""
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        here,                                  # 스크립트와 같은 폴더 (정상 배치)
        os.path.join(here, "cli_tools"),       # 저장소 하위
        os.path.dirname(here),                 # 한 단계 위
        os.getcwd(),                           # 현재 작업 폴더
        os.path.join(os.getcwd(), "cli_tools"),
    ]
    tried = []
    for d in candidates:
        p = os.path.join(d, name)
        if p in tried:
            continue
        tried.append(p)
        if os.path.exists(p):
            return p
    raise RuntimeError(
        f"'{name}' 을 찾지 못했습니다. 아래 위치를 모두 확인했습니다:\n  "
        + "\n  ".join(tried)
        + f"\n\n→ {name} 을 {here} 폴더에 두세요 "
          "(git clone 하면 자동으로 들어옵니다)."
    )


def load_cdecl_dll(name: str):
    """DLL을 찾아서 ctypes.CDLL로 로드. 실패 시 원인을 구분해 안내한다.

    파일은 분명히 있는데 로드가 실패하면 십중팔구 **의존 DLL 누락**이다.
    KXCIclient.dll은 MSVCR120.dll(Visual C++ 2013 재배포 패키지 x86)을
    필요로 하는데 Windows 기본 설치에는 없다 — 이때 파이썬이 내는 메시지가
    'Could not find module ... (or one of its dependencies)' 라서 마치
    경로 문제처럼 보인다. 실제로는 경로가 맞아도 나는 오류."""
    path = find_dll(name)
    try:
        return ctypes.CDLL(path)
    except OSError as e:
        raise RuntimeError(
            f"'{name}' 파일은 찾았지만 로드에 실패했습니다.\n"
            f"  경로: {path}\n"
            f"  원본 오류: {e}\n\n"
            "→ 파일이 있는데 이 오류가 나면 대부분 **의존 DLL 누락**입니다.\n"
            "   이 PC에 Visual C++ 2013 재배포 패키지(x86)를 설치하세요:\n"
            "   https://www.microsoft.com/en-us/download/details.aspx?id=40784\n"
            "   반드시 vcredist_x86.exe (64비트 OS에서도 x86!) 를 받으세요."
        ) from e


def load_json(path, default):
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return json.loads(json.dumps(default))  # deep copy


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def safe_filename(s: str) -> str:
    return re.sub(r"[^\w.+-]", "_", s)


# ==========================================================
# Keithley 4200 — KXCIClient.DLL(ctypes, cdecl) 래퍼
# ==========================================================
class Keithley4200:
    """DE/SS/SM/MD 페이지 명령을 감싼 범용 래퍼.
    호출 전에 반드시 configure_channels()로 채널 정의부터 보내야 한다(매뉴얼 규칙)."""

    def __init__(self, dry=False, log=print):
        self.dry = dry
        self.log = log
        self.dll = None
        if dry:
            return

        _check_bitness()
        dll = load_cdecl_dll(DLL_NAME)
        dll.OpenKXCIConnection_C.argtypes = [ctypes.c_char_p, ctypes.c_int,
                                             ctypes.POINTER(ctypes.c_int)]
        dll.OpenKXCIConnection_C.restype = ctypes.c_int
        dll.SendKXCICommand_C.argtypes = [ctypes.c_char_p, ctypes.c_char_p,
                                          ctypes.POINTER(ctypes.c_int)]
        dll.SendKXCICommand_C.restype = ctypes.c_int
        dll.GetKXCISpollByte_C.argtypes = [ctypes.POINTER(ctypes.c_ushort),
                                           ctypes.POINTER(ctypes.c_int)]
        dll.GetKXCISpollByte_C.restype = ctypes.c_int
        dll.CloseKXCIConnection_C.argtypes = []
        dll.CloseKXCIConnection_C.restype = None
        self.dll = dll

        sock_err = ctypes.c_int(0)
        ret = dll.OpenKXCIConnection_C(IP, PORT, ctypes.byref(sock_err))
        self.log(f"[4200] 연결 (DLL): ret={ret}, socket_err={sock_err.value}")
        if sock_err.value != 0:
            raise RuntimeError(f"KXCI 연결 실패 (socket_err={sock_err.value})")

        idn = self._raw_send("ID")
        self.log(f"[4200] 응답: {idn.strip()}")

    # ---------- 저수준 송수신 ----------
    def _raw_send(self, cmd: str) -> str:
        if self.dry:
            self.log(f"    [4200] {cmd}")
            return ""
        resp_buf = ctypes.create_string_buffer(BUF_SIZE)
        sock_err = ctypes.c_int(0)
        self.dll.SendKXCICommand_C(cmd.encode(), resp_buf, ctypes.byref(sock_err))
        if sock_err.value != 0:
            self.log(f"    ⚠ socket_err={sock_err.value} (cmd={cmd!r})")
        return resp_buf.value.decode(errors="ignore")

    def _w(self, cmd: str):
        self._raw_send(cmd)

    def _w_checked(self, cmd: str) -> bool:
        """전송 직후 상태 바이트를 확인해 Syntax Error를 즉시 잡아낸다.
        DE/SS/SM 명령은 실패해도 예외를 던지지 않고 조용히 무시되던 것이
        실기에서 확인됨(예: 6글자 넘는 채널 이름) — 그래서 DE/SS 등 설정
        명령은 전부 이 경로로 보내 문제를 바로 로그에 드러낸다."""
        self._raw_send(cmd)
        if not self.dry and (self.spoll() & BIT_SYNTAX_ERR):
            self.log(f"    ⚠ Syntax Error: {cmd!r}")
            return False
        return True

    def _fetch(self, name: str):
        raw = self._raw_send(f"DO '{name}'")
        # 파일럿 단계라 항상 원본 응답을 로그에 남긴다 — "0점 수신" 같은 문제를
        # 진단하려면 파싱 전 raw 문자열을 봐야 한다.
        self.log(f"    [DO '{name}'] raw={raw!r}")
        out = []
        for tok in raw.split(","):
            m = _NUM.search(tok)
            if m:
                out.append(float(m.group()))
        return out

    def fetch_with_status(self, name: str):
        """DO 응답의 각 토큰 앞에 붙는 한 글자 상태 코드(예: 'N'=Normal)까지
        같이 뽑아낸다. 컴플라이언스/오버플로 여부를 점 단위로 확인하려면
        이 코드가 필요하다 — 정확한 코드별 의미는 Reference Manual의 데이터
        상태 문자 표(9절 부근)로 재확인할 것, 'N'만 정상으로 잠정 취급한다."""
        raw = self._raw_send(f"DO '{name}'")
        self.log(f"    [DO '{name}'] raw={raw!r}")
        out = []
        for tok in raw.split(","):
            m = _TOK_STATUS.search(tok)
            if m:
                status = (m.group(1) or "").strip()
                out.append((float(m.group(2)), status))
        return out

    def spoll(self):
        """상태 바이트 1회 조회 (즉시 반환, 대기 없음)."""
        if self.dry:
            return 0
        spb = ctypes.c_ushort(0)
        sock_err = ctypes.c_int(0)
        self.dll.GetKXCISpollByte_C(ctypes.byref(spb), ctypes.byref(sock_err))
        return spb.value

    def wait_done(self, poll_s=0.2, max_wait_s=120, on_tick=None):
        if self.dry:
            return True
        t0 = time.time()
        first_poll = True
        while time.time() - t0 < max_wait_s:
            status = self.spoll()
            if status & BIT_SYNTAX_ERR:
                self.log("    ⚠ KXCI Syntax Error 비트 감지 — 직전 명령 문법 확인 필요")
            if status & BIT_DATA_READY:
                # 트리거 직후 첫 폴링에서 이미 완료로 나오는 건 물리적으로
                # 이상하다(스윕에 최소한의 시간은 걸린다). BC로 비트를 지웠는데도
                # 이러면 장비가 명령을 안 받았거나 이전 데이터가 남은 것.
                if first_poll:
                    self.log("    ⚠ 트리거 직후 첫 조회에서 이미 'Data Ready' — 측정이 실제로 "
                            "수행되지 않았거나 이전 데이터일 수 있습니다(스윕 설정/채널 정의 확인)")
                self._last_wait_s = time.time() - t0
                return True
            first_poll = False
            if on_tick:
                on_tick(time.time() - t0)
            time.sleep(poll_s)
        self._last_wait_s = time.time() - t0
        self.log("    ⚠ wait_done 타임아웃 — Data Ready 비트가 서지 않음")
        return False

    # ---------- DE 페이지: 채널 정의 ----------
    def configure_channels(self, channels):
        """channels: [{ch,enabled,vname,iname,mode,func}, ...] (최대 8개, ch=1~8).
        mode: 1=전압원 2=전류원 3=Common   func: 1=VAR1 2=VAR2 3=Constant 4=VAR1'
        Common(3)이면 func도 반드시 3이어야 한다(매뉴얼 규칙 — 호출자가 보장)."""
        self._w("DE")
        for c in channels:
            if not c.get("enabled"):
                self._w(f"CH{c['ch']}")  # 아무것도 안 붙이면 해당 채널 꺼짐
                continue
            mode = 3 if c["mode"] == 3 else c["mode"]
            func = 3 if mode == 3 else c["func"]
            self._w_checked(f"CH{c['ch']},'{c['vname']}','{c['iname']}',{mode},{func}")

    # ---------- SS 페이지: 소스 설정 ----------
    def setup_sources(self, channels, sweep_type=1):
        """VAR1(func=1) 채널은 호출자가 별도로 vr_sweep()/ir_sweep()으로 값을 넣는다.
        여기서는 Constant(func=3)로 지정된 채널들만 VC/IC로 값을 채운다."""
        self._w("SS")
        for c in channels:
            if not c.get("enabled") or c["mode"] == 3:
                continue
            if c.get("func") == 3:
                val = c.get("const_value", 0.0)
                comp = c.get("const_compliance", 1e-3)
                cmd = "VC" if c["mode"] == 1 else "IC"
                self._w_checked(f"{cmd}{c['ch']},{val:g},{comp:g}")

    def vr_sweep(self, ch, start, stop, step, compliance_A, sweep_type=1):
        step = abs(step) * (1 if stop >= start else -1)
        self._w_checked(f"VR{sweep_type},{start:g},{stop:g},{step:g},{compliance_A:g}")

    def ir_sweep(self, ch, start, stop, step, compliance_A, sweep_type=1):
        step = abs(step) * (1 if stop >= start else -1)
        self._w_checked(f"IR{sweep_type},{start:g},{stop:g},{step:g},{compliance_A:g}")

    def vc_constant(self, ch, value, compliance_A):
        self._w_checked(f"VC{ch},{value:g},{compliance_A:g}")

    # ---------- SM 페이지: 측정 설정 ----------
    def _send_li(self, names):
        """LI = 리스트 모드에서 **측정할 함수**를 지정한다 (매뉴얼 5.4절).

        ⚠ 이걸 안 보내면 스윕 변수(전압)는 돌려주지만 **전류가 측정 대상으로
        등록되지 않아 전부 0.00000E+00으로 돌아온다.** 실기에서 정확히 이
        증상이 나왔다(V는 201점 정상, I는 201개 전부 정확히 0). 측정 자체도
        전류를 적분하지 않으니 예상보다 빨리 끝난다.
        이름은 DE 페이지에서 붙인 것을 그대로 써야 하고 최대 6개."""
        names = [n for n in (names or []) if n]
        if not names:
            return
        self._w_checked("LI " + ",".join(f"'{n}'" for n in names[:6]))

    def setup_measure_iv(self, measure_names=None):
        self._w("SM")
        self._w_checked("DM2")  # 리스트 데이터 모드
        self._send_li(measure_names)

    def setup_measure_it(self, wait_s, interval_s, n_reads, measure_names=None):
        self._w("SM")
        self._w_checked(f"WT {wait_s:g}")
        self._w_checked(f"IN {interval_s:g}")
        self._w_checked(f"NR {n_reads}")
        self._w_checked("DM2")
        self._send_li(measure_names)

    # ---------- 전역 설정 ----------
    def set_integration(self, mode, custom=None):
        """mode: 1=Short 2=Medium 3=Long, 4=Custom(custom=(delay,filter,plc))"""
        if mode == 4 and custom:
            d, f, plc = custom
            self._w_checked(f"IT 4,{d:g},{f:g},{plc:g}")
        else:
            self._w_checked(f"IT {mode}")

    def set_resolution(self, digits):
        self._w_checked(f"RS {digits}")

    def set_range_fixed(self, ch, range_A, compliance_A):
        """RI(즉시 고정)를 우선 시도하고, Syntax Error 비트가 뜨면 RG(하한만 지정)로
        자동 폴백한다.

        ⚠ **컴플라이언스는 고정 레인지보다 클 수 없다.** 예전 기본값이
        Range 10uA + 컴플라이언스 1mA(100배)라 모순된 조합이었고, 이것이
        RI Syntax Error의 원인으로 보인다(장비가 RI를 지원하지 않아서가
        아니라). 실제 KITE 측정 파일도 Range 100uA / 컴플라이언스 11uA로
        레인지 안쪽 값을 쓴다."""
        if compliance_A > range_A:
            self.log(f"    ⚠ 컴플라이언스({compliance_A:g}A)가 Range I({range_A:g}A)보다 큽니다 "
                    "— RI는 이 조합을 거부합니다. 탭2에서 컴플라이언스를 Range 이하로 "
                    "낮추세요(그대로 진행하면 RG 폴백으로 오토레인징이 됩니다).")
        self._w(f"RI{ch},{range_A:g},{compliance_A:g}")
        if not self.dry and (self.spoll() & BIT_SYNTAX_ERR):
            self.log(f"    ⚠ RI{ch} Syntax Error — RG{ch}로 폴백 "
                    "(컴플라이언스 > Range 조합이면 이게 원인)")
            self._w("BC")  # 에러/버퍼 비트 클리어
            self._w(f"RG{ch},{range_A:g}")

    # ---------- MD 페이지: 트리거 + 조회 ----------
    def trigger(self):
        """측정 시작. **반드시 BC로 이전 측정의 Data Ready 비트를 먼저 지운다.**

        BC를 안 보내면 직전 측정에서 세워진 Data Ready(B0)가 그대로 남아 있어,
        wait_done()이 첫 폴링에서 곧바로 '완료'로 판단하고 빠져나온다. 그러면
        스윕이 실제로 끝나기도 전에 DO로 데이터를 읽어서 **측정이 비정상적으로
        빨리 끝난 것처럼 보이고, 직전 측정의 낡은 데이터를 가져올 수 있다.**
        (매뉴얼 5.6절: BC = 데이터 버퍼 및 DataReady 비트 클리어)"""
        self._w("BC")
        self._w("MD")
        self._w("ME1")

    def fetch(self, name):
        return self._fetch(name)

    def close(self):
        if not self.dry and self.dll:
            self.dll.CloseKXCIConnection_C()


# ==========================================================
# BioLED (Mightex BLS-SA02-U) — ctypes HID DLL, bioled_controller.py 와
# 설정/프리셋 파일 공유
# ==========================================================
# 2026-07-30 확인: 이 장치는 시리얼(COM 포트) 장치가 아니라 USB HID 장치다
# (Mightex SDK 매뉴얼 "the BIOLED Control driver is designed as a HID
# device"). 그래서 장치관리자에 COM 포트로 절대 안 뜨고 pyserial로 열
# 방법 자체가 없었다 — 이전 코드의 ASCII 시리얼 명령(MODE/NORMAL/CURRENT)은
# 전부 추측이었고 틀렸음. 공식 SDK DLL(Mightex_BLSDriver_SDK.dll,
# cdecl, 32비트 전용 — Keithley KXCIclient.dll과 동일 패턴)을 ctypes로
# 직접 불러써야 한다. 세기(%)는 장치 API 자체가 "0.1% 단위"로 받는다
# (예: 500 = 50.0%) — 그래서 max_mA 환산이 필요 없다. 상세: cli_tools/
# bls_dll_test.py, SDK/Documents/Mightex bioLED Controller SDK Manual.pdf.
BLS_DLL_NAME = "Mightex_BLSDriver_SDK.dll"
BLS_MODE_DISABLE = 0
BLS_MODE_NORMAL = 1
BLS_MODE_TRIGGER = 3


class BioLED:
    def __init__(self, dry=False, log=print):
        self.dry = dry
        self.log = log
        self.dll = None
        self.handle = None
        self.channels = None     # 장비가 실제로 가진 채널 수 (연결 후 조회)
        self.serial = ""
        if dry:
            return

        bits = 8 * ctypes.sizeof(ctypes.c_void_p)
        if bits != 32:
            raise RuntimeError(
                f"Mightex_BLSDriver_SDK.dll은 32비트 전용인데 현재 파이썬은 {bits}비트입니다.\n"
                "  터미널에서: py -3.13-32 " + os.path.basename(__file__))
        dll = load_cdecl_dll(BLS_DLL_NAME)
        dll.MTUSB_BLSDriverInitDevices.restype = ctypes.c_int
        dll.MTUSB_BLSDriverOpenDevice.argtypes = [ctypes.c_int]
        dll.MTUSB_BLSDriverOpenDevice.restype = ctypes.c_int
        dll.MTUSB_BLSDriverCloseDevice.argtypes = [ctypes.c_int]
        dll.MTUSB_BLSDriverCloseDevice.restype = ctypes.c_int
        dll.MTUSB_BLSDriverGetSerialNo.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
        dll.MTUSB_BLSDriverGetSerialNo.restype = ctypes.c_int
        dll.MTUSB_BLSDriverGetChannels.argtypes = [ctypes.c_int]
        dll.MTUSB_BLSDriverGetChannels.restype = ctypes.c_int
        dll.MTUSB_BLSDriverSetMode.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int]
        dll.MTUSB_BLSDriverSetMode.restype = ctypes.c_int
        dll.MTUSB_BLSDriverSetNormalCurrent.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int]
        dll.MTUSB_BLSDriverSetNormalCurrent.restype = ctypes.c_int
        self.dll = dll

        n = dll.MTUSB_BLSDriverInitDevices()
        self.log(f"[LED] InitDevices: {n}개 발견")
        if n <= 0:
            raise RuntimeError("BioLED 장치를 찾지 못했습니다 — 전원/USB 케이블/"
                              "BioLEDController.exe 종료 여부를 확인하세요.")
        handle = dll.MTUSB_BLSDriverOpenDevice(0)
        self.log(f"[LED] OpenDevice(0): handle={handle}")
        if handle < 0:
            raise RuntimeError("BioLED 장치 열기 실패 — 다른 프로그램이 이미 사용 중일 수 있습니다"
                              "(BioLEDController.exe를 완전히 종료했는지 확인).")
        self.handle = handle

        buf = ctypes.create_string_buffer(32)
        dll.MTUSB_BLSDriverGetSerialNo(handle, buf, 32)
        self.serial = buf.value.decode(errors="ignore")
        # ⚠ 장비가 실제로 가진 채널 수. BLS-SA02-U는 이름 그대로 채널이 몇 개
        # 없는데, 예전 코드는 파장 8개를 ch1~ch8에 기계적으로 배정해놓고 이
        # 값을 **조회만 하고 검증하지 않았다** — 없는 채널(ch6 등)에 명령을
        # 보내면 SDK가 ret=-1을 돌려주는데, 매뉴얼상 -1이 "invalid handle"로
        # 적혀 있어 핸들 문제로 오해하기 딱 좋았다. 이제 미리 막는다.
        self.channels = dll.MTUSB_BLSDriverGetChannels(handle)
        self.log(f"[LED] Serial={self.serial!r}, 사용 가능한 채널 수={self.channels}")

    def _check_channel(self, channel):
        """장비에 없는 채널이면 즉시 사람이 이해할 수 있는 오류로 막는다."""
        if self.dry:
            return
        if self.channels is not None and self.channels > 0 and not (1 <= channel <= self.channels):
            raise RuntimeError(
                f"이 BioLED 장비에는 채널 {channel}번이 없습니다 "
                f"(사용 가능: 1~{self.channels}번).\n\n"
                "파장↔채널 배정이 실제 장비와 다릅니다. 상단 'BioLED 채널 설정'에서 "
                "실제로 LED가 꽂힌 채널 번호로 고쳐주세요."
            )

    def set_percent(self, channel, percent):
        """percent: 0~100 (%). 장치 API는 '0.1%' 단위 정수를 받는다
        (예: 50.0% -> 500)."""
        if self.dry:
            self.log(f"    [LED] ch{channel} NORMAL, {percent}%")
            return
        self._check_channel(channel)
        self.dll.MTUSB_BLSDriverSetMode(self.handle, channel, BLS_MODE_NORMAL)
        tenths = int(round(percent * 10))
        ret = self.dll.MTUSB_BLSDriverSetNormalCurrent(self.handle, channel, tenths)
        if ret not in (0, None):
            self.log(f"    ⚠ SetNormalCurrent(ch{channel}, {percent}%) ret={ret} "
                    f"(-1=핸들/채널 오류, 1=장치 오류 / 이 장비 채널 수={self.channels})")

    def off(self, channel):
        if self.dry:
            self.log(f"    [LED] ch{channel} OFF")
            return
        self._check_channel(channel)
        self.dll.MTUSB_BLSDriverSetMode(self.handle, channel, BLS_MODE_DISABLE)

    def close(self):
        if not self.dry and self.dll and self.handle is not None:
            self.dll.MTUSB_BLSDriverCloseDevice(self.handle)
            self.handle = None      # 닫은 핸들을 다시 쓰지 않도록 무효화


# ==========================================================
# Session — 측정 누적, 즉시 CSV 기록, pd_app 호환 엑셀 내보내기
# ==========================================================
def save_csv(path, header, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    import csv
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


class Session:
    def __init__(self, sample_name, base_dir=SESSIONS_DIR):
        self.sample_name = sample_name
        self.base_dir = base_dir
        stamp = datetime.now().strftime("%y%m%d_%H%M%S")
        self.dir = os.path.join(base_dir, f"{safe_filename(sample_name)}_{stamp}")
        os.makedirs(self.dir, exist_ok=True)
        self.traces = []  # [{index,label,range_i_A,range_i_str,data,csv_path}]
        self._save_meta()

    def add_trace(self, label, range_i_A, data):
        idx = len(self.traces) + 1
        rec = {
            "index": idx,
            "label": label,
            "range_i_A": range_i_A,
            "range_i_str": format_range_i(range_i_A),
            "data": data,
        }
        rec["csv_path"] = os.path.join(
            self.dir, f"trace_{idx:02d}_{safe_filename(label)}.csv")
        # data는 (V, I, Status) 3튜플 — Status는 KXCI가 각 점에 붙이는 상태
        # 코드('N'=Normal, 그 외는 컴플라이언스/오버플로 가능성).
        save_csv(rec["csv_path"], ["Voltage (V)", "Current (A)", "Status"], data)
        self.traces.append(rec)
        self._save_meta()
        return rec

    def remove_last(self):
        return self.remove_at(len(self.traces) - 1)

    def remove_at(self, idx):
        """실제 4200(KITE)은 실행/Append만 가능해 중간 트레이스를 못 지우지만,
        여기서는 엑셀을 우리가 직접 생성하므로 순서·구성에 제약이 없다."""
        if not self.traces or idx < 0 or idx >= len(self.traces):
            return None
        rec = self.traces.pop(idx)
        try:
            os.remove(rec["csv_path"])
        except OSError:
            pass
        self._renumber()
        self._save_meta()
        return rec

    def update_label(self, idx, new_label):
        if 0 <= idx < len(self.traces):
            self.traces[idx]["label"] = new_label
            self._save_meta()

    def move(self, idx, delta):
        j = idx + delta
        if not (0 <= idx < len(self.traces) and 0 <= j < len(self.traces)):
            return False
        self.traces[idx], self.traces[j] = self.traces[j], self.traces[idx]
        self._renumber()
        self._save_meta()
        return True

    def _renumber(self):
        for i, t in enumerate(self.traces):
            t["index"] = i + 1

    def bracket_code(self):
        return "".join(LABEL_TO_SYMBOL.get(t["label"], "?") for t in self.traces)

    def _save_meta(self):
        meta = {
            "sample_name": self.sample_name,
            "traces": [
                {"index": t["index"], "label": t["label"],
                 "range_i_str": t["range_i_str"], "csv_path": t["csv_path"]}
                for t in self.traces
            ],
        }
        save_json(os.path.join(self.dir, "session.json"), meta)

    def export_excel(self, out_dir=".", sample_name=None):
        if not self.traces:
            raise ValueError("내보낼 트레이스가 없습니다.")
        from openpyxl import Workbook
        display_name = sample_name or self.sample_name

        wb = Workbook()
        ws0 = wb.active
        for i, t in enumerate(self.traces):
            sheet_name = "Data" if i == 0 else f"Append{i}"
            ws = ws0 if i == 0 else wb.create_sheet(sheet_name)
            ws.title = sheet_name
            # pd_app는 AnodeV/AnodeI 두 컬럼만 이름으로 골라 읽으므로 Status
            # 열이 추가로 있어도 무시될 뿐 호환에 영향 없음(재검증 완료).
            ws.append(["AnodeV", "AnodeI", "Status"])
            for v, i_, status in t["data"]:
                ws.append([v, i_, status])

        ws_set = wb.create_sheet("Settings")
        for i, t in enumerate(self.traces):
            block = "Initial Run" if i == 0 else f"Append {i}"
            ws_set.append([SEP_TOKEN])
            ws_set.append([block])
            ws_set.append(["Range I", t["range_i_str"]])
            ws_set.append(["Label", t["label"]])
        ws_set.append([SEP_TOKEN])

        bracket = self.bracket_code()
        # 파일명 서식: [측정순서] (샘플명).xlsx
        # pd_app 파서는 소괄호/대괄호를 각각 독립적으로 re.search 하므로 순서에
        # 구애받지 않는다(양쪽 순서 모두 동일하게 파싱되는 것을 확인함).
        fname = f"[{bracket}] ({safe_filename(display_name)}).xlsx"
        path = os.path.join(out_dir, fname)
        wb.save(path)
        return path


# ==========================================================
# 기본 설정값
# ==========================================================
DEFAULT_STATION_CONFIG = {
    "sample_name": "Sample",
    "output_dir": SESSIONS_DIR,
    # 기본 결선: example/15s_1 [dd876543].xls (실제 KITE 산출물) Settings 시트에서
    # 확인된 실측 배선 그대로 — SMU1=Cathode(Common), SMU2=Anode(Voltage Sweep).
    # HANDOFF 9번 미해결 항목 #1 여기서 해소됨. 배선이 다르면 탭1에서 바꾸면 된다.
    # 채널 이름(vname/iname)은 매뉴얼 표기 'BBBBBB'/'CCCCCC'가 정확히 6글자라 —
    # 6글자를 넘기면 DE 정의 자체가 조용히 Syntax Error 날 수 있다(실기에서 확인됨).
    # "VA"/"IA"는 4.3절에서 41점 수신까지 검증된 이름이라 그대로 재사용.
    "smu_channels": [
        {"ch": 1, "enabled": True, "vname": "VK", "iname": "IK", "mode": 3, "func": 3,
         "const_value": 0.0, "const_compliance": 1e-3},
        {"ch": 2, "enabled": True, "vname": "VA", "iname": "IA", "mode": 1, "func": 1,
         "const_value": 0.0, "const_compliance": 1e-3},
    ] + [
        {"ch": n, "enabled": False, "vname": f"V{n}", "iname": f"I{n}", "mode": 1, "func": 3,
         "const_value": 0.0, "const_compliance": 1e-3}
        for n in range(3, 9)
    ],
}

DEFAULT_STATION_PRESETS = {
    "presets": {
        "default": {
            # 전압 스텝 기본 0.01 V — Dark는 101점, 광전류(-1~+1)는 201점이 된다
            # 컴플라이언스는 **Range I를 넘으면 안 된다**(고정 레인지보다 큰
            # 컴플라이언스는 모순이라 RI가 Syntax Error를 낸다). Range 100uA에
            # 맞춰 100uA로 둔다. 소자 보호를 더 강하게 하려면 낮출 것 —
            # 참고로 실제 KITE 측정 파일은 11uA(1.1e-5)를 썼다.
            "dark_neg": {"start": 0.0, "stop": -1.0, "step": 0.01, "compliance": 1e-4},
            "dark_pos": {"start": 0.0, "stop": 1.0, "step": 0.01, "compliance": 1e-4},
            "photo": {"start": -1.0, "stop": 1.0, "step": 0.01, "compliance": 1e-4},
            "sweep_type": 1,
            # 적분시간 = KITE의 "Speed"에 해당. 실제 랩 측정 파일(example/15s_1)이
            # Speed=Normal 이었으므로 그에 맞춰 Medium(2)을 기본으로 둔다.
            # (기존 기본값 Short(1)=Fast 라서 평소보다 측정이 빨리 끝났던 것)
            "integration": {"mode": 2, "delay": 0, "filter": 0, "plc": 1.0},
            "resolution_digits": 6,
            "range_mode": "RI",       # auto / RI / RG
            "range_A": 1e-4,          # 100 uA — 실제 KITE 측정 파일과 동일

            "range_dark_same": True,
        }
    },
    "active_preset": "default",
}

# HID 장치라 포트/보드레이트 개념이 없다 — 파장 -> BioLED 채널 번호만 있으면 됨.
DEFAULT_BIOLED_SETTINGS = {
    "channels": {wl: {"channel": i + 1} for i, wl in enumerate(WAVELENGTHS)},
}
DEFAULT_OD = "OD0"
# 프리셋을 파장 -> OD(ND필터 값) -> [{"label","percent"}, ...] 로 묶어둔다.
# OD는 "ND 필터를 쓰냐 안 쓰냐, 어떤 OD 값이냐"에 따라 세기(%)가 실제로 내는
# 광량이 달라지기 때문에 구분이 필요하다(ND 필터 자체는 사람이 수동으로 낀다).
DEFAULT_BIOLED_PRESETS = {wl: {} for wl in WAVELENGTHS}


def normalize_led_presets(presets):
    """예전(OD 구분 없는 평면 리스트) 포맷으로 저장된 파일을 만나면
    {"OD0": [...]}로 감싸 새 포맷과 호환되게 만든다 — 데이터 손실 없이."""
    for wl, v in list(presets.items()):
        if isinstance(v, list):
            presets[wl] = {DEFAULT_OD: v} if v else {}
    return presets


HELP_TEXT = """\
⚠ 이 프로그램은 아직 파일럿(베타) 단계입니다.
   실기 연결과 기본 I-V 스윕은 확인되었지만, BioLED 실측·I-T 탭·엣지 케이스는
   아직 검증 중입니다. 이상 동작이 보이면 로그 창 내용을 그대로 기록해두세요.


1. 실행 전 준비물
────────────────
  - K4200에서 KITE를 완전히 종료하고 KXCI를 실행해 둘 것 (동시 실행 불가)
  - 32비트 파이썬으로 실행: 터미널에서
        py -3.13-32 pd_iv_station.py
  - 처음 한 번은 패키지 설치 필요(32비트 파이썬 기준):
        py -3.13-32 -m pip install openpyxl
    (pyserial은 더 이상 필요 없음 — 아래 참고)
  - BioLED(BLS-SA02-U)는 시리얼(COM 포트) 장치가 아니라 **USB HID 장치**다
    (Mightex 공식 SDK 매뉴얼에 명시된 사실). 그래서 장치관리자에 COM 포트로
    절대 안 뜨고, "포트 번호를 입력"하는 절차 자체가 없다 — 그냥 USB로
    연결하고 상단 "BioLED 연결" 버튼만 누르면 된다. 내부적으로는 Mightex
    공식 SDK DLL(Mightex_BLSDriver_SDK.dll + HIDDLL.dll, 이 파일과 같은
    폴더에 있어야 함)을 ctypes로 직접 호출한다.
  - ⚠ BLS 전용 소프트웨어(BioLEDController.exe)가 이미 켜져 있으면 장치를
    독점 사용 중이라 이 프로그램이 못 엽니다 — 연결하기 전에 완전히 종료할 것.
  - 개별 연결 점검: cli_tools\\bls_dll_test.py
  - 프리셋(세기 %) 등록은 cli_tools\\bioled_controller.py를 한 번 열어 등록해
    두면 이 프로그램 탭3에서 그대로 불러온다(같은 bioled_presets.json 공유).


2. 창 상단
──────────
  - "Dry-run(장비 없이 로직만)": 체크돼 있으면 실제 명령을 장비로 보내지
    않고 로그만 찍는다. 처음 눌러볼 때, 또는 장비 없이 화면 흐름만 확인할
    때 켜둘 것. 실제 측정을 하려면 반드시 체크 해제.
  - "Keithley 연결" / "BioLED 연결": 각각 따로 연결한다. 연결 성공 시 로그에
        [4200] 연결 (DLL): ret=1, socket_err=0
        [4200] 응답: KI4200 V9.1-SP1
    가 뜨면 정상. ret=1이 정상이고 0이 아니라는 점 주의(직관과 반대).


3. 탭별 사용법
──────────────
  [0. 사용법] — 지금 보고 있는 이 탭.

  [1. SMU 구성] — 소자에 실제로 연결된 배선대로 채널을 정의하는 곳.
    - 채널/사용/전압이름/전류이름/소스모드/소스함수를 채우고
      "4200에 적용(DE 전송)"을 누르면 그 즉시 장비에 채널 정의가 전송된다.
    - 전압/전류 "이름"은 반드시 6글자 이하! (Keithley 매뉴얼 제한, 넘기면
      조용히 Syntax Error가 나서 데이터가 안 잡힌다 — 6글자 넘으면 프로그램이
      자동으로 잘라주고 로그에 경고를 남긴다)
    - 소스모드를 Common(3)으로 바꾸면 소스함수가 자동으로 Constant(3)로
      고정된다 (매뉴얼 규칙).
    - 기본값은 실측 예시 파일에서 확인된 배선(SMU1=Common, SMU2=전압스윕)으로
      채워져 있다. 실제 소자 배선이 다르면 여기서 바꾸면 된다.
    - "설정 저장"을 누르면 station_config.json에 저장되어 다음 실행 때도
      그대로 유지된다.

  [2. 측정 설정] — Dark(음/양 분리 2회) / 광전류(한 번에 스윕) 값, 적분시간,
    분해능, Range I 방식을 정하는 곳. "프리셋"으로 이름 붙여 여러 세트를
    저장/전환할 수 있다(예: 저잡음용 vs 빠른측정용).
    - **적분시간(IT)**: 한 점을 잴 때 SMU가 신호를 얼마나 오래 평균化(적분)
      하는지. Short(가장 빠름, 노이즈 큼) → Medium → Long(가장 느림, 가장
      깨끗함) 순. 전원 노이즈(60Hz/50Hz)를 걸러내려고 PLC(Power Line Cycle)
      단위로 적분한다 — Custom을 쓰면 지연/필터/PLC를 직접 지정 가능.
    - **분해능(RS, 3~7 digits)**: 한 번 읽은 값의 유효자릿수. 낮으면(3자리)
      빠르고 거칠고, 높으면(7자리) 느리지만 미세한 전류 차이까지 구분된다.
      적분시간과 별개 설정이지만 둘 다 "느릴수록 깨끗하다"는 같은 트레이드오프.
    - **Range I**: 전류계가 사용할 고정 범위(예: 10uA). 이 범위를 넘는 전류가
      들어오면 컴플라이언스에 걸려 값이 그 이상 못 올라가고 클리핑된다 —
      그래서 광전류들의 최댓값보다는 크게, 그러나 노이즈 바닥을 위해 가능한
      한 작게 잡아야 한다(1번 프로토콜 규칙과 동일한 이유).
    - **컴플라이언스 확인**: 트레이스마다 CSV/엑셀에 "Status" 열이 같이
      저장된다. 각 점 앞에 KXCI가 붙이는 상태 코드('N'=Normal 추정, 그 외
      문자는 컴플라이언스/오버플로 가능성)를 그대로 옮겨 적은 것이다. 측정
      직후 로그에도 "⚠ N개 포인트 상태코드가 'N'이 아님"으로 요약되어 뜬다.
      ⚠ 정확한 코드별 의미는 아직 매뉴얼로 100% 확인 전이니, 애매하면
      Reference Manual의 상태 문자 표와 대조할 것.
    - Range I 모드: RI(즉시 고정)를 우선 시도하고, 장비가 문법 오류를 내면
      자동으로 RG(하한만 지정)로 바꿔 다시 보낸다 — 로그에
          ⚠ RI2 Syntax Error — RG2로 폴백
      이 보이면 정상 동작이다(에러가 아니라 자동 복구가 실행된 것). 이미
      실기에서 이 장비는 RG로 폴백해야 한다는 게 확인됐다.

  [3. 측정 실행] — 실제로 스윕을 실행하는 화면.
    - "새 세션 시작"을 먼저 눌러야 측정 버튼들이 동작한다(세션 = 하나의
      샘플에 대한 측정 묶음, sessions\\폴더에 즉시 CSV로 백업됨).
    - 파장 드롭다운은 "8: 940 nm"처럼 분석 앱 브래킷 코드 번호를 같이 보여주고,
      큰 파장(940)이 위로 오도록 정렬돼 있다.
    - "OD(ND필터)" 칸으로 세기 프리셋을 OD별로 나눠 관리한다. ND 필터는
      사람이 손으로 끼우는 것이라 프로그램이 알 수 없지만, 같은 %라도 OD가
      다르면 실제 광량이 다르므로 "이 파장 · 이 OD"로 묶어서 등록해야
      나중에 헷갈리지 않는다. 새 OD 값(예: OD2)은 그 칸에 직접 입력하고
      "+ 현재 세기를 프리셋으로"를 누르면 새로 생긴다.

    - ★ "실시간 세기 조절" — BioLED 전용 소프트웨어를 따로 띄울 필요 없이
      여기서 바로 광량을 맞춘다. 사용 순서:
        ① 파장·OD 선택 → ② "켜기" → ③ 슬라이더를 드래그하거나 숫자칸을
        클릭하고 ↑/↓ 키로 0.1 %씩 미세조정 (BioLED에 즉시 반영됨)
        → ④ 파워미터가 원하는 값(예: 1 mW)을 가리키면
        → ⑤ "+ 현재 세기를 프리셋으로" 클릭 → 이름만 입력(예: `1 mW`)
      **세기를 다시 타이핑할 필요가 없다** — 지금 슬라이더에 있는 값이 그대로
      저장된다. 이름 입력창은 **커서가 자동으로 들어가 있어** 바로 타이핑하면
      되고, Enter로 확인 / Esc로 취소된다.
      · 켠 상태에서 파장을 바꾸면 이전 파장은 자동으로 꺼진다(광원 하나만 켜짐).
      · 측정을 실행하면 측정 쪽이 광원을 제어하고 끝나면 꺼지므로, 실시간
        조절도 자동으로 해제된다.
    - 프리셋은 cli_tools\\bioled_controller.py와 같은 파일을 공유하므로 거기서
      등록한 것도 그대로 보인다(그쪽도 OD별로 나뉘어 있다). 파장·OD를 바꾸면
      그 조합에 등록된 프리셋만 자동으로 드롭다운에 나타난다.
    - "프리셋 수정" / "프리셋 삭제"는 드롭다운에서 프리셋을 고른 뒤 누른다.
    - Dark 0→−1V / Dark 0→+1V / 선택 광원 I-V 버튼으로 한 트레이스씩 쌓는다.
    - 오른쪽 그래프에 측정된 트레이스가 |전류| 로그스케일로 즉시 겹쳐 그려진다
      (KITE 화면처럼 누적해서 볼 수 있다). 전류가 정확히 0으로 읽히면 그래프
      맨 아래에 평평한 선으로 표시된다(사라지지 않음 — "0으로 측정됐다"는
      뜻이지 "그래프가 고장났다"는 뜻이 아니다).
    - 목록에서 트레이스를 선택하면: 선택 삭제 / 라벨 수정 / 위·아래로 이동이
      가능하다. 실제 4200(KITE)은 실행·Append만 되고 중간 삭제나 시트 이름
      바꾸기가 안 되지만, 이 프로그램은 엑셀 파일을 우리가 직접 새로 만들기
      때문에 중간 트레이스를 지우거나 순서를 바꿔도 내보내기 결과에는 아무
      문제가 없다.
    - "엑셀 내보내기"를 누르기 전까지 위쪽 "샘플명" 입력란은 자유롭게 바꿀 수
      있고, 그 시점의 값이 파일명에 들어간다(세션 폴더 이름 자체는 세션을
      시작할 때 이름으로 고정되지만, 이건 내부 백업 폴더일 뿐 파일명과는 별개).
      트레이스 목록 아래 "내보낼 파일명" 칸에 실제로 저장될 이름이 실시간으로
      미리 보인다.
    - 브래킷 코드(예: dd4)는 분석 앱(pd_app)이 트레이스 라벨을 복원하는 데
      쓰는 코드다. 라벨을 바꾸거나 순서를 바꾸면 자동으로 다시 계산된다.

  [4. I-T 측정] — 시간에 따른 전류(암전류→광전류→암전류…) 측정. 파장과
    OD(ND필터)를 고르면 그 조합에 탭3(또는 bioled_controller.py)에서
    등록해둔 세기 프리셋을 낮은 세기부터 자동으로 순서대로 사용한다 —
    프리셋이 N개면 dark를 N+1번, light를 N번 자동으로 반복한다(설정을
    따로 또 입력할 필요 없음). OD 드롭다운에는 그 파장에 실제로 프리셋이
    등록된 OD만 나타난다 — 안 보이면 탭3에서 그 파장·OD로 먼저 등록할 것.
    아직 실기로 한 번도 돌려보지 않은 탭이다 — 처음 쓸 때는 꼭 Dry-run으로
    먼저 흐름을 확인할 것.


4. 로그 읽는 법
───────────────
  - 일반 텍스트: 정상 진행 상황
  - "⚠"로 시작: 경고. 대부분 자동으로 복구되거나(RI→RG 폴백 등) 그냥 참고만
    하면 되는 것들이지만, 반복되면 원인을 봐야 한다.
  - "✘ 오류:": 실제로 동작이 중단된 경우. 메시지를 그대로 캡처해서 물어볼 것.
  - "[DO '이름'] raw=...": 장비가 실제로 돌려준 원본 응답. 트레이스가 "0점"
    으로 나오면 이 줄에 무엇이 찍혔는지가 원인 파악의 핵심 단서다.
  - "N개 포인트 상태코드가 'N'이 아님": 컴플라이언스/오버플로가 의심되는
    점이 있다는 뜻. CSV/엑셀의 Status 열에서 정확히 몇 번째 점인지 볼 수 있다.
  - 로그 창과 위쪽 탭 영역 사이의 경계선을 마우스로 드래그하면 로그 창
    높이를 원하는 대로 조절할 수 있다.


5. 문제가 생기면
────────────────
  - 이 파일과 같은 폴더의 HANDOFF_keithley_automation.md 에 지금까지 겪은
    문제/해결/실패 기록이 전부 있다. 특히 "3. 실패한 접근" 절에 적힌 방법은
    이미 안 되는 게 확인된 것들이니 다시 시도하지 말 것.
  - cli_tools\\kxci_dll_test.py 로 DLL 연결 자체만 따로 점검할 수 있다.
"""


# ==========================================================
# GUI
# ==========================================================
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("PD 측정 스테이션 — Keithley 4200 + BioLED")
        self.geometry("1280x900")
        # 탭3의 파장/OD/프리셋/버튼 한 줄, 탭1의 8열 SMU 표 등이 이보다 좁으면
        # 버튼이나 안내문구가 잘린다 — 최소 크기를 강제해서 방지.
        self.minsize(1150, 780)

        self.station_cfg = load_json(STATION_CONFIG_FILE, DEFAULT_STATION_CONFIG)
        self.presets_cfg = load_json(STATION_PRESETS_FILE, DEFAULT_STATION_PRESETS)
        self.led_settings = load_json(BIOLED_SETTINGS_FILE, DEFAULT_BIOLED_SETTINGS)
        self.led_presets = normalize_led_presets(
            load_json(BIOLED_PRESETS_FILE, DEFAULT_BIOLED_PRESETS))
        self.it_cfg = load_json(IT_CONFIG_FILE, None)

        self.smu = None          # Keithley4200
        self.led = None          # BioLED
        self.session = None      # Session
        # Dry-run 상태를 껐다 켰다 했는데 앱을 재시작하면 기본값(True)으로
        # 되돌아가서 "분명 껐는데 왜 로그가 dry-run 형태로 나오지" 하고 혼란을
        # 겪을 수 있다 — station_config.json에 저장해 재시작해도 유지되게 함.
        self.dry_run = tk.BooleanVar(value=self.station_cfg.get("dry_run", True))
        self.dry_run.trace_add("write", lambda *_: self._on_dry_run_change())
        self.q = queue.Queue()   # 워커 스레드 -> UI 로그
        self.busy = False
        # 실시간 광원 세기 조절 상태 (슬라이더 드래그는 이벤트가 초당 수십 번
        # 발생하므로 debounce 후 마지막 값만 장치로 보낸다)
        self._live_after_id = None
        self._live_is_on = False
        self._live_wl = None     # 현재 실제로 출력 중인 파장(파장 전환 시 이전 채널 소등용)
        self._live_applying = False   # 스냅용 set()의 재진입 방지
        self._live_error = None       # 마지막 적용 실패 사유(예외 대신 여기 담음)

        self._build()
        self._on_dry_run_change()
        self._refresh_live_state()   # 시작 시 '● BioLED 미연결'로 표시
        self._drain_after_id = self.after(150, self._drain_queue)

    def _on_dry_run_change(self):
        self.station_cfg["dry_run"] = self.dry_run.get()
        save_json(STATION_CONFIG_FILE, self.station_cfg)
        if self.dry_run.get():
            self.dry_banner.config(
                text="🔶 DRY-RUN 켜짐 — 실제 장비로 명령을 보내지 않습니다",
                background="#fff3cd", foreground="#7a5b00")
        else:
            self.dry_banner.config(
                text="🔴 실측 모드 — 지금부터 실제 4200/BioLED로 명령이 나갑니다",
                background="#f8d7da", foreground="#7a1c1c")

    # ---------- 공통 ----------
    def log(self, msg):
        self.q.put(str(msg))

    def _drain_queue(self):
        try:
            while True:
                msg = self.q.get_nowait()
                self.log_text.insert("end", msg + "\n")
                self.log_text.see("end")
        except queue.Empty:
            pass
        self._drain_after_id = self.after(150, self._drain_queue)

    def _run_worker(self, fn, *args):
        if self.busy:
            messagebox.showwarning("측정 중", "이전 측정이 아직 끝나지 않았습니다.")
            return
        self.busy = True

        def _wrap():
            try:
                fn(*args)
            except Exception as e:  # noqa: BLE001
                self.log(f"✘ 오류: {e}")
            finally:
                self.busy = False

        threading.Thread(target=_wrap, daemon=True).start()

    def _build(self):
        self.dry_banner = tk.Label(self, text="", anchor="w", padx=8, pady=3,
                                   font=("", 9, "bold"))
        self.dry_banner.pack(fill="x")

        top = ttk.Frame(self, padding=6)
        top.pack(fill="x")
        ttk.Checkbutton(top, text="Dry-run(장비 없이 로직만)", variable=self.dry_run
                        ).pack(side="left")
        ttk.Label(top, text="   ").pack(side="left")
        # --- Keithley 상태 ---
        self.conn_status = ttk.Label(top, text="● Keithley 미연결", foreground="gray")
        self.conn_status.pack(side="left")
        ttk.Button(top, text="Keithley 연결", command=self.connect_smu).pack(side="left", padx=4)
        ttk.Separator(top, orient="vertical").pack(side="left", fill="y", padx=10)
        # --- BioLED 상태 (연결 여부를 한눈에) ---
        self.led_status = ttk.Label(top, text="● BioLED 미연결", foreground="gray")
        self.led_status.pack(side="left")
        ttk.Button(top, text="BioLED 연결", command=self.connect_led).pack(side="left", padx=4)
        ttk.Button(top, text="채널 설정", command=self.edit_led_channels).pack(side="left", padx=2)
        ttk.Separator(top, orient="vertical").pack(side="left", fill="y", padx=10)
        ttk.Button(top, text="모두 해제", command=self.disconnect_all).pack(side="left", padx=4)

        # 탭 영역과 로그 창 사이에 드래그 가능한 구분선(sash)을 둬서
        # 로그 창 높이를 사용자가 직접 조절할 수 있게 한다.
        paned = ttk.PanedWindow(self, orient="vertical")
        paned.pack(fill="both", expand=True, padx=8, pady=(0, 6))

        self.nb = ttk.Notebook(paned)
        self._build_tab_help()
        self._build_tab_smu()
        self._build_tab_measure()
        self._build_tab_run()
        self._build_tab_it()
        paned.add(self.nb, weight=6)   # 그래프가 세로로 눌리지 않게 탭 쪽에 더 배분

        bottom = ttk.Frame(paned, padding=6)
        ttk.Label(bottom, text="로그 (경계선을 위아래로 드래그하면 높이 조절)").pack(anchor="w")
        log_box = ttk.Frame(bottom)
        log_box.pack(fill="both", expand=True)
        log_scroll = ttk.Scrollbar(log_box, orient="vertical")
        self.log_text = tk.Text(log_box, height=8, yscrollcommand=log_scroll.set)
        log_scroll.config(command=self.log_text.yview)
        log_scroll.pack(side="right", fill="y")
        self.log_text.pack(side="left", fill="both", expand=True)
        paned.add(bottom, weight=1)

    # ---------- 연결 ----------
    # ⚠ 아래 두 핸들러는 `except Exception`이 아니라 `except BaseException`을
    # 쓴다. SystemExit/KeyboardInterrupt 같은 BaseException 직속 예외가 올라오면
    # tkinter 콜백 밖으로 조용히 빠져나가 **오류창도 없이 버튼이 먹통인 것처럼**
    # 보이기 때문. (실측 모드 연결 실패를 며칠간 못 찾은 원인이 정확히 이것)
    def connect_smu(self):
        if self.smu is not None:
            self.log("[4200] 이미 연결되어 있습니다 (해제 후 다시 연결하세요)")
            return
        self.log(f"[4200] 연결 시도... (dry_run={self.dry_run.get()}, {IP.decode()}:{PORT})")
        try:
            self.smu = Keithley4200(dry=self.dry_run.get(), log=self.log)
            self.conn_status.config(text="● Keithley 연결됨", foreground="green")
            self.log("[4200] 연결 완료")
        except BaseException as e:  # noqa: BLE001 — 위 주석 참조
            self.log(f"✘ Keithley 연결 실패: {type(e).__name__}: {e}")
            messagebox.showerror("연결 실패", f"{type(e).__name__}\n\n{e}")

    def connect_led(self):
        if self.led is not None:
            self.log("[LED] 이미 연결되어 있습니다")
            return
        self.log(f"[LED] 연결 시도... (dry_run={self.dry_run.get()})")
        try:
            self.led = BioLED(dry=self.dry_run.get(), log=self.log)
            self.log("[LED] 연결됨")
            nch = self.led.channels
            self.led_status.config(
                text=f"● BioLED 연결됨 (ch 1~{nch})" if nch else "● BioLED 연결됨",
                foreground="green")
            self._warn_channel_mapping(nch)
            self._refresh_live_state()
        except BaseException as e:  # noqa: BLE001
            self.log(f"✘ BioLED 연결 실패: {type(e).__name__}: {e}")
            messagebox.showerror(
                "BioLED 연결 실패",
                f"{type(e).__name__}\n\n{e}\n\nBLS 박스 전원이 켜져 있는지, "
                "USB 케이블이 데이터선 포함인지, "
                "BioLEDController.exe가 완전히 종료됐는지 확인하세요.")

    def disconnect_all(self):
        if self.smu:
            self.smu.close()
            self.smu = None
            self.conn_status.config(text="● 미연결", foreground="gray")
        if self.led:
            # 해제 전에 실시간 출력부터 끈다 — 광원이 켜진 채 연결만 끊기면
            # 프로그램에서 더 이상 끌 방법이 없어진다.
            try:
                self.live_off()
            except Exception:  # noqa: BLE001
                pass
            self.led.close()
            self.led = None
            self.led_status.config(text="● BioLED 미연결", foreground="gray")
        self._live_is_on = False
        self._live_wl = None
        self._refresh_live_state()

    def _warn_channel_mapping(self, nch):
        """장비 채널 수보다 큰 번호로 배정된 파장이 있으면 미리 경고한다.
        (예전에는 없는 채널로 명령을 보내 ret=-1만 뜨고 원인을 알 수 없었다)"""
        if not nch or nch <= 0:
            return
        bad = [PRETTY_LABEL[wl] for wl, info in self.led_settings.get("channels", {}).items()
               if wl in PRETTY_LABEL and info.get("channel", 0) > nch]
        if bad:
            self.log(f"[LED] ⚠ 이 장비는 채널이 {nch}개뿐인데 다음 파장이 그보다 큰 번호로 "
                    f"배정돼 있습니다: {', '.join(bad)} — 상단 '채널 설정'에서 고치세요.")

    # ======================================================
    # 탭 0 · 사용법
    # ======================================================
    def _build_tab_help(self):
        frame = ttk.Frame(self.nb, padding=10)
        self.nb.add(frame, text="0. 사용법")

        box = ttk.Frame(frame)
        box.pack(fill="both", expand=True)
        scroll = ttk.Scrollbar(box, orient="vertical")
        text = tk.Text(box, wrap="word", yscrollcommand=scroll.set,
                       font=("", 10), padx=10, pady=8, background="#fdfdfd")
        scroll.config(command=text.yview)
        scroll.pack(side="right", fill="y")
        text.pack(side="left", fill="both", expand=True)
        text.insert("1.0", HELP_TEXT)
        text.config(state="disabled")

    # ======================================================
    # 탭 1 · SMU 구성
    # ======================================================
    def _build_tab_smu(self):
        frame = ttk.Frame(self.nb, padding=10)
        self.nb.add(frame, text="1. SMU 구성")

        cols = ("ch", "use", "vname", "iname", "mode", "func", "const_v", "const_c")
        headers = ["채널", "사용", "전압이름", "전류이름", "소스모드", "소스함수",
                   "Const 출력값", "Const 컴플라이언스(A)"]
        for j, h in enumerate(headers):
            ttk.Label(frame, text=h, font=("", 9, "bold")).grid(row=0, column=j, padx=3, pady=3)

        self.smu_rows = []
        chans = self.station_cfg["smu_channels"]
        mode_opts = ["1:전압원", "2:전류원", "3:Common"]
        func_opts = ["1:VAR1스윕", "2:VAR2스텝", "3:Constant", "4:VAR1'"]

        for i, c in enumerate(chans):
            r = i + 1
            ttk.Label(frame, text=str(c["ch"])).grid(row=r, column=0)
            use_var = tk.BooleanVar(value=c["enabled"])
            ttk.Checkbutton(frame, variable=use_var).grid(row=r, column=1)
            vname_var = tk.StringVar(value=c["vname"])
            ttk.Entry(frame, textvariable=vname_var, width=8).grid(row=r, column=2)
            iname_var = tk.StringVar(value=c["iname"])
            ttk.Entry(frame, textvariable=iname_var, width=8).grid(row=r, column=3)
            mode_var = tk.StringVar(value=mode_opts[c["mode"] - 1])
            mode_cb = ttk.Combobox(frame, textvariable=mode_var, values=mode_opts,
                                   width=10, state="readonly")
            mode_cb.grid(row=r, column=4)
            func_var = tk.StringVar(value=func_opts[c["func"] - 1])
            func_cb = ttk.Combobox(frame, textvariable=func_var, values=func_opts,
                                   width=11, state="readonly")
            func_cb.grid(row=r, column=5)
            cv_var = tk.DoubleVar(value=c.get("const_value", 0.0))
            ttk.Entry(frame, textvariable=cv_var, width=10).grid(row=r, column=6)
            cc_var = tk.DoubleVar(value=c.get("const_compliance", 1e-3))
            ttk.Entry(frame, textvariable=cc_var, width=14).grid(row=r, column=7)

            row = {"ch": c["ch"], "use": use_var, "vname": vname_var, "iname": iname_var,
                   "mode": mode_var, "func": func_var, "cv": cv_var, "cc": cc_var}
            self.smu_rows.append(row)

            def on_mode_change(_e=None, mv=mode_var, fv=func_var, fcb=func_cb):
                if mv.get().startswith("3"):
                    fv.set(func_opts[2])  # Common -> Constant 강제
                    fcb.config(state="disabled")
                else:
                    fcb.config(state="readonly")
            mode_cb.bind("<<ComboboxSelected>>", on_mode_change)
            on_mode_change()

        btns = ttk.Frame(frame)
        btns.grid(row=len(chans) + 1, column=0, columnspan=8, pady=10, sticky="w")
        ttk.Button(btns, text="설정 저장", command=self.save_smu_config).pack(side="left", padx=4)
        ttk.Button(btns, text="4200에 적용(DE 전송)", command=self.apply_smu_config
                  ).pack(side="left", padx=4)
        ttk.Label(frame, text="Common(3)을 고르면 소스함수는 자동으로 Constant(3)로 고정됩니다.",
                  foreground="gray").grid(row=len(chans) + 2, column=0, columnspan=8, sticky="w")

    def _collect_smu_channels(self):
        chans = []
        for row in self.smu_rows:
            mode = int(row["mode"].get().split(":")[0])
            func = int(row["func"].get().split(":")[0])
            if mode == 3:
                func = 3
            vname = row["vname"].get().strip() or f"V{row['ch']}"
            iname = row["iname"].get().strip() or f"I{row['ch']}"
            # 매뉴얼 표기 'BBBBBB'/'CCCCCC' = 6글자. 넘기면 DE 정의가 조용히
            # Syntax Error 날 수 있음(실기에서 확인) — 눈치채기 전에 여기서 자른다.
            if len(vname) > 6 or len(iname) > 6:
                self.log(f"    ⚠ 채널{row['ch']} 이름이 6자를 넘어 잘림: "
                        f"'{vname}'/'{iname}' -> '{vname[:6]}'/'{iname[:6]}'")
                vname, iname = vname[:6], iname[:6]
            chans.append({
                "ch": row["ch"], "enabled": row["use"].get(),
                "vname": vname, "iname": iname,
                "mode": mode, "func": func,
                "const_value": row["cv"].get(), "const_compliance": row["cc"].get(),
            })
        return chans

    def save_smu_config(self):
        self.station_cfg["smu_channels"] = self._collect_smu_channels()
        save_json(STATION_CONFIG_FILE, self.station_cfg)
        self.log("[설정] SMU 구성 저장됨")

    def apply_smu_config(self):
        if self.smu is None:
            messagebox.showwarning("미연결", "먼저 Keithley를 연결하세요.")
            return
        chans = self._collect_smu_channels()
        self._run_worker(self._apply_smu_config_worker, chans)

    def _apply_smu_config_worker(self, chans):
        self.smu.configure_channels(chans)
        self.log("[SMU] 채널 정의(DE) 전송 완료")

    def _sweep_channel(self, chans):
        cands = [c for c in chans if c["enabled"] and c["func"] == 1]
        if not cands:
            raise ValueError("VAR1(스윕) 채널이 설정되어 있지 않습니다 (탭1에서 확인).")
        return cands[0]

    # ======================================================
    # 탭 2 · 측정 설정
    # ======================================================
    def _build_tab_measure(self):
        frame = ttk.Frame(self.nb, padding=10)
        self.nb.add(frame, text="2. 측정 설정")

        p = self.presets_cfg["presets"][self.presets_cfg["active_preset"]]

        def sweep_block(parent, title, key, row0):
            ttk.Label(parent, text=title, font=("", 9, "bold")).grid(
                row=row0, column=0, sticky="w", pady=(8, 2))
            v = {}
            labels = ["시작 V", "종료 V", "스텝 V", "컴플라이언스 A"]
            keys = ["start", "stop", "step", "compliance"]
            for j, (lb, k) in enumerate(zip(labels, keys)):
                ttk.Label(parent, text=lb).grid(row=row0 + 1, column=j, sticky="w")
                var = tk.DoubleVar(value=p[key][k])
                ttk.Entry(parent, textvariable=var, width=10).grid(row=row0 + 2, column=j, padx=3)
                v[k] = var
            return v

        self.mvars = {}
        self.mvars["dark_neg"] = sweep_block(frame, "Dark 0→−1V", "dark_neg", 0)
        self.mvars["dark_pos"] = sweep_block(frame, "Dark 0→+1V", "dark_pos", 3)
        self.mvars["photo"] = sweep_block(frame, "광전류 −1→+1V (한번에)", "photo", 6)

        r = 9
        ttk.Label(frame, text="스윕 타입", font=("", 9, "bold")).grid(row=r, column=0, sticky="w", pady=(10, 2))
        sweep_opts = SWEEP_OPTS
        self.sweep_type_var = tk.StringVar(value=sweep_opts[p["sweep_type"] - 1])
        ttk.Combobox(frame, textvariable=self.sweep_type_var, values=sweep_opts,
                    width=10, state="readonly").grid(row=r, column=1, sticky="w")

        r += 1
        ttk.Label(frame, text="적분시간(IT)", font=("", 9, "bold")).grid(row=r, column=0, sticky="w", pady=(10, 2))
        it_opts = IT_OPTS
        self.it_mode_var = tk.StringVar(value=it_opts[p["integration"]["mode"] - 1])
        it_cb = ttk.Combobox(frame, textvariable=self.it_mode_var, values=it_opts,
                             width=10, state="readonly")
        it_cb.grid(row=r + 1, column=0, sticky="w")
        ttk.Label(frame, text="지연계수(0~100)").grid(row=r + 1, column=1)
        self.it_delay_var = tk.DoubleVar(value=p["integration"]["delay"])
        ttk.Entry(frame, textvariable=self.it_delay_var, width=8).grid(row=r + 1, column=2)
        ttk.Label(frame, text="필터계수(0~100)").grid(row=r + 1, column=3)
        self.it_filter_var = tk.DoubleVar(value=p["integration"]["filter"])
        ttk.Entry(frame, textvariable=self.it_filter_var, width=8).grid(row=r + 1, column=4)
        ttk.Label(frame, text="A/D 적분(PLC)").grid(row=r + 1, column=5)
        self.it_plc_var = tk.DoubleVar(value=p["integration"]["plc"])
        ttk.Entry(frame, textvariable=self.it_plc_var, width=8).grid(row=r + 1, column=6)

        r += 2
        ttk.Label(frame, text="분해능(RS, 3~7 digits)", font=("", 9, "bold")).grid(
            row=r, column=0, sticky="w", pady=(10, 2))
        self.resolution_var = tk.IntVar(value=p["resolution_digits"])
        ttk.Spinbox(frame, from_=3, to=7, textvariable=self.resolution_var, width=6).grid(
            row=r + 1, column=0, sticky="w")

        r += 2
        ttk.Label(frame, text="Range I", font=("", 9, "bold")).grid(row=r, column=0, sticky="w", pady=(10, 2))
        range_opts = ["auto", "RI", "RG"]
        self.range_mode_var = tk.StringVar(value=p["range_mode"])
        ttk.Combobox(frame, textvariable=self.range_mode_var, values=range_opts,
                    width=8, state="readonly").grid(row=r + 1, column=0, sticky="w")
        range_val_opts = [RANGE_LABELS[v] for v in FIXED_RANGES_A]
        self.range_val_var = tk.StringVar(value=RANGE_LABELS.get(p["range_A"], range_val_opts[0]))
        ttk.Combobox(frame, textvariable=self.range_val_var, values=range_val_opts,
                    width=10, state="readonly").grid(row=r + 1, column=1, sticky="w")
        self.range_dark_same_var = tk.BooleanVar(value=p["range_dark_same"])
        ttk.Checkbutton(frame, text="Dark도 동일 Range 적용",
                        variable=self.range_dark_same_var).grid(row=r + 1, column=2, columnspan=2, sticky="w")

        self.rc_note_lbl = ttk.Label(frame, foreground="#555", wraplength=900, justify="left", text="")
        self.rc_note_lbl.grid(row=r + 2, column=0, columnspan=7, sticky="w", pady=(4, 0))

        # Range ↔ 컴플라이언스 양방향 자동 보정 (KITE와 동일한 동작).
        # 위젯이 다 만들어진 뒤에 연결해야 초기화 도중 콜백이 터지지 않는다.
        self.range_mode_var.trace_add("write", lambda *_: self._sync_range_compliance("range"))
        self.range_val_var.trace_add("write", lambda *_: self._sync_range_compliance("range"))
        for key in ("dark_neg", "dark_pos", "photo"):
            self.mvars[key]["compliance"].trace_add(
                "write", lambda *_: self._sync_range_compliance("compliance"))
        self._sync_range_compliance("init")

        r += 2
        btns = ttk.Frame(frame)
        btns.grid(row=r, column=0, columnspan=7, pady=14, sticky="w")
        ttk.Label(btns, text="프리셋:").pack(side="left")
        self.preset_name_var = tk.StringVar(value=self.presets_cfg["active_preset"])
        self.preset_combo = ttk.Combobox(btns, textvariable=self.preset_name_var,
                                         values=list(self.presets_cfg["presets"].keys()),
                                         width=16, state="readonly")
        self.preset_combo.pack(side="left", padx=4)
        ttk.Button(btns, text="불러오기", command=self.load_preset).pack(side="left", padx=4)
        ttk.Button(btns, text="다른 이름으로 저장", command=self.save_preset_as).pack(side="left", padx=4)
        ttk.Button(btns, text="현재 프리셋에 저장", command=self.save_preset).pack(side="left", padx=4)

    def _current_range_A(self):
        for r in FIXED_RANGES_A:
            if RANGE_LABELS[r] == self.range_val_var.get():
                return r
        return FIXED_RANGES_A[0]

    def _sync_range_compliance(self, source):
        """Range I ↔ 컴플라이언스 양방향 자동 보정 (KITE와 동일한 동작).

        제약: 컴플라이언스 ≤ Range × 1.05. 고정 레인지(RI)일 때만 구속력이
        있으므로 그 모드에서만 값을 건드린다.
          - Range를 바꾸면  -> 범위를 넘는 컴플라이언스를 상한으로 클램프
          - 컴플라이언스를 바꾸면 -> 그걸 담을 수 있는 최소 Range로 상향
        Range는 스윕 3종이 공유하므로, 상향 판단은 **가장 큰 컴플라이언스**
        기준으로 한다.
        """
        if getattr(self, "_rc_syncing", False):
            return  # 한쪽을 고치면 다른 쪽 trace가 다시 불려 무한루프가 된다
        keys = ("dark_neg", "dark_pos", "photo")
        try:
            comps = {k: self.mvars[k]["compliance"].get() for k in keys}
            range_A = self._current_range_A()
        except Exception:  # noqa: BLE001 — 입력칸을 지우는 중이면 get()이 실패한다
            return

        if self.range_mode_var.get() != "RI":
            self.rc_note_lbl.config(
                text="※ 고정 레인지(RI)가 아니면 Range↔컴플라이언스 자동 보정을 하지 않습니다.")
            return

        self._rc_syncing = True
        try:
            if source in ("range", "init"):
                cap = max_compliance_for(range_A)
                for k in keys:
                    if comps[k] > cap * (1 + 1e-9):
                        self.mvars[k]["compliance"].set(cap)
                        self.log(f"[설정] {k} 컴플라이언스 {comps[k]:g} A → {cap:g} A 자동 조정 "
                                f"(Range {format_range_i(range_A)}의 105% 상한)")
            else:  # compliance
                need = max(comps.values())
                new_r = min_range_for(need)
                if new_r > range_A:
                    self.range_val_var.set(RANGE_LABELS[new_r])
                    self.log(f"[설정] 컴플라이언스 {need:g} A를 담기 위해 Range I "
                            f"{format_range_i(range_A)} → {format_range_i(new_r)} 자동 상향")
                    range_A = new_r
        finally:
            self._rc_syncing = False

        cap = max_compliance_for(self._current_range_A())
        self.rc_note_lbl.config(
            text=f"※ 고정 레인지(RI) 규칙: 컴플라이언스 ≤ Range × 1.05. "
                 f"현재 Range {format_range_i(self._current_range_A())} → 컴플라이언스 상한 {cap:g} A. "
                 "Range를 바꾸면 초과분이 자동으로 낮춰지고, 컴플라이언스를 키우면 Range가 자동으로 올라갑니다.")

    def _collect_measure_settings(self):
        def sw(key):
            v = self.mvars[key]
            return {k: var.get() for k, var in v.items()}

        range_A = next(r for r in FIXED_RANGES_A if RANGE_LABELS[r] == self.range_val_var.get())
        return {
            "dark_neg": sw("dark_neg"), "dark_pos": sw("dark_pos"), "photo": sw("photo"),
            "sweep_type": int(self.sweep_type_var.get().split(":")[0]),
            "integration": {
                "mode": int(self.it_mode_var.get().split(":")[0]),
                "delay": self.it_delay_var.get(), "filter": self.it_filter_var.get(),
                "plc": self.it_plc_var.get(),
            },
            "resolution_digits": self.resolution_var.get(),
            "range_mode": self.range_mode_var.get(),
            "range_A": range_A,
            "range_dark_same": self.range_dark_same_var.get(),
        }

    def save_preset(self):
        name = self.presets_cfg["active_preset"]
        self.presets_cfg["presets"][name] = self._collect_measure_settings()
        save_json(STATION_PRESETS_FILE, self.presets_cfg)
        self.log(f"[프리셋] '{name}' 저장됨")

    def save_preset_as(self):
        name = self._ask_focused("프리셋 저장", "새 프리셋 이름:")
        if not name:
            return
        self.presets_cfg["presets"][name] = self._collect_measure_settings()
        self.presets_cfg["active_preset"] = name
        save_json(STATION_PRESETS_FILE, self.presets_cfg)
        self.preset_combo.config(values=list(self.presets_cfg["presets"].keys()))
        self.preset_name_var.set(name)
        self.log(f"[프리셋] '{name}' 이름으로 저장됨")

    def load_preset(self):
        name = self.preset_name_var.get()
        p = self.presets_cfg["presets"].get(name)
        if not p:
            return
        self.presets_cfg["active_preset"] = name
        for key in ("dark_neg", "dark_pos", "photo"):
            for k, var in self.mvars[key].items():
                var.set(p[key][k])
        self.sweep_type_var.set(SWEEP_OPTS[p["sweep_type"] - 1])
        self.it_mode_var.set(IT_OPTS[p["integration"]["mode"] - 1])
        self.it_delay_var.set(p["integration"]["delay"])
        self.it_filter_var.set(p["integration"]["filter"])
        self.it_plc_var.set(p["integration"]["plc"])
        self.resolution_var.set(p["resolution_digits"])
        self.range_mode_var.set(p["range_mode"])
        self.range_val_var.set(RANGE_LABELS.get(p["range_A"], RANGE_LABELS[FIXED_RANGES_A[0]]))
        self.range_dark_same_var.set(p["range_dark_same"])
        self.log(f"[프리셋] '{name}' 불러옴")

    # ======================================================
    # 탭 3 · 측정 실행
    # ======================================================
    def _build_tab_run(self):
        frame = ttk.Frame(self.nb, padding=10)
        self.nb.add(frame, text="3. 측정 실행")

        top = ttk.Frame(frame)
        top.pack(fill="x")
        ttk.Label(top, text="샘플명").grid(row=0, column=0, sticky="w")
        self.sample_name_var = tk.StringVar(value=self.station_cfg["sample_name"])
        ttk.Entry(top, textvariable=self.sample_name_var, width=20).grid(row=0, column=1, padx=4)
        ttk.Button(top, text="새 세션 시작", command=self.start_session).grid(row=0, column=2, padx=6)
        self.session_lbl = ttk.Label(top, text="세션: (없음)")
        self.session_lbl.grid(row=0, column=3, padx=10)

        # Dark 버튼은 별도 LabelFrame 없이 세션 줄에 붙인다 — 세로 공간을 아껴
        # 그래프에 넘겨주기 위함(예전엔 이 프레임 하나가 60px 가까이 먹었다).
        ttk.Separator(top, orient="vertical").grid(row=0, column=4, sticky="ns", padx=10)
        ttk.Button(top, text="Dark 0→−1V 측정",
                  command=lambda: self._run_worker(self._measure_dark, "neg")
                  ).grid(row=0, column=5, padx=3)
        ttk.Button(top, text="Dark 0→+1V 측정",
                  command=lambda: self._run_worker(self._measure_dark, "pos")
                  ).grid(row=0, column=6, padx=3)

        light_frame = ttk.LabelFrame(frame, text="광전류 (−1→+1V, 한번에)", padding=8)
        light_frame.pack(fill="x", pady=(6, 4))
        ttk.Label(light_frame, text="파장(브래킷 코드)").grid(row=0, column=0, sticky="w")
        self.wl_var = tk.StringVar(value=WL_DISPLAY[WAVELENGTHS[0]])
        ttk.Combobox(light_frame, textvariable=self.wl_var,
                    values=[WL_DISPLAY[wl] for wl in WAVELENGTHS],
                    width=10, state="readonly").grid(row=0, column=1, padx=4, pady=2)
        ttk.Label(light_frame, text="OD(ND필터)").grid(row=0, column=2, sticky="w")
        self.od_var = tk.StringVar(value=DEFAULT_OD)
        self.od_combo = ttk.Combobox(light_frame, textvariable=self.od_var, width=8)
        self.od_combo.grid(row=0, column=3, padx=4, pady=2)
        ttk.Label(light_frame, text="세기 프리셋").grid(row=0, column=4, sticky="w")
        self.preset_pct_var = tk.StringVar()
        self.pct_combo = ttk.Combobox(light_frame, textvariable=self.preset_pct_var,
                                      width=14, state="readonly")
        self.pct_combo.grid(row=0, column=5, padx=4, pady=2)
        ttk.Button(light_frame, text="선택 광원 I-V 측정",
                  command=lambda: self._run_worker(self._measure_photo)
                  ).grid(row=0, column=6, padx=(16, 0), pady=2)

        # ---- 실시간 세기 조절 (파워미터 보면서 맞추고 그대로 프리셋 저장) ----
        live = ttk.LabelFrame(light_frame, text="실시간 세기 조절", padding=6)
        live.grid(row=1, column=0, columnspan=7, sticky="ew", pady=(6, 2))

        self.live_pct_var = tk.DoubleVar(value=0.0)
        self.live_scale = ttk.Scale(live, from_=0.0, to=100.0, orient="horizontal",
                                    variable=self.live_pct_var, length=260,
                                    command=lambda _v: self._on_live_scale())
        self.live_scale.grid(row=0, column=0, padx=(0, 8), pady=2)

        # Spinbox는 위/아래 화살표키가 기본 동작이라 미세조정에 유리.
        # 슬라이더(드래그)와 같은 변수를 공유해 양쪽이 항상 동기화된다.
        self.live_spin = ttk.Spinbox(live, from_=0.0, to=100.0, increment=0.1,
                                     textvariable=self.live_pct_var, width=8,
                                     format="%.1f", command=self._apply_live_percent)
        self.live_spin.grid(row=0, column=1, pady=2)
        ttk.Label(live, text="%").grid(row=0, column=2, padx=(2, 10))

        self.live_on_btn = ttk.Button(live, text="켜기", width=6, command=self.live_on)
        self.live_on_btn.grid(row=0, column=3, padx=2)
        self.live_off_btn = ttk.Button(live, text="끄기", width=6, command=self.live_off)
        self.live_off_btn.grid(row=0, column=4, padx=2)
        # 지금 실제로 빛이 나오고 있는지를 항상 표시 (버튼만으로는 상태를 알 수 없음)
        self.live_state_lbl = tk.Label(live, text="○ 꺼짐", width=22, anchor="w",
                                       font=("", 9, "bold"), fg="#666")
        self.live_state_lbl.grid(row=0, column=5, padx=(10, 4))

        preset_row = ttk.Frame(live)
        preset_row.grid(row=1, column=0, columnspan=6, sticky="w", pady=(6, 0))
        ttk.Button(preset_row, text="+ 현재 세기를 프리셋으로", command=self.add_led_preset
                  ).pack(side="left", padx=(0, 4))
        ttk.Button(preset_row, text="프리셋 수정", command=self.edit_led_preset
                  ).pack(side="left", padx=4)
        ttk.Button(preset_row, text="프리셋 삭제", command=self.delete_led_preset
                  ).pack(side="left", padx=4)

        ttk.Label(live, foreground="gray", wraplength=1040, justify="left",
                 text="슬라이더 드래그 / 숫자칸 클릭 후 ↑↓키로 0.1 %씩 → 즉시 반영. 파워미터로 맞춘 뒤 "
                      "'+ 현재 세기를 프리셋으로'. OD = ND 필터 값(OD0=필터 없음), 새 OD는 직접 입력."
                 ).grid(row=2, column=0, columnspan=6, sticky="w", pady=(2, 0))

        # (실시간 조절 상태 변수는 __init__에서 초기화 — _build 도중 실패해도
        #  destroy -> disconnect_all 경로에서 AttributeError가 안 나도록)

        self.wl_var.trace_add("write", lambda *_: self._refresh_od_options())
        self.od_var.trace_add("write", lambda *_: self._refresh_led_presets())
        self._refresh_od_options()
        # ⚠ 내보내기 줄을 **mid보다 먼저** side="bottom"으로 배치한다.
        # 이렇게 해야 tkinter가 이 줄의 높이를 먼저 확보하고 남은 공간을 그래프에
        # 준다. 예전에는 이 컨트롤들이 목록 옆 버튼단 안에 있어서, 세로 공간이
        # 모자라면 조용히 잘려 "내보내기 버튼이 없다"고 보였다.
        export_bar = ttk.LabelFrame(frame, text="내보내기", padding=8)
        export_bar.pack(fill="x", side="bottom", pady=(6, 0))
        ttk.Button(export_bar, text="엑셀 내보내기", command=self.export_excel
                  ).pack(side="left", padx=(0, 12))
        self.bracket_lbl = ttk.Label(export_bar, text="브래킷: ", font=("", 9, "bold"))
        self.bracket_lbl.pack(side="left", padx=(0, 16))
        self.filename_lbl = ttk.Label(export_bar, text="내보낼 파일명: (없음)", foreground="#555")
        self.filename_lbl.pack(side="left")
        self.sample_name_var.trace_add("write", lambda *_: self._refresh_trace_list())

        mid = ttk.Frame(frame)
        mid.pack(fill="both", expand=True, pady=8)

        # 그래프에 폭을 몰아주기 위해 목록 쪽은 늘어나지 않게 고정(expand=False).
        list_frame = ttk.LabelFrame(mid, text="측정된 트레이스", padding=8)
        list_frame.pack(fill="y", expand=False, side="left")
        self.trace_tree = ttk.Treeview(list_frame, columns=("label", "range"),
                                       show="headings", height=8)
        self.trace_tree.heading("label", text="라벨")
        self.trace_tree.heading("range", text="Range I")
        self.trace_tree.column("label", width=90)
        self.trace_tree.column("range", width=70)
        self.trace_tree.pack(fill="y", expand=True, side="left")
        btn_col = ttk.Frame(list_frame)
        btn_col.pack(side="left", padx=8, fill="y")
        ttk.Button(btn_col, text="선택 삭제", command=self.delete_selected_trace).pack(pady=2, fill="x")
        ttk.Button(btn_col, text="라벨 수정", command=self.edit_selected_label).pack(pady=2, fill="x")
        ttk.Button(btn_col, text="위로 ▲", command=lambda: self.move_selected(-1)).pack(pady=2, fill="x")
        ttk.Button(btn_col, text="아래로 ▼", command=lambda: self.move_selected(1)).pack(pady=2, fill="x")
        ttk.Label(btn_col, text="중간 삭제·순서 변경\n모두 가능", foreground="gray",
                 justify="left").pack(pady=(8, 0), anchor="w")

        plot_frame = ttk.LabelFrame(mid, text="그래프 (누적, |I| 로그스케일, 8:10 비율)", padding=4)
        plot_frame.pack(fill="both", expand=True, side="left", padx=(8, 0))
        # 기본 크기도 8:10(가로:세로)으로 맞춘다. 창을 늘려도 비율이 깨지지
        # 않도록 실제 작도 영역은 _redraw_plot에서 다시 8:10으로 맞춘다.
        self.plot_canvas = tk.Canvas(plot_frame, width=400, height=500, background="white",
                                     highlightthickness=1, highlightbackground="#ccc")
        self.plot_canvas.pack(fill="both", expand=True)
        self.plot_canvas.bind("<Configure>", lambda e: self._redraw_plot())

    def _wl_key(self):
        """콤보박스에는 '8: 940 nm'처럼 브래킷 코드 번호를 붙여 보여주지만,
        내부적으로는 원래 키('940nm')로 되돌려써야 led_settings/it_config 등과 맞는다."""
        return WL_DISPLAY_TO_KEY.get(self.wl_var.get(), WAVELENGTHS[0])

    def _od_list(self, wl):
        ods = sorted(self.led_presets.get(wl, {}).keys())
        return ods or [DEFAULT_OD]

    def _refresh_od_options(self):
        wl = self._wl_key()
        ods = self._od_list(wl)
        self.od_combo.config(values=ods)
        if self.od_var.get() not in ods:
            self.od_var.set(ods[0])
        else:
            self._refresh_led_presets()

    def _refresh_led_presets(self):
        wl = self._wl_key()
        od = self.od_var.get().strip() or DEFAULT_OD
        presets = self.led_presets.get(wl, {}).get(od, [])
        vals = [f"{p['label']} ({p['percent']} %)" for p in presets]
        self.pct_combo.config(values=vals)
        if vals:
            self.pct_combo.current(0)
        else:
            self.preset_pct_var.set("")

    # ---------- 실시간 세기 조절 ----------
    def _on_live_scale(self):
        """슬라이더 드래그 중 호출. 이벤트가 매우 잦으므로 debounce."""
        if self._live_after_id:
            self.after_cancel(self._live_after_id)
        self._live_after_id = self.after(60, self._apply_live_percent)

    def _apply_live_percent(self):
        self._live_after_id = None
        if getattr(self, "_live_applying", False):
            return  # 스냅용 .set()이 Scale 콜백을 다시 부르는 재진입 방지
        pct = round(float(self.live_pct_var.get()), 1)
        # 슬라이더는 연속값이라 0.1 단위로 스냅해 표시/저장값을 깔끔하게 유지
        if abs(pct - float(self.live_pct_var.get())) > 1e-9:
            self._live_applying = True
            try:
                self.live_pct_var.set(pct)
            finally:
                self._live_applying = False
        if self.led is None or not self._live_is_on:
            self._refresh_live_state()
            return True  # 미연결이거나 '켜기' 전이면 값만 바꾸고 실제 출력은 안 건드림
        wl = self._wl_key()
        # ⚠ 여기서 예외를 던지면 안 된다 — 슬라이더 드래그는 after() 타이머
        # 콜백으로 들어오므로, 예외가 tkinter 밖으로 새면 화면에 아무것도 안
        # 뜨고 조용히 죽는다. 실패 사유는 _live_error에 담아 호출자가 쓴다.
        self._live_error = None
        try:
            # 켠 상태로 파장을 바꿨다면 이전 채널을 먼저 끈다
            # (단일 광원 측정 가정 — 두 파장이 동시에 켜지면 안 됨)
            if self._live_wl and self._live_wl != wl:
                self.led.off(self.led_settings["channels"][self._live_wl]["channel"])
                self.log(f"[LED] 파장 변경 — {PRETTY_LABEL[self._live_wl]} 끔")
            ch_info = self.led_settings["channels"][wl]
            self.led.set_percent(ch_info["channel"], pct)
            self._live_wl = wl
            return True
        except Exception as e:  # noqa: BLE001
            self._live_is_on = False
            self._live_wl = None
            self._live_error = e
            self.log(f"✘ LED 세기 적용 실패: {e}")
            return False
        finally:
            self._refresh_live_state()

    def _refresh_live_state(self):
        """'지금 빛이 나오고 있는가'를 화면에 항상 정확히 표시한다.
        버튼만 있으면 뭐가 눌린 상태인지 알 수 없어서 별도 표시가 필요하다."""
        if not hasattr(self, "live_state_lbl"):
            return
        if self.led is None:
            self.live_state_lbl.config(text="○ BioLED 미연결", fg="#999")
            self.live_on_btn.state(["disabled"])
            self.live_off_btn.state(["disabled"])
            return
        self.live_on_btn.state(["!disabled"])
        self.live_off_btn.state(["!disabled"])
        if self._live_is_on and self._live_wl:
            self.live_state_lbl.config(
                text=f"● 출력 중  {PRETTY_LABEL[self._live_wl]} @ {self.live_pct_var.get():.1f}%",
                fg="#0a7d28")
            self.live_on_btn.state(["disabled"])   # 이미 켜져 있음
        else:
            self.live_state_lbl.config(text="○ 꺼짐", fg="#666")
            self.live_off_btn.state(["disabled"])  # 이미 꺼져 있음

    def live_on(self):
        if self.led is None:
            messagebox.showwarning("미연결", "먼저 상단 'BioLED 연결'을 누르세요.")
            return
        self._live_is_on = True
        if not self._apply_live_percent():
            err = getattr(self, "_live_error", None)
            messagebox.showerror("LED 켜기 실패", str(err) if err else "알 수 없는 오류")
            return
        wl = self._wl_key()
        self.log(f"[LED] {PRETTY_LABEL[wl]} 실시간 조절 켜짐 @ {self.live_pct_var.get():.1f}% "
                "— 파워미터 보며 맞춘 뒤 '+ 현재 세기를 프리셋으로'")
        self._refresh_live_state()

    def live_off(self):
        self._live_is_on = False
        if self.led is None:
            self._live_wl = None
            self._refresh_live_state()
            return
        wl = self._live_wl or self._wl_key()
        try:
            self.led.off(self.led_settings["channels"][wl]["channel"])
            self.log(f"[LED] {PRETTY_LABEL[wl]} 끔")
        except Exception as e:  # noqa: BLE001
            self.log(f"✘ LED 끄기 실패: {e}")
        finally:
            self._live_wl = None
            self._refresh_live_state()

    def edit_led_channels(self):
        """파장 ↔ BioLED 채널 번호 배정 편집.

        기본값은 파장 8개를 ch1~ch8에 기계적으로 배정하지만, 실제 장비는
        채널이 그보다 적을 수 있다(BLS-SA02 등). 실제로 LED가 꽂힌 채널
        번호로 맞춰줘야 한다."""
        top = tk.Toplevel(self)
        top.title("BioLED 채널 설정")
        top.transient(self)
        top.resizable(False, False)

        nch = self.led.channels if (self.led and self.led.channels) else None
        head = ("파장별로 BioLED의 몇 번 채널에 연결돼 있는지 지정하세요.\n"
                + (f"이 장비에서 사용 가능한 채널: 1 ~ {nch}번"
                   if nch else "장비 미연결 — 연결하면 사용 가능한 채널 수를 확인할 수 있습니다."))
        ttk.Label(top, text=head, justify="left").pack(padx=14, pady=(14, 8), anchor="w")

        body = ttk.Frame(top)
        body.pack(padx=14)
        vars_ = {}
        for i, wl in enumerate(WAVELENGTHS):
            ttk.Label(body, text=PRETTY_LABEL[wl], width=10, anchor="w").grid(
                row=i, column=0, sticky="w", pady=2)
            v = tk.IntVar(value=self.led_settings["channels"].get(wl, {}).get("channel", i + 1))
            ttk.Spinbox(body, from_=1, to=(nch or 8), textvariable=v, width=6).grid(
                row=i, column=1, pady=2)
            vars_[wl] = v

        def save():
            for wl, v in vars_.items():
                self.led_settings.setdefault("channels", {}).setdefault(wl, {})["channel"] = int(v.get())
            save_json(BIOLED_SETTINGS_FILE, self.led_settings)
            self.log("[LED] 채널 배정 저장됨 — " + ", ".join(
                f"{PRETTY_LABEL[wl]}=ch{v.get()}" for wl, v in vars_.items()))
            top.destroy()

        btns = ttk.Frame(top)
        btns.pack(padx=14, pady=12)
        ttk.Button(btns, text="저장", command=save).pack(side="left", padx=4)
        ttk.Button(btns, text="취소", command=top.destroy).pack(side="left", padx=4)
        top.update_idletasks()
        top.grab_set()
        top.wait_window()

    def _ask_focused(self, title, prompt, initial=""):
        """입력칸에 **자동으로 커서가 들어가 있는** 한 줄 입력창.
        tkinter 기본 simpledialog는 포커스가 확실치 않아 매번 칸을 클릭해야
        했다 — 그 불편을 없애려고 직접 만든다. Enter=확인, Esc=취소."""
        top = tk.Toplevel(self)
        top.title(title)
        top.transient(self)
        top.resizable(False, False)
        ttk.Label(top, text=prompt, wraplength=380, justify="left").pack(
            padx=14, pady=(14, 6), anchor="w")
        var = tk.StringVar(value=initial)
        ent = ttk.Entry(top, textvariable=var, width=34)
        ent.pack(padx=14, pady=(0, 10))

        result = {"value": None}

        def ok(_e=None):
            result["value"] = var.get().strip()
            top.destroy()

        def cancel(_e=None):
            top.destroy()

        btns = ttk.Frame(top)
        btns.pack(padx=14, pady=(0, 12))
        ttk.Button(btns, text="확인", command=ok).pack(side="left", padx=4)
        ttk.Button(btns, text="취소", command=cancel).pack(side="left", padx=4)

        ent.bind("<Return>", ok)
        ent.bind("<Escape>", cancel)
        top.bind("<Escape>", cancel)

        # 창이 실제로 뜬 뒤에 포커스를 줘야 확실히 먹는다.
        top.update_idletasks()
        top.grab_set()
        ent.focus_force()
        ent.selection_range(0, "end")
        ent.icursor("end")
        top.wait_window()
        return result["value"] or None

    def add_led_preset(self):
        """현재 슬라이더 세기를 그대로 프리셋으로 저장한다.
        파워미터를 보며 맞춘 값을 다시 타이핑할 필요가 없도록, 세기는 묻지 않고
        **이름만** 물어본다(입력칸에 커서가 자동으로 들어가 있음)."""
        wl = self._wl_key()
        od = self.od_var.get().strip() or DEFAULT_OD
        percent = round(float(self.live_pct_var.get()), 1)
        label = self._ask_focused(
            "프리셋 추가",
            f"{PRETTY_LABEL[wl]} · {od} · 현재 세기 {percent} %\n\n"
            "이 세기의 이름을 입력하세요 (예: 1 mW):")
        if not label:
            return
        self.led_presets.setdefault(wl, {}).setdefault(od, []).append(
            {"label": label, "percent": percent})
        save_json(BIOLED_PRESETS_FILE, self.led_presets)
        self._refresh_od_options()
        self.od_var.set(od)
        self._refresh_led_presets()
        self.pct_combo.set(f"{label} ({percent} %)")
        self.log(f"[LED] 프리셋 추가: {PRETTY_LABEL[wl]} · {od} · {label} ({percent}%) "
                f"— bioled_presets.json에 저장, cli_tools\\bioled_controller.py에서도 보임")

    def edit_led_preset(self):
        wl = self._wl_key()
        od = self.od_var.get().strip() or DEFAULT_OD
        presets = self.led_presets.get(wl, {}).get(od, [])
        idx = self.pct_combo.current()
        if idx < 0 or idx >= len(presets):
            messagebox.showinfo("선택 없음", "수정할 프리셋을 먼저 드롭다운에서 선택하세요.")
            return
        cur = presets[idx]
        pct_s = self._ask_focused(
            "프리셋 수정",
            f"{PRETTY_LABEL[wl]} · {od} · '{cur['label']}'의 새 세기(%):\n"
            f"(현재 슬라이더 값을 쓰려면 {self.live_pct_var.get():.1f} 입력)",
            initial=str(cur["percent"]))
        if not pct_s:
            return
        try:
            percent = round(float(pct_s), 1)
        except ValueError:
            messagebox.showerror("입력 오류", f"숫자가 아닙니다: {pct_s!r}")
            return
        if not (0.0 <= percent <= 100.0):
            messagebox.showerror("입력 오류", "세기는 0~100 % 범위여야 합니다.")
            return
        label = self._ask_focused("프리셋 수정", "새 이름:", initial=cur["label"])
        if not label:
            return
        presets[idx] = {"label": label, "percent": percent}
        save_json(BIOLED_PRESETS_FILE, self.led_presets)
        self._refresh_led_presets()
        self.pct_combo.current(idx)
        self.log(f"[LED] 프리셋 수정: {PRETTY_LABEL[wl]} · {od} · {cur['label']}({cur['percent']}%) "
                f"-> {label}({percent}%)")

    def delete_led_preset(self):
        wl = self._wl_key()
        od = self.od_var.get().strip() or DEFAULT_OD
        presets = self.led_presets.get(wl, {}).get(od, [])
        idx = self.pct_combo.current()
        if idx < 0 or idx >= len(presets):
            messagebox.showinfo("선택 없음", "삭제할 프리셋을 먼저 드롭다운에서 선택하세요.")
            return
        p = presets[idx]
        if not messagebox.askyesno("삭제", f"'{PRETTY_LABEL[wl]} · {od} · {p['label']} ({p['percent']}%)' 삭제할까요?"):
            return
        presets.pop(idx)
        save_json(BIOLED_PRESETS_FILE, self.led_presets)
        self._refresh_led_presets()
        self.log(f"[LED] 프리셋 삭제: {PRETTY_LABEL[wl]} · {od} · {p['label']} ({p['percent']}%)")

    def start_session(self):
        name = self.sample_name_var.get().strip() or "Sample"
        self.station_cfg["sample_name"] = name
        save_json(STATION_CONFIG_FILE, self.station_cfg)
        self.session = Session(name, self.station_cfg.get("output_dir", SESSIONS_DIR))
        self.session_lbl.config(text=f"세션: {os.path.basename(self.session.dir)}")
        self._refresh_trace_list()
        self.log(f"[세션] 시작: {self.session.dir}")

    def _refresh_trace_list(self):
        self.trace_tree.delete(*self.trace_tree.get_children())
        if not self.session:
            self.filename_lbl.config(text="내보낼 파일명: (세션 없음)")
            self._redraw_plot()
            return
        for t in self.session.traces:
            self.trace_tree.insert("", "end", values=(t["label"], t["range_i_str"]))
        bracket = self.session.bracket_code()
        self.bracket_lbl.config(text=f"브래킷: {bracket}")
        # "엑셀 내보내기"를 누르면 실제로 저장될 이름을 미리 보여준다 —
        # (샘플명)[브래킷코드].xlsx 형식으로 자동 조합되며, 샘플명 칸을 고치면
        # 이 미리보기도 즉시 따라 바뀐다.
        name = self.sample_name_var.get().strip() or (self.session.sample_name if self.session else "")
        self.filename_lbl.config(text=f"내보낼 파일명:  [{bracket}] ({safe_filename(name)}).xlsx")
        self._redraw_plot()

    def _selected_index(self):
        sel = self.trace_tree.selection()
        if not sel or not self.session:
            return None
        return self.trace_tree.index(sel[0])

    def delete_selected_trace(self):
        idx = self._selected_index()
        if idx is None:
            messagebox.showinfo("선택 없음", "삭제할 트레이스를 목록에서 먼저 선택하세요.")
            return
        rec = self.session.remove_at(idx)
        self._refresh_trace_list()
        if rec:
            self.log(f"[세션] 트레이스 삭제: {rec['label']} ({rec['range_i_str']})")

    def _ask_label(self, current):
        top = tk.Toplevel(self)
        top.title("라벨 수정")
        top.transient(self)
        top.grab_set()
        opts = ["Dark"] + [PRETTY_LABEL[wl] for wl in WAVELENGTHS]
        var = tk.StringVar(value=current if current in opts else opts[0])
        ttk.Label(top, text="새 라벨 (브래킷 코드에 쓰일 값):").pack(padx=12, pady=(12, 4))
        ttk.Combobox(top, textvariable=var, values=opts, state="readonly", width=14).pack(padx=12, pady=4)
        result = {"value": None}

        def ok():
            result["value"] = var.get()
            top.destroy()
        ttk.Button(top, text="확인", command=ok).pack(pady=12)
        top.wait_window()
        return result["value"]

    def edit_selected_label(self):
        idx = self._selected_index()
        if idx is None:
            messagebox.showinfo("선택 없음", "라벨을 수정할 트레이스를 목록에서 먼저 선택하세요.")
            return
        current = self.session.traces[idx]["label"]
        new_label = self._ask_label(current)
        if new_label and new_label != current:
            self.session.update_label(idx, new_label)
            self._refresh_trace_list()
            self.log(f"[세션] 라벨 변경: {current} -> {new_label}")

    def move_selected(self, delta):
        idx = self._selected_index()
        if idx is None:
            return
        if self.session.move(idx, delta):
            self._refresh_trace_list()
            children = self.trace_tree.get_children()
            self.trace_tree.selection_set(children[idx + delta])

    def export_excel(self):
        if not self.session:
            messagebox.showwarning("세션 없음", "먼저 세션을 시작하세요.")
            return
        # 세션 폴더 이름은 시작할 때 고정되지만, 엑셀 파일명에 들어갈 샘플명은
        # 내보내기 직전까지 위 입력란에서 자유롭게 바꿀 수 있다.
        name = self.sample_name_var.get().strip() or self.session.sample_name
        try:
            path = self.session.export_excel(".", sample_name=name)
            self.log(f"[내보내기] 저장됨: {path}")
            messagebox.showinfo("완료", f"저장됨:\n{path}")
        except ImportError:
            messagebox.showerror(
                "openpyxl 없음",
                "이 파이썬에 openpyxl이 설치되어 있지 않습니다.\n\n"
                "터미널에서 (32비트 파이썬으로):\n"
                "  py -3.13-32 -m pip install openpyxl")
        except Exception as e:
            messagebox.showerror("내보내기 실패", str(e))

    # ---------- 그래프 (tkinter Canvas, numpy/matplotlib 없이) ----------
    def _redraw_plot(self):
        c = self.plot_canvas
        c.delete("all")
        # 탭이 아직 한 번도 화면에 그려진 적 없으면 winfo_width/height가 실제
        # 크기 대신 1을 돌려주는 tkinter 특유의 함정이 있다 — 그럴 땐 생성 시
        # 지정한 크기로 대체한다.
        cw = c.winfo_width()
        ch_ = c.winfo_height()
        if cw <= 1:
            cw = int(c.cget("width"))
        if ch_ <= 1:
            ch_ = int(c.cget("height"))

        # 창을 어떻게 늘리든 작도 영역은 항상 8:10(가로:세로)을 유지한다.
        # 남는 쪽은 여백으로 두고(레터박스) 그림을 가운데 정렬 —— 이렇게 해야
        # 화면 크기에 따라 그래프가 찌그러지지 않는다.
        box_w, box_h = ASPECT_W, ASPECT_H
        scale = min(cw / box_w, ch_ / box_h)
        w = max(int(box_w * scale), 10)
        h = max(int(box_h * scale), 10)
        off_x = (cw - w) // 2
        off_y = (ch_ - h) // 2
        # 이하 좌표는 전부 (0,0)~(w,h) 기준으로 계산하고, 함수 끝에서 한 번에
        # off_x/off_y 만큼 밀어 가운데 정렬한다.
        if not self.session or not self.session.traces:
            c.create_text(cw // 2, ch_ // 2, text="측정된 트레이스 없음", fill="gray")
            return

        traces = self.session.traces
        all_v = [v for t in traces for v, i, *_ in t["data"]]
        if not all_v:
            c.create_text(cw // 2, ch_ // 2, text="표시할 데이터 포인트가 없습니다\n"
                                                  "(장비 미연결/Dry-run이면 정상)",
                          fill="gray", justify="center")
            return

        margin_l, margin_r, margin_t, margin_b = 55, 12, 10, 28
        plot_w = max(w - margin_l - margin_r, 10)
        plot_h = max(h - margin_t - margin_b, 10)

        vmin, vmax = min(all_v), max(all_v)
        if vmin == vmax:
            vmin, vmax = vmin - 0.5, vmax + 0.5
        # 전류가 모두 정확히 0으로 읽힐 수도 있다(측정 자체는 됐지만 값이 0인
        # 경우) — 그럴 땐 축이 정의되게 기본 범위로 대체하고, 0인 점은 숨기지
        # 않고 축 맨 아래에 붙여서 그린다(완전히 사라지면 "그래프가 안 보인다"
        # 는 오해를 산다).
        nonzero_absi = [abs(i) for t in traces for v, i, *_ in t["data"] if i != 0]
        if nonzero_absi:
            logmin = math.floor(math.log10(min(nonzero_absi)))
            logmax = math.ceil(math.log10(max(nonzero_absi)))
            if logmin == logmax:
                logmax = logmin + 1
        else:
            logmin, logmax = -11, -5

        def xpix(v):
            return margin_l + (v - vmin) / (vmax - vmin) * plot_w

        def ypix(i_abs):
            i_abs = max(i_abs, 10 ** logmin)
            frac = (math.log10(i_abs) - logmin) / (logmax - logmin)
            return margin_t + (1 - frac) * plot_h

        c.create_rectangle(margin_l, margin_t, margin_l + plot_w, margin_t + plot_h, outline="#999")
        for dec in range(logmin, logmax + 1):
            y = ypix(10 ** dec)
            c.create_line(margin_l - 4, y, margin_l + plot_w, y, fill="#eee")
            c.create_text(margin_l - 6, y, text=f"1e{dec}", anchor="e", font=("", 7))
        for k in range(5):
            v = vmin + (vmax - vmin) * k / 4
            x = xpix(v)
            c.create_line(x, margin_t, x, margin_t + plot_h, fill="#eee")
            c.create_text(x, margin_t + plot_h + 12, text=f"{v:.2f}", font=("", 7))
        c.create_text(margin_l + plot_w / 2, h - 6, text="Voltage (V)", font=("", 7))

        legend_y = margin_t + 4
        for idx, t in enumerate(traces):
            color = TRACE_COLORS.get(t["label"], FALLBACK_TRACE_COLORS[idx % len(FALLBACK_TRACE_COLORS)])
            pts = []
            for v, i, *_ in t["data"]:
                i_plot = i if i != 0 else 10 ** logmin  # 0은 숨기지 않고 축 바닥에 그림
                pts.extend([xpix(v), ypix(abs(i_plot))])
            if len(pts) >= 4:
                c.create_line(*pts, fill=color, width=1.6)
            c.create_line(w - margin_r - 46, legend_y + 5, w - margin_r - 28, legend_y + 5,
                         fill=color, width=2)
            c.create_text(w - margin_r - 24, legend_y + 5, text=t["label"], anchor="w", font=("", 7))
            legend_y += 13

        # 8:10 박스를 캔버스 가운데로 이동 (레터박스)
        if off_x or off_y:
            c.move("all", off_x, off_y)

    # ---------- 실제 측정 로직 (워커 스레드에서 실행) ----------
    def _prep_and_apply(self, chans, ms):
        """DE/IT/RS 전송. 채널 정의는 매 측정 전에 다시 보내 상태를 확정한다."""
        self.smu.configure_channels(chans)
        self.smu.set_integration(
            ms["integration"]["mode"],
            (ms["integration"]["delay"], ms["integration"]["filter"], ms["integration"]["plc"]))
        self.smu.set_resolution(ms["resolution_digits"])

    def _do_sweep(self, sweep_ch, chans, ms, start, stop, step, compliance, range_A):
        self._prep_and_apply(chans, ms)
        self.smu.setup_sources(chans, ms["sweep_type"])
        if sweep_ch["mode"] == 2:
            self.smu.ir_sweep(sweep_ch["ch"], start, stop, step, compliance, ms["sweep_type"])
        else:
            self.smu.vr_sweep(sweep_ch["ch"], start, stop, step, compliance, ms["sweep_type"])
        # 스윕 채널의 전압·전류 이름을 측정 대상으로 명시 (LI) — 없으면 전류가
        # 측정되지 않아 전부 0으로 돌아온다
        self.smu.setup_measure_iv([sweep_ch["vname"], sweep_ch["iname"]])
        if range_A is not None and ms["range_mode"] in ("RI", "RG"):
            if ms["range_mode"] == "RI":
                self.smu.set_range_fixed(sweep_ch["ch"], range_A, compliance)
            else:
                self.smu._w(f"RG{sweep_ch['ch']},{range_A:g}")
        expected = int(round(abs(stop - start) / abs(step))) + 1 if step else 0
        t_trig = time.time()
        self.smu.trigger()
        self.smu.wait_done()
        elapsed = time.time() - t_trig
        v_pairs = self.smu.fetch_with_status(sweep_ch["vname"])
        i_pairs = self.smu.fetch_with_status(sweep_ch["iname"])
        n = min(len(v_pairs), len(i_pairs))
        # 실제로 얼마나 걸렸는지 항상 남긴다 — "너무 빨리 지나간다" 같은 의심을
        # 감이 아니라 숫자로 확인할 수 있어야 한다.
        per_pt = (elapsed / n * 1000) if n else 0.0
        self.log(f"    측정 소요 {elapsed:.2f}s / {n}점 (점당 {per_pt:.1f}ms), "
                f"예상 점수 {expected}")
        if expected and n != expected:
            self.log(f"    ⚠ 수신 점수({n})가 설정값에서 계산한 점수({expected})와 다릅니다 "
                    "— 스윕이 끝나기 전에 읽었을 가능성")
        data = [(v_pairs[k][0], i_pairs[k][0], i_pairs[k][1]) for k in range(n)]
        # 전류가 '정확히' 전부 0이면 물리적 측정 결과로 보기 어렵다. 실제
        # 개방회로라도 미세한 누설/노이즈가 섞여 완전한 0이 되긴 힘들다.
        if n and all(i == 0.0 for _, i, _ in data):
            self.log(f"    ⚠ 전류 {n}점이 전부 정확히 0입니다 — 측정이 실제로 일어나지 "
                    "않았을 가능성이 큽니다. 확인 순서:\n"
                    "       ① 소자가 실제로 프로브에 물려 있는지\n"
                    "       ② 탭1 SMU 배정이 실제 배선과 맞는지 (스윕=Anode쪽, Common=Cathode쪽)\n"
                    "       ③ 4200 SMU 출력 케이블 / Interlock 상태")
        # 'N'(Normal) 이외의 상태 코드는 컴플라이언스/오버플로 가능성을 뜻한다
        # (정확한 코드 의미는 매뉴얼 상태 문자 표로 재확인할 것).
        flagged = sum(1 for _, _, s in data if s and s != "N")
        if flagged:
            self.log(f"    ⚠ {flagged}/{n}개 포인트 상태코드가 'N'(정상)이 아님 "
                    "— 컴플라이언스/오버플로 가능성. Status 컬럼에서 어느 점인지 확인 가능")
        return data

    def _require_ready(self):
        if self.smu is None:
            raise RuntimeError("먼저 Keithley를 연결하세요.")
        if self.session is None:
            raise RuntimeError("먼저 '새 세션 시작'을 눌러 세션을 만드세요.")

    def _measure_dark(self, which):
        self._require_ready()
        chans = self._collect_smu_channels()
        sweep_ch = self._sweep_channel(chans)
        ms = self._collect_measure_settings()
        key = "dark_neg" if which == "neg" else "dark_pos"
        d = ms[key]
        range_A = ms["range_A"] if ms["range_dark_same"] else None
        label = "Dark"
        self.log(f"[측정] Dark {d['start']}V→{d['stop']}V ...")
        data = self._do_sweep(sweep_ch, chans, ms, d["start"], d["stop"], d["step"],
                              d["compliance"], range_A)
        rec = self.session.add_trace(label, range_A, data)
        self.log(f"[측정] Dark 완료: {len(data)}점 -> {rec['csv_path']}")
        self.after(0, self._refresh_trace_list)

    def _measure_photo(self):
        self._require_ready()
        chans = self._collect_smu_channels()
        sweep_ch = self._sweep_channel(chans)
        ms = self._collect_measure_settings()
        d = ms["photo"]
        range_A = ms["range_A"]
        wl = self._wl_key()
        label = PRETTY_LABEL[wl]

        od = self.od_var.get().strip() or DEFAULT_OD
        if self.led is not None:
            sel = self.pct_combo.current()
            presets = self.led_presets.get(wl, {}).get(od, [])
            if sel < 0 or sel >= len(presets):
                raise RuntimeError(f"먼저 {PRETTY_LABEL[wl]} · {od}의 세기 프리셋을 선택/등록하세요.")
            pct = presets[sel]["percent"]
            ch_info = self.led_settings["channels"][wl]
            self.led.set_percent(ch_info["channel"], pct)
            self.log(f"[LED] {wl} · {od} @ {pct}% 켬")
        else:
            self.log("[LED] ⚠ BioLED 미연결 — 광원 수동 점등 가정하고 진행")

        self.log(f"[측정] {label} {d['start']}V→{d['stop']}V ...")
        try:
            data = self._do_sweep(sweep_ch, chans, ms, d["start"], d["stop"], d["step"],
                                  d["compliance"], range_A)
        finally:
            if self.led is not None:
                ch_info = self.led_settings["channels"][wl]
                self.led.off(ch_info["channel"])
                # 측정이 광원을 껐으므로 실시간 조절 상태도 실제와 맞춘다
                # (UI만 '켜짐'으로 남아 있으면 사용자가 오해한다)
                self._live_is_on = False
                self._live_wl = None
                self.after(0, self._refresh_live_state)

        rec = self.session.add_trace(label, range_A, data)
        self.log(f"[측정] {label} 완료: {len(data)}점 -> {rec['csv_path']}")
        self.after(0, self._refresh_trace_list)

    # ======================================================
    # 탭 4 · I-T 측정 (pd_it.py 타임라인 로직을 DLL 방식으로 이관)
    # ======================================================
    def _build_tab_it(self):
        frame = ttk.Frame(self.nb, padding=10)
        self.nb.add(frame, text="4. I-T 측정")

        itc = (self.it_cfg or {}).get("it", {})

        top = ttk.Frame(frame)
        top.pack(fill="x")
        ttk.Label(top, text="파장(브래킷 코드)").grid(row=0, column=0, sticky="w")
        self.it_wl_var = tk.StringVar(value=WL_DISPLAY[WAVELENGTHS[0]])
        wl_cb = ttk.Combobox(top, textvariable=self.it_wl_var,
                             values=[WL_DISPLAY[wl] for wl in WAVELENGTHS],
                             width=10, state="readonly")
        wl_cb.grid(row=0, column=1, padx=4)

        ttk.Label(top, text="OD(ND필터)").grid(row=0, column=2, sticky="w")
        self.it_od_var = tk.StringVar(value=DEFAULT_OD)
        it_od_combo = ttk.Combobox(top, textvariable=self.it_od_var, width=8, state="readonly")
        it_od_combo.grid(row=0, column=3, padx=4)

        self.it_presets_lbl = ttk.Label(top, text="", foreground="#555", wraplength=600, justify="left")
        self.it_presets_lbl.grid(row=0, column=4, columnspan=3, sticky="w", padx=8)

        def refresh_presets_preview(*_):
            wl = WL_DISPLAY_TO_KEY.get(self.it_wl_var.get(), WAVELENGTHS[0])
            od = self.it_od_var.get().strip() or DEFAULT_OD
            presets = sorted(self.led_presets.get(wl, {}).get(od, []), key=lambda p: p["percent"])
            if not presets:
                self.it_presets_lbl.config(
                    text=f"⚠ {PRETTY_LABEL[wl]} · {od}에 등록된 세기 프리셋이 없습니다 — "
                        "탭3 '+ 프리셋 추가'로 먼저 등록하세요.")
            else:
                n = len(presets)
                pct_list = ", ".join(f"{p['percent']}%" for p in presets)
                self.it_presets_lbl.config(
                    text=f"등록된 프리셋 {n}개(낮은 세기 순): {pct_list}\n"
                        f"→ dark {n + 1}번 · light {n}번 자동 반복")

        def refresh_it_od_options(*_):
            wl = WL_DISPLAY_TO_KEY.get(self.it_wl_var.get(), WAVELENGTHS[0])
            ods = sorted(self.led_presets.get(wl, {}).keys()) or [DEFAULT_OD]
            it_od_combo.config(values=ods)
            if self.it_od_var.get() not in ods:
                self.it_od_var.set(ods[0])
            refresh_presets_preview()

        wl_cb.bind("<<ComboboxSelected>>", refresh_it_od_options)
        it_od_combo.bind("<<ComboboxSelected>>", refresh_presets_preview)
        # <<ComboboxSelected>>는 실제 마우스 선택에서만 뜬다 — 프로그램에서
        # .set()으로 값을 바꾸는 경우까지 확실히 반영되도록 trace도 같이 건다.
        self.it_od_var.trace_add("write", lambda *_: refresh_presets_preview())
        refresh_it_od_options()
        # 탭3에서 프리셋을 새로 추가했을 수도 있으니 이 탭이 눈에 보일 때마다 새로고침
        self.nb.bind("<<NotebookTabChanged>>", lambda e: refresh_it_od_options())

        ttk.Label(top, text="Bias(V)").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.it_bias_var = tk.DoubleVar(value=itc.get("bias_V", -1.0))
        ttk.Entry(top, textvariable=self.it_bias_var, width=8).grid(row=1, column=1, pady=(6, 0))
        ttk.Label(top, text="Dark 길이(s)").grid(row=1, column=2, sticky="w", pady=(6, 0))
        self.it_dark_s_var = tk.DoubleVar(value=itc.get("dark_s", 5.0))
        ttk.Entry(top, textvariable=self.it_dark_s_var, width=8).grid(row=1, column=3, pady=(6, 0))
        ttk.Label(top, text="Light 길이(s)").grid(row=1, column=4, sticky="w", pady=(6, 0))
        self.it_light_s_var = tk.DoubleVar(value=itc.get("light_s", 5.0))
        ttk.Entry(top, textvariable=self.it_light_s_var, width=8).grid(row=1, column=5, pady=(6, 0))

        ttk.Button(frame, text="I-T 측정 시작",
                  command=lambda: self._run_worker(self._measure_it)).pack(anchor="w", pady=12)
        ttk.Label(frame, text="시퀀스: dark → (가장 약한 세기) → dark → ... → (가장 강한 세기) → dark(끝). "
                              "세기는 탭3/BioLED Controller에 등록된 프리셋을 낮은 것부터 순서대로 사용. "
                              "Range I는 이 파장의 프리셋 세트 전체(dark 포함)에 고정.",
                 foreground="gray", wraplength=800).pack(anchor="w")

    def _measure_it(self):
        if self.smu is None:
            raise RuntimeError("먼저 Keithley를 연결하세요.")
        if self.led is None:
            raise RuntimeError("먼저 BioLED를 연결하세요 (상단 'BioLED 연결').")
        wl = WL_DISPLAY_TO_KEY.get(self.it_wl_var.get(), WAVELENGTHS[0])
        od = self.it_od_var.get().strip() or DEFAULT_OD
        presets = sorted(self.led_presets.get(wl, {}).get(od, []), key=lambda p: p["percent"])
        if not presets:
            raise RuntimeError(f"{PRETTY_LABEL[wl]} · {od}에 등록된 세기 프리셋이 없습니다 — "
                              "탭3 '+ 프리셋 추가'로 먼저 등록하세요.")
        ch_info = self.led_settings["channels"][wl]

        itc = (self.it_cfg or {}).get("it", {})
        bias = self.it_bias_var.get()
        dark_s = self.it_dark_s_var.get()
        light_s = self.it_light_s_var.get()
        interval_s = itc.get("sample_interval_s", 0.05)
        compliance = itc.get("compliance_A", 1e-3)

        chans = self._collect_smu_channels()
        sweep_ch_candidates = [c for c in chans if c["enabled"]]
        if not sweep_ch_candidates:
            raise RuntimeError("SMU 채널이 설정되어 있지 않습니다 (탭1 확인).")
        ch = sweep_ch_candidates[0]

        self.log(f"[IT] 프리스캔: {PRETTY_LABEL[wl]} 최대세기({presets[-1]['percent']}%)에서 |I| 실측 ...")
        self.led.set_percent(ch_info["channel"], presets[-1]["percent"])
        time.sleep(1.0)
        data = self._it_capture(ch, bias, 2.0, 0.2, compliance, None)
        self.led.off(ch_info["channel"])
        exp = max((abs(i) for _, i in data), default=compliance)
        self.log(f"    실측 |I|max = {exp:.3e} A")
        fixed_range = pick_fixed_range(exp, itc.get("range_margin", 3.0))
        self.log(f"[IT] 고정 Range I = {format_range_i(fixed_range)}")

        # 시퀀스: dark, P1, dark, P2, ..., Pn, dark(끝) — 프리셋 n개면 dark n+1번, light n번.
        timeline = [(None, "dark", dark_s)]
        for p in presets:
            timeline.append((p["percent"], p["label"], light_s))
            timeline.append((None, "dark", dark_s))
        total_s = sum(d for _, _, d in timeline)
        self.log(f"[IT] {len(timeline)}구간(dark {len(presets)+1}번, light {len(presets)}번), "
                f"총 {total_s:.0f}s, bias {bias}V")

        self.led.off(ch_info["channel"])
        self._prep_and_apply(chans, self._collect_measure_settings())
        self.smu.setup_sources(chans)
        self.smu.vc_constant(ch["ch"], bias, compliance)
        n = int((total_s + 1.0) / interval_s) + 1
        self.smu.setup_measure_it(0.0, interval_s, n, [ch["vname"], ch["iname"]])
        if fixed_range is not None:
            self.smu.set_range_fixed(ch["ch"], fixed_range, compliance)
        self.smu.trigger()

        t0 = time.time()
        events = []
        elapsed_target = 0.0
        for level, seg_label, dur in timeline:
            if level is None:
                self.led.off(ch_info["channel"])
            else:
                self.led.set_percent(ch_info["channel"], level)
            events.append((round(time.time() - t0, 3), seg_label))
            elapsed_target += dur
            edge = t0 + elapsed_target
            while time.time() < edge:
                time.sleep(0.01)
        self.led.off(ch_info["channel"])

        self.smu.wait_done()
        t = self.smu.fetch("T")
        i = self.smu.fetch(ch["iname"])
        if not t:
            t = list(range(len(i)))
        data = list(zip(t, i))

        stamp = datetime.now().strftime("%y%m%d_%H%M")
        outdir = os.path.join((self.it_cfg or {}).get("output_dir", IT_OUTPUT_DIR), f"IT_{stamp}")
        sample = self.sample_name_var.get().strip() or self.station_cfg.get("sample_name", "Sample")
        base = f"{safe_filename(sample)}_{wl}_{od}_{bias:+.0f}V"
        save_csv(os.path.join(outdir, base + "_IT.csv"), ["Time (s)", "Current (A)"], data)
        save_csv(os.path.join(outdir, base + "_events.csv"), ["Elapsed (s)", "Segment"], events)
        self.log(f"[IT] 완료 -> {outdir}")

    def _it_capture(self, ch, bias, total_s, interval_s, compliance, fixed_range):
        chans = self._collect_smu_channels()
        self._prep_and_apply(chans, self._collect_measure_settings())
        self.smu.setup_sources(chans)
        self.smu.vc_constant(ch["ch"], bias, compliance)
        n = int(total_s / interval_s) + 1
        self.smu.setup_measure_it(0.0, interval_s, n, [ch["vname"], ch["iname"]])
        if fixed_range is not None:
            self.smu.set_range_fixed(ch["ch"], fixed_range, compliance)
        self.smu.trigger()
        self.smu.wait_done()
        i = self.smu.fetch(ch["iname"])
        t = list(range(len(i)))
        return list(zip(t, i))

    def destroy(self):
        try:
            if getattr(self, "_drain_after_id", None):
                self.after_cancel(self._drain_after_id)
            self.disconnect_all()
        finally:
            super().destroy()


def main():
    if "--check-bitness" in sys.argv:
        bits = 8 * ctypes.sizeof(ctypes.c_void_p)
        print(f"{bits}-bit")
        return
    App().mainloop()


if __name__ == "__main__":
    main()
