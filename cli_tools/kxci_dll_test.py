# -*- coding: utf-8 -*-
"""
kxci_dll_test.py — 공식 KXCIClient.DLL (ctypes) 연결 테스트
=============================================================
지금까지 raw socket으로 KXCI와 직접 텍스트 프로토콜을 주고받으려던 시도는
전부 무응답이었다. 매뉴얼 확인 결과, GPIB의 EOI는 물리적 하드웨어 신호라
printable 문자로 재현할 방법이 없고, Keithley가 이를 대신 처리해주는 전용
클라이언트 DLL(KXCIClient.DLL)을 제공한다. 이 스크립트는 그 DLL을 ctypes로
직접 불러 사용한다.

⚠ 이 DLL은 32비트(x86)이다. 32비트 파이썬에서만 로드된다.
   확인: python -c "import struct; print(struct.calcsize('P')*8)"
   64 가 나오면 python.org에서 32-bit installer로 별도 설치 필요.

바이너리 확인 사항 (objdump로 직접 검증, 2026-07-29):
  - Export: OpenKXCIConnection_C, SendKXCICommand_C,
            GetKXCISpollByte_C, CloseKXCIConnection_C  (모두 cdecl, 'ret' 사용)
  - 접미사 없는 버전(OpenKXCIConnection 등)은 stdcall('ret 0xC') — VB용, 미사용

DLL 위치: 이 스크립트와 같은 폴더에 KXCIclient.dll 을 둘 것.
"""

import ctypes
import os
import sys

DLL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "KXCIclient.dll")
IP = b"192.168.0.200"
PORT = 2105
BUF_SIZE = 2048   # 매뉴얼 C 예제의 #define MAXLEN 2048 참고


def load_dll():
    # 비트수 확인 — 안 맞으면 바로 명확한 에러 메시지로 안내
    bits = 8 * ctypes.sizeof(ctypes.c_void_p)
    print(f"[정보] 현재 파이썬: {bits}-bit  (Python {sys.version.split()[0]})")
    if bits != 32:
        raise SystemExit(
            f"\n\u2718 KXCIClient.DLL은 32비트 전용인데 현재 파이썬은 {bits}비트입니다.\n"
            "  python.org 에서 'Windows installer (32-bit)' 를 받아 별도 설치한 뒤,\n"
            "  그 32비트 python.exe 로 이 스크립트를 실행하세요.\n"
            "  (기존 64비트 파이썬은 그대로 두고 병행 설치 가능)"
        )
    if not os.path.exists(DLL_PATH):
        raise SystemExit(f"\u2718 DLL을 찾을 수 없습니다: {DLL_PATH}\n"
                         "  KXCIclient.dll 을 이 스크립트와 같은 폴더에 두세요.")

    dll = ctypes.CDLL(DLL_PATH)   # _C 함수들은 cdecl -> CDLL (WinDLL 아님)

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

    return dll


def main():
    dll = load_dll()

    sock_err = ctypes.c_int(0)
    print(f"\n[1] OpenKXCIConnection_C({IP.decode()}, {PORT}) ...")
    ret = dll.OpenKXCIConnection_C(IP, PORT, ctypes.byref(sock_err))
    print(f"    return={ret}  socket_err={sock_err.value}")
    if ret != 0:
        print("    \u26a0 return 값이 0이 아닙니다 — 매뉴얼에서 이 코드의 의미를 "
              "확인하거나, socket_err(WSAGetLastError 값)를 검색해 보세요.")

    print("\n[2] SendKXCICommand_C('US', ...) 시도 — 지금까지 시도한 조회 명령")
    resp_buf = ctypes.create_string_buffer(BUF_SIZE)
    ret2 = dll.SendKXCICommand_C(b"US", resp_buf, ctypes.byref(sock_err))
    print(f"    return={ret2}  socket_err={sock_err.value}")
    print(f"    응답 데이터: {resp_buf.value!r}")

    print("\n[3] SendKXCICommand_C('ID', ...) 추가 시도")
    resp_buf2 = ctypes.create_string_buffer(BUF_SIZE)
    ret3 = dll.SendKXCICommand_C(b"ID", resp_buf2, ctypes.byref(sock_err))
    print(f"    return={ret3}  socket_err={sock_err.value}")
    print(f"    응답 데이터: {resp_buf2.value!r}")

    print("\n[4] CloseKXCIConnection_C() ...")
    dll.CloseKXCIConnection_C()
    print("    완료")

    print("\n" + "=" * 58)
    print("위 [1]에서 return이 0이고 socket_err도 0이면 연결 자체는 성공.")
    print("[2],[3]에서 응답 데이터가 비어 있지 않으면 그 명령이 유효한 것.")
    print("모두 비어 있으면 명령 문자열 자체를 매뉴얼 GPIB command reference")
    print("표에서 다시 대조해야 합니다 (예: 'DE' 로 채널부터 정의해야 할 수도).")


if __name__ == "__main__":
    main()