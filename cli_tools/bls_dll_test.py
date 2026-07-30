# -*- coding: utf-8 -*-
"""
bls_dll_test.py — Mightex BioLED (BLS 시리즈) HID DLL 연결 테스트
====================================================================
BLS-SA02-U는 시리얼(COM 포트) 장치가 아니라 **USB HID 장치**다 — 그래서
장치관리자에 COM 포트로 절대 안 뜨고, pyserial로도 열 수 없다(Mightex
공식 SDK 매뉴얼에 명시된 사실: "the BIOLED Control driver is designed
as a HID device"). 공식 SDK가 제공하는 Mightex_BLSDriver_SDK.dll을
ctypes(cdecl)로 직접 불러써야 한다 — Keithley KXCIclient.dll과 완전히
같은 패턴.

⚠ Mightex_BLSDriver_SDK.dll도 32비트(x86) 전용이다. 32비트 파이썬으로
   실행할 것: py -3.13-32 bls_dll_test.py
   DLL은 HIDDLL.dll과 함께 이 스크립트와 같은 폴더에 있어야 한다
   (Mightex_BLSDriver_SDK.dll이 내부적으로 HIDDLL.dll을 불러쓴다).

원본: Mightex bioLED Controller SDK Manual.pdf (버전 1.2.1, 2020-12-22)
"""

import ctypes
import os
import sys

DLL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Mightex_BLSDriver_SDK.dll")

DISABLE_MODE = 0
NORMAL_MODE = 1
TRIGGER_MODE = 3
MODULE_TYPE_NAMES = {0: "AA_MODULE", 2: "SA_MODULE", 13: "PL_MODULE", 14: "IO_MODULE"}


def load_dll():
    bits = 8 * ctypes.sizeof(ctypes.c_void_p)
    print(f"[정보] 현재 파이썬: {bits}-bit (Python {sys.version.split()[0]})")
    if bits != 32:
        raise SystemExit(
            f"\n✘ Mightex_BLSDriver_SDK.dll은 32비트 전용인데 현재 파이썬은 {bits}비트입니다.\n"
            "  py -3.13-32 bls_dll_test.py 로 실행하세요."
        )
    if not os.path.exists(DLL_PATH):
        raise SystemExit(f"✘ DLL을 찾을 수 없습니다: {DLL_PATH}")

    dll = ctypes.CDLL(DLL_PATH)  # cdecl -> CDLL

    dll.MTUSB_BLSDriverInitDevices.restype = ctypes.c_int
    dll.MTUSB_BLSDriverOpenDevice.argtypes = [ctypes.c_int]
    dll.MTUSB_BLSDriverOpenDevice.restype = ctypes.c_int
    dll.MTUSB_BLSDriverCloseDevice.argtypes = [ctypes.c_int]
    dll.MTUSB_BLSDriverCloseDevice.restype = ctypes.c_int
    dll.MTUSB_BLSDriverGetSerialNo.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
    dll.MTUSB_BLSDriverGetSerialNo.restype = ctypes.c_int
    dll.MTUSB_BLSDriverGetModuleType.argtypes = [ctypes.c_int]
    dll.MTUSB_BLSDriverGetModuleType.restype = ctypes.c_int
    dll.MTUSB_BLSDriverGetChannels.argtypes = [ctypes.c_int]
    dll.MTUSB_BLSDriverGetChannels.restype = ctypes.c_int
    dll.MTUSB_BLSDriverGetChannelTitle.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_char_p]
    dll.MTUSB_BLSDriverGetChannelTitle.restype = ctypes.c_int
    dll.MTUSB_BLSDriverSetMode.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int]
    dll.MTUSB_BLSDriverSetMode.restype = ctypes.c_int
    dll.MTUSB_BLSDriverSetNormalCurrent.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int]
    dll.MTUSB_BLSDriverSetNormalCurrent.restype = ctypes.c_int

    return dll


def main():
    dll = load_dll()

    print("\n[1] MTUSB_BLSDriverInitDevices() ...")
    n = dll.MTUSB_BLSDriverInitDevices()
    print(f"    연결된 장치 수: {n}")
    if n <= 0:
        print("    ✘ 장치가 안 잡힙니다. BLS 박스 전원(LED 켜짐) 확인, "
              "USB 케이블 재연결, BioLEDController.exe 완전 종료 후 재시도.")
        return

    print("\n[2] MTUSB_BLSDriverOpenDevice(0) ...")
    handle = dll.MTUSB_BLSDriverOpenDevice(0)
    print(f"    handle={handle}  (0 이상이면 성공, -1이면 실패)")
    if handle < 0:
        print("    ✘ 열기 실패 — 다른 프로그램(BioLEDController.exe 등)이 이미 잡고 있는지 확인.")
        return

    try:
        buf = ctypes.create_string_buffer(32)
        ret = dll.MTUSB_BLSDriverGetSerialNo(handle, buf, 32)
        print(f"\n[3] Serial No.: {buf.value.decode(errors='ignore')!r} (ret={ret})")

        mtype = dll.MTUSB_BLSDriverGetModuleType(handle)
        print(f"[4] Module Type: {mtype} ({MODULE_TYPE_NAMES.get(mtype, '?')})")

        nch = dll.MTUSB_BLSDriverGetChannels(handle)
        print(f"[5] Channels: {nch}")

        for ch in range(1, (nch if nch > 0 else 1) + 1):
            tbuf = ctypes.create_string_buffer(64)
            tret = dll.MTUSB_BLSDriverGetChannelTitle(handle, ch, tbuf)
            print(f"    채널 {ch} 이름: {tbuf.value.decode(errors='ignore')!r} (ret={tret})")

        print("\n" + "=" * 58)
        print("여기까지 정상이면 DLL 연결은 완전히 성공한 것.")
        print("실제로 LED를 켜보려면(밝기 5%, 채널 1):")
        print("  dll.MTUSB_BLSDriverSetMode(handle, 1, 1)       # NORMAL 모드")
        print("  dll.MTUSB_BLSDriverSetNormalCurrent(handle, 1, 50)  # 50 = 0.1%단위 -> 5.0%")
        answer = input("\n지금 채널 1을 5%로 3초간 켜볼까요? (y/N): ").strip().lower()
        if answer == "y":
            print("    SetMode:", dll.MTUSB_BLSDriverSetMode(handle, 1, NORMAL_MODE))
            print("    SetNormalCurrent(5.0%):", dll.MTUSB_BLSDriverSetNormalCurrent(handle, 1, 50))
            import time
            time.sleep(3)
            print("    OFF:", dll.MTUSB_BLSDriverSetMode(handle, 1, DISABLE_MODE))
    finally:
        print("\n[종료] MTUSB_BLSDriverCloseDevice() ...")
        dll.MTUSB_BLSDriverCloseDevice(handle)


if __name__ == "__main__":
    main()
