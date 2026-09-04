# -*- coding: utf-8 -*-
"""
dll_check.py — 계측기 DLL 3개가 **실제로 로드되는지** 확인한다.
================================================================
파일이 폴더에 있는 것과, 그 DLL이 실제로 로드되는 것은 다른 문제다.
KXCIclient.dll 은 MSVCR120.dll(Visual C++ 2013 x86 재배포)을 요구하는데
Windows 기본 설치에는 없다. 이게 빠지면 DLL 파일이 멀쩡히 있는데도
로드가 실패하면서 "Could not find module ... (or one of its dependencies)"
라는, 마치 경로가 틀린 것처럼 보이는 오류가 난다. 실제로 ctypes 로
열어보는 것 말고는 이 상태를 미리 잡아낼 방법이 없다.

최초설치.bat 의 마지막 검증 단계에서 호출한다. 직접 실행해도 된다:
    py -3-32 dll_check.py
성공 시 종료 코드 0, 하나라도 실패하면 1.
"""

import ctypes
import os
import sys

DLLS = ("KXCIclient.dll", "HIDDLL.dll", "Mightex_BLSDriver_SDK.dll")


def main():
    base = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__))

    bits = 8 * ctypes.sizeof(ctypes.c_void_p)
    if bits != 32:
        print("      [실패] 현재 파이썬이 %d비트입니다. DLL은 32비트 전용이라"
              " 32비트 파이썬에서만 로드됩니다." % bits)
        return 1

    bad = []
    for name in DLLS:
        path = os.path.join(base, name)
        if not os.path.exists(path):
            bad.append((name, "파일이 없습니다: %s" % path))
            continue
        try:
            ctypes.CDLL(path)
        except OSError as exc:
            bad.append((name, str(exc)))

    for name, why in bad:
        print("      [실패] %s -> %s" % (name, why))
    if bad:
        print("      → 파일이 있는데 로드가 실패했다면 대부분"
              " Visual C++ 2013 재배포 패키지(x86) 누락입니다.")
        print("        https://www.microsoft.com/en-us/download/details.aspx?id=40784")
        print("        (64비트 Windows 에서도 vcredist_x86.exe 를 받아야 합니다)")
        return 1

    print("      DLL %d개 모두 정상 로드됨." % len(DLLS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
