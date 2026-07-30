# -*- coding: utf-8 -*-
"""
pd_iv_only.py — Keithley 4200(KXCI) 단독 I-V 측정, 공식 DLL 기반
==================================================================
2026-07-29 개정: pyvisa raw socket 방식은 KXCI가 응답하지 않아 전면 폐기.
Keithley 제공 공식 클라이언트 KXCIClient.DLL(ctypes)로 교체 — 실측 검증됨
(ID 쿼리에 'KI4200 V9.1-SP1' 응답 확인).

⚠ KXCIClient.DLL은 32비트 전용이다. 반드시 32비트 파이썬으로 실행할 것.
   VSCode: Ctrl+Shift+P -> "Python: Select Interpreter" -> 32비트 항목 선택
   터미널 직접 실행: py -3.13-32 pd_iv_only.py ...
   확인: python -c "import struct; print(struct.calcsize('P')*8)"  -> 32 이어야 함

DLL은 이 스크립트와 같은 폴더에 KXCIclient.dll 로 두어야 한다.

문법 근거 (Model 4200-SCS Reference Manual, Section 9, 2013):
  - DE 페이지에서 채널 정의: DE 후 CH1,'V1','I1',mode,func  (Table 9-7)
  - 소스 설정: SS 후 VR1,start,stop,step,compliance
  - 측정 실행: SM 후 DM2(리스트 모드), MD 후 ME1(트리거)
  - 데이터 조회: DO 'AAAAAA'  (AAAAAA = DE 페이지에서 붙인 이름, 예: 'VA','IA')
  - 완료 판정: 상태 바이트 Bit 0(값 1)=Data Ready, Bit 1(값 2)=Syntax Error,
    Bit 4(값 16)=Busy. GetKXCISpollByte_C 로 폴링.

사용법
  1) 연결만 점검
     python pd_iv_only.py --test-connection

  2) 실제 스윕 (예: -1V -> +1V, 0.05V 스텝, 컴플라이언스 1mA)
     python pd_iv_only.py --start -1 --stop 1 --step 0.05 --compliance 1e-3 --label dark

  3) 장비 없이 로직만 점검
     python pd_iv_only.py --start -1 --stop 1 --step 0.05 --dry-run
"""

from __future__ import annotations

import argparse
import csv
import ctypes
import os
import re
import sys
import time
from datetime import datetime

IP = b"192.168.0.200"
PORT = 2105
DLL_NAME = "KXCIclient.dll"
BUF_SIZE = 4096
OUTPUT_DIR = "iv_data"
SAMPLE_NAME = "FAPbI3_Si"

# 고정 전류 레인지 사다리 (프리앰프 없을 때 기준)
FIXED_RANGES_A = [1e-9, 1e-8, 1e-7, 1e-6, 1e-5, 1e-4, 1e-3, 1e-2, 1e-1]

# 상태 바이트 비트 (매뉴얼 Section 9, Status byte)
BIT_DATA_READY = 0x01
BIT_SYNTAX_ERR = 0x02
BIT_BUSY = 0x10


def pick_fixed_range(i_max_A: float, margin: float = 3.0) -> float:
    need = abs(i_max_A) * margin
    for r in FIXED_RANGES_A:
        if r >= need:
            return r
    return FIXED_RANGES_A[-1]


def _check_bitness():
    bits = 8 * ctypes.sizeof(ctypes.c_void_p)
    if bits != 32:
        raise SystemExit(
            f"\n\u2718 KXCIClient.DLL은 32비트 전용인데 현재 파이썬은 {bits}비트입니다.\n"
            "  VSCode: Ctrl+Shift+P -> Python: Select Interpreter -> 32비트 항목 선택\n"
            "  또는 터미널에서: py -3.13-32 " + os.path.basename(__file__) + " ...\n"
        )


class Keithley4200:
    """KXCIClient.DLL(ctypes, cdecl) 래퍼. SMU1 = 소자 전압 인가/전류 측정 가정."""

    _NUM = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")

    def __init__(self, dry=False):
        self.dry = dry
        self.dll = None
        if dry:
            return

        _check_bitness()
        dll_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), DLL_NAME)
        if not os.path.exists(dll_path):
            raise SystemExit(f"DLL을 찾을 수 없습니다: {dll_path}")

        dll = ctypes.CDLL(dll_path)
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
        print(f"[4200] 연결 (DLL): ret={ret}, socket_err={sock_err.value}")
        if sock_err.value != 0:
            raise RuntimeError(f"KXCI 연결 실패 (socket_err={sock_err.value})")

        idn = self._raw_send("ID")
        print(f"[4200] 응답: {idn.strip()}")

    # ---------- 저수준 송수신 ----------
    def _raw_send(self, cmd: str) -> str:
        if self.dry:
            print(f"    [4200] {cmd}")
            return ""
        resp_buf = ctypes.create_string_buffer(BUF_SIZE)
        sock_err = ctypes.c_int(0)
        self.dll.SendKXCICommand_C(cmd.encode(), resp_buf, ctypes.byref(sock_err))
        if sock_err.value != 0:
            print(f"    \u26a0 socket_err={sock_err.value} (cmd={cmd!r})")
        return resp_buf.value.decode(errors="ignore")

    def _w(self, cmd: str):
        """응답을 특별히 파싱할 필요 없는 명령(설정류) 전송."""
        self._raw_send(cmd)

    def _fetch(self, name: str):
        """DO 'name' 으로 저장된 데이터를 조회해 float 리스트로 반환."""
        raw = self._raw_send(f"DO '{name}'")
        out = []
        for tok in raw.split(","):
            m = self._NUM.search(tok)
            if m:
                out.append(float(m.group()))
        return out

    def wait_done(self, poll_s=0.2, max_wait_s=60):
        """상태 바이트 Bit0(Data Ready)을 폴링. Bit1(Syntax Error)이면 즉시 경고."""
        if self.dry:
            return
        t0 = time.time()
        spb = ctypes.c_ushort(0)
        sock_err = ctypes.c_int(0)
        while time.time() - t0 < max_wait_s:
            self.dll.GetKXCISpollByte_C(ctypes.byref(spb), ctypes.byref(sock_err))
            status = spb.value
            if status & BIT_SYNTAX_ERR:
                print("    \u26a0 KXCI Syntax Error 비트 감지 — 직전 명령 문법 확인 필요")
            if status & BIT_DATA_READY:
                return
            time.sleep(poll_s)
        print("    \u26a0 wait_done 타임아웃 — Data Ready 비트가 서지 않음")

    # ---------- I-V 스윕 ----------
    def iv_sweep(self, v_start, v_stop, v_step, compliance_A, fixed_range_A=None):
        step = abs(v_step) * (1 if v_stop >= v_start else -1)
        self._w("DE")
        self._w("CH1,'VA','IA',1,1")             # SMU1: V소스, I측정
        self._w("SS")
        self._w(f"VR1,{v_start},{v_stop},{step},{compliance_A}")
        self._w("SM")
        self._w("DM2")                            # 리스트 데이터 모드
        if fixed_range_A is not None:
            self._w(f"RG1,{fixed_range_A:g}")     # [VERIFY] 고정 레인지 명령
        self._w("MD")
        self._w("ME1")
        self.wait_done()
        v = self._fetch("VA")
        i = self._fetch("IA")
        return list(zip(v, i))

    def close(self):
        if not self.dry and self.dll:
            self.dll.CloseKXCIConnection_C()


def test_connection():
    print("=" * 58)
    print("[Keithley 4200 연결 점검 — KXCIClient.DLL]")
    bits = 8 * ctypes.sizeof(ctypes.c_void_p)
    print(f"  파이썬 비트수: {bits}-bit  (Python {sys.version.split()[0]})")
    if bits != 32:
        print("  \u2718 32비트 파이썬이 아닙니다. py -3.13-32 로 실행하세요.")
        print("=" * 58)
        return False
    try:
        smu = Keithley4200(dry=False)
        smu.close()
        print("  \u2714 연결·응답 모두 정상")
        print("=" * 58)
        return True
    except Exception as e:
        print(f"  \u2718 실패: {e}")
        print("=" * 58)
        return False


def save_csv(path, header, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    print(f"    -> 저장: {path}")


def main():
    ap = argparse.ArgumentParser(description="Keithley 4200 단독 I-V 스윕 (DLL 기반)")
    ap.add_argument("--test-connection", action="store_true", help="연결만 점검하고 종료")
    ap.add_argument("--start", type=float, help="시작 전압 (V)")
    ap.add_argument("--stop", type=float, help="종료 전압 (V)")
    ap.add_argument("--step", type=float, default=0.05, help="전압 스텝 (V), 기본 0.05")
    ap.add_argument("--compliance", type=float, default=1e-3, help="컴플라이언스 (A), 기본 1e-3")
    ap.add_argument("--range", type=float, default=None,
                    help="고정 Range I (A). 미지정 시 오토레인지")
    ap.add_argument("--label", default="sweep", help="파일명 라벨 (예: dark, 530nm)")
    ap.add_argument("--dry-run", action="store_true", help="장비 없이 로직만 점검")
    args = ap.parse_args()

    if args.test_connection:
        test_connection()
        return

    if args.start is None or args.stop is None:
        raise SystemExit("--start 와 --stop 은 필수입니다 (연결 점검만 하려면 --test-connection)")

    smu = Keithley4200(dry=args.dry_run)
    try:
        print(f"[IV] {args.start} V -> {args.stop} V, step {args.step} V, "
              f"compliance {args.compliance:g} A, "
              f"range={'auto' if args.range is None else f'{args.range:g} A'}")
        data = smu.iv_sweep(args.start, args.stop, args.step, args.compliance,
                            fixed_range_A=args.range)
        if not data:
            print("[IV] \u26a0 데이터가 비어 있습니다 — DO 'VA'/'IA' 응답을 확인하세요")
        else:
            print(f"[IV] {len(data)} points 수신")
        stamp = datetime.now().strftime("%y%m%d_%H%M%S")
        path = os.path.join(OUTPUT_DIR, f"{SAMPLE_NAME}_{args.label}_{stamp}_IV.csv")
        save_csv(path, ["Voltage (V)", "Current (A)"], data)
    finally:
        smu.close()


if __name__ == "__main__":
    main()