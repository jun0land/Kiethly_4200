# -*- coding: utf-8 -*-
"""
BioLED Controller — Mightex BioLED(BLS 시리즈) 단독 제어 GUI
================================================
파장별로 세기(%)를 미리 저장해두고, 파장 버튼을 누르면 그 세기가
자동으로 적용된다. 매번 슬라이더를 스크롤할 필요가 없다.

세기 단위: BioLED 소프트웨어와 동일하게 "채널 최대 대비 %".
예) 530 nm에서 1 mW를 내려면 10.9 % → 그 값을 프리셋에 저장해두고 버튼 클릭.

프리셋은 파장마다, 그리고 OD(ND필터 값)별로 여러 개 저장 가능
(예: 530 nm·OD0의 0.5 mW=5.4 %, 1 mW=10.9 %). 프리셋은 bioled_presets.json에
저장되어 다음 실행 때 그대로 불러오고, pd_iv_station.py(메인 GUI)와도 공유된다.

⚠ 2026-07-30 확인: BLS-SA02-U는 시리얼(COM 포트) 장치가 아니라 **USB HID
   장치**다(Mightex SDK 매뉴얼: "the BIOLED Control driver is designed as
   a HID device"). 그래서 장치관리자에 COM 포트로 절대 안 뜨고, pyserial로
   여는 것 자체가 불가능하다 — 예전 코드의 ASCII 시리얼 명령(MODE/NORMAL/
   CURRENT)은 전부 추측이었고 틀렸다. 공식 SDK DLL
   (Mightex_BLSDriver_SDK.dll, cdecl, 32비트 전용)을 ctypes로 직접 불러쓴다
   — Keithley KXCIclient.dll과 동일한 패턴. 포트/보드레이트 설정 자체가
   필요 없다(HID라 USB에 꽂으면 그냥 잡힌다).
   DLL은 이 스크립트와 같은 폴더에 Mightex_BLSDriver_SDK.dll + HIDDLL.dll로
   있어야 한다. 세기(%)는 장치 API가 "0.1% 단위" 정수로 받는다(예: 500 =
   50.0%) — 그래서 max_mA 환산이 필요 없다.
   개별 점검: bls_dll_test.py

필요 패키지: 없음 (ctypes/tkinter 모두 표준 라이브러리)
"""

from __future__ import annotations

import ctypes
import json
import os
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

PRESET_FILE = "bioled_presets.json"
BLS_DLL_NAME = "Mightex_BLSDriver_SDK.dll"
BLS_MODE_DISABLE = 0
BLS_MODE_NORMAL = 1

# ---- 채널 기본값 (환경에 맞게 수정) ----
DEFAULT_SETTINGS = {
    # 파장 -> {"channel": BioLED 채널번호} — HID 장치라 포트/max_mA 불필요
    # 기본값을 전부 1번 포트로 둔다. 파장마다 다른 번호를 기본으로 주면
    # LED가 꽂히지 않은 포트로 명령이 나가서 "오류도 없는데 불만 안 들어오는"
    # 상황이 된다(pd_iv_station.py의 DEFAULT_BIOLED_SETTINGS 주석 참고).
    # 채널이 몇 개인 장비든 1번은 반드시 있다.
    "channels": {
        "365nm": {"channel": 1},
        "470nm": {"channel": 1},
        "530nm": {"channel": 1},
        "625nm": {"channel": 1},
    },
}

DEFAULT_OD = "OD0"
# 파장 -> OD(ND필터 값) -> [{"label": "1 mW", "percent": 10.9}, ...]
# OD로 나누는 이유: 같은 %라도 ND 필터(사람이 수동으로 낌) 유무/값에 따라
# 실제 광량이 달라지므로, 세기 프리셋을 OD별로 따로 관리해야 pd_iv_station.py
# 탭4(I-T)에서 "이 파장·이 OD"의 프리셋만 골라 쓸 수 있다.
DEFAULT_PRESETS = {
    "365nm": {},
    "470nm": {},
    "530nm": {DEFAULT_OD: [{"label": "1 mW", "percent": 10.9}]},
    "625nm": {},
}


def normalize_presets(presets):
    """예전(OD 구분 없는 평면 리스트) 포맷 파일을 만나면 {"OD0": [...]}로
    감싸 새 포맷과 호환되게 만든다 — pd_iv_station.py와 같은 파일을 공유하므로
    포맷이 어긋나면 서로 못 읽는다."""
    for wl, v in list(presets.items()):
        if isinstance(v, list):
            presets[wl] = {DEFAULT_OD: v} if v else {}
    return presets


# ==========================================================
# 장치 백엔드
# ==========================================================
class BioLEDDevice:
    def __init__(self, settings):
        self.settings = settings
        self.dll = None
        self.handle = None

    def connect(self):
        bits = 8 * ctypes.sizeof(ctypes.c_void_p)
        if bits != 32:
            raise RuntimeError(f"Mightex_BLSDriver_SDK.dll은 32비트 전용인데 현재 파이썬은 {bits}비트입니다. "
                              "py -3.13-32 로 실행하세요.")
        dll_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), BLS_DLL_NAME)
        if not os.path.exists(dll_path):
            raise RuntimeError(f"DLL을 찾을 수 없습니다: {dll_path}")

        dll = ctypes.CDLL(dll_path)
        dll.MTUSB_BLSDriverInitDevices.restype = ctypes.c_int
        dll.MTUSB_BLSDriverOpenDevice.argtypes = [ctypes.c_int]
        dll.MTUSB_BLSDriverOpenDevice.restype = ctypes.c_int
        dll.MTUSB_BLSDriverCloseDevice.argtypes = [ctypes.c_int]
        dll.MTUSB_BLSDriverCloseDevice.restype = ctypes.c_int
        dll.MTUSB_BLSDriverSetMode.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int]
        dll.MTUSB_BLSDriverSetMode.restype = ctypes.c_int
        dll.MTUSB_BLSDriverSetNormalCurrent.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int]
        dll.MTUSB_BLSDriverSetNormalCurrent.restype = ctypes.c_int
        self.dll = dll

        n = dll.MTUSB_BLSDriverInitDevices()
        if n <= 0:
            raise RuntimeError("BioLED 장치를 찾지 못했습니다 — 전원/USB 케이블/"
                              "BioLEDController.exe 종료 여부를 확인하세요.")
        handle = dll.MTUSB_BLSDriverOpenDevice(0)
        if handle < 0:
            raise RuntimeError("BioLED 장치 열기 실패 — 다른 프로그램이 이미 사용 중일 수 있습니다.")
        self.handle = handle

    def send_percent(self, wavelength, percent):
        """해당 파장 채널에 percent(%, 0~100)를 정전류(NORMAL 모드)로 인가.
        장치 API는 '0.1%' 단위 정수를 받는다(예: 50.0% -> 500)."""
        ch = self.settings["channels"][wavelength]["channel"]
        self.dll.MTUSB_BLSDriverSetMode(self.handle, ch, BLS_MODE_NORMAL)
        self.dll.MTUSB_BLSDriverSetNormalCurrent(self.handle, ch, int(round(percent * 10)))
        return percent

    def off(self, wavelength):
        ch = self.settings["channels"][wavelength]["channel"]
        self.dll.MTUSB_BLSDriverSetMode(self.handle, ch, BLS_MODE_DISABLE)

    def all_off(self):
        for wl in self.settings["channels"]:
            try:
                self.off(wl)
            except Exception:
                pass

    def close(self):
        if self.handle is not None:
            self.all_off()
            self.dll.MTUSB_BLSDriverCloseDevice(self.handle)
            self.handle = None


# ==========================================================
# 저장/로드
# ==========================================================
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


# ==========================================================
# GUI
# ==========================================================
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("BioLED Controller")
        self.geometry("560x520")

        self.settings = load_json("bioled_settings.json", DEFAULT_SETTINGS)
        self.presets = normalize_presets(load_json(PRESET_FILE, DEFAULT_PRESETS))
        self.dev = BioLEDDevice(self.settings)
        self.connected = False
        self.active_wl = None
        self.od_vars = {}   # wl -> tk.StringVar (현재 선택된 OD)

        self._build()

    # ---------- UI 구성 ----------
    def _build(self):
        top = ttk.Frame(self, padding=10)
        top.pack(fill="x")

        self.conn_btn = ttk.Button(top, text="연결", command=self.toggle_connect)
        self.conn_btn.grid(row=0, column=0, padx=(0, 8))
        self.status = ttk.Label(top, text="● 미연결", foreground="gray")
        self.status.grid(row=0, column=1, padx=4)
        ttk.Label(top, text="(USB HID 장치라 포트 설정 불필요 — 그냥 연결만 누르면 됨)",
                 foreground="gray").grid(row=0, column=2, padx=8, sticky="w")

        ttk.Button(top, text="전체 OFF", command=self.all_off).grid(
            row=0, column=4, padx=4)

        # 파장 탭
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=10, pady=10)
        self.wl_frames = {}
        for wl in self.settings["channels"]:
            self._build_wl_tab(wl)

        # 하단 현재 상태
        self.current_lbl = ttk.Label(self, text="현재 출력: 없음", padding=8)
        self.current_lbl.pack(fill="x")

    def _od_list(self, wl):
        ods = sorted(self.presets.get(wl, {}).keys())
        return ods or [DEFAULT_OD]

    def _build_wl_tab(self, wl):
        frame = ttk.Frame(self.nb, padding=10)
        self.nb.add(frame, text=wl)
        self.wl_frames[wl] = frame

        ttk.Label(frame, text=f"{wl} 프리셋 (클릭하면 즉시 적용)",
                  font=("", 10, "bold")).pack(anchor="w")

        od_row = ttk.Frame(frame)
        od_row.pack(fill="x", pady=(2, 6))
        ttk.Label(od_row, text="OD(ND필터):").pack(side="left")
        od_var = tk.StringVar(value=self._od_list(wl)[0])
        self.od_vars[wl] = od_var
        od_combo = ttk.Combobox(od_row, textvariable=od_var, values=self._od_list(wl), width=8)
        od_combo.pack(side="left", padx=4)
        od_combo.bind("<<ComboboxSelected>>", lambda e, w=wl: self._refresh_preset_buttons(w))
        od_var.trace_add("write", lambda *_a, w=wl: self._refresh_preset_buttons(w))
        ttk.Label(od_row, text="(새 OD는 직접 입력 후 프리셋을 저장하면 생성됨)",
                 foreground="gray").pack(side="left", padx=6)

        btn_area = ttk.Frame(frame)
        btn_area.pack(fill="x", pady=6)
        self._refresh_preset_buttons(wl, btn_area)

        # 수동 % 입력
        manual = ttk.Frame(frame)
        manual.pack(fill="x", pady=10)
        ttk.Label(manual, text="수동 %:").pack(side="left")
        var = tk.DoubleVar(value=0.0)
        ttk.Entry(manual, textvariable=var, width=8).pack(side="left", padx=4)
        ttk.Button(manual, text="적용",
                   command=lambda w=wl, v=var: self.apply_percent(w, v.get())
                   ).pack(side="left", padx=4)
        ttk.Button(manual, text="이 %를 프리셋으로 저장",
                   command=lambda w=wl, v=var: self.add_preset(w, v.get())
                   ).pack(side="left", padx=4)
        ttk.Button(manual, text=f"{wl} OFF",
                   command=lambda w=wl: self.off(w)).pack(side="right")

    def _refresh_preset_buttons(self, wl, area=None):
        if area is None:
            # 프레임 재구성: 탭 내 첫 btn_area 찾기
            frame = self.wl_frames[wl]
            for child in frame.winfo_children():
                if isinstance(child, ttk.Frame) and getattr(child, "_is_btnarea", False):
                    area = child
                    break
            if area is None:
                return
        area._is_btnarea = True
        for w in area.winfo_children():
            w.destroy()
        od = self.od_vars[wl].get().strip() or DEFAULT_OD
        for i, p in enumerate(self.presets.get(wl, {}).get(od, [])):
            b = ttk.Button(
                area, text=f"{p['label']}\n({p['percent']} %)",
                command=lambda w=wl, pc=p["percent"]: self.apply_percent(w, pc))
            b.grid(row=i // 4, column=i % 4, padx=4, pady=4, sticky="ew")
            b.bind("<Button-3>",
                   lambda e, w=wl, idx=i: self.delete_preset(w, idx))
        ttk.Label(area, text="(프리셋 우클릭 = 삭제, 위 OD 칸으로 세트 전환)",
                  foreground="gray").grid(row=99, column=0, columnspan=4,
                                          sticky="w", pady=(4, 0))

    # ---------- 동작 ----------
    def toggle_connect(self):
        if self.connected:
            self.dev.close()
            self.connected = False
            self.status.config(text="● 미연결", foreground="gray")
            self.conn_btn.config(text="연결")
            return
        try:
            self.dev.connect()
            self.connected = True
            self.status.config(text="● 연결됨", foreground="green")
            self.conn_btn.config(text="해제")
        except Exception as e:
            messagebox.showerror(
                "연결 실패",
                f"{e}\n\nBLS 박스 전원이 켜져 있는지, USB 케이블이 데이터선 포함인지, "
                "BioLEDController.exe가 완전히 종료됐는지 확인하세요.")

    def apply_percent(self, wl, percent):
        if not self.connected:
            messagebox.showwarning("미연결", "먼저 장치를 연결하세요.")
            return
        try:
            # 다른 파장이 켜져 있으면 끄고(단일 광원 측정 가정) 이 파장만 인가
            if self.active_wl and self.active_wl != wl:
                self.dev.off(self.active_wl)
            self.dev.send_percent(wl, percent)
            self.active_wl = wl
            self.current_lbl.config(text=f"현재 출력: {wl} @ {percent} %")
        except Exception as e:
            messagebox.showerror("전송 실패", str(e))

    def off(self, wl):
        if not self.connected:
            return
        try:
            self.dev.off(wl)
            if self.active_wl == wl:
                self.active_wl = None
                self.current_lbl.config(text="현재 출력: 없음")
        except Exception as e:
            messagebox.showerror("실패", str(e))

    def all_off(self):
        if not self.connected:
            return
        self.dev.all_off()
        self.active_wl = None
        self.current_lbl.config(text="현재 출력: 없음")

    def add_preset(self, wl, percent):
        od = self.od_vars[wl].get().strip() or DEFAULT_OD
        label = simpledialog.askstring(
            "프리셋 저장", f"{wl} · {od} · {percent} % 의 이름 (예: 1 mW):", parent=self)
        if not label:
            return
        self.presets.setdefault(wl, {}).setdefault(od, []).append(
            {"label": label, "percent": float(percent)})
        save_json(PRESET_FILE, self.presets)
        # 새 OD를 타이핑해서 처음 저장한 경우 콤보박스 목록도 갱신
        self.od_vars[wl].set(od)
        for child in self.wl_frames[wl].winfo_children():
            if isinstance(child, ttk.Frame):
                for gc in child.winfo_children():
                    if isinstance(gc, ttk.Combobox):
                        gc.config(values=self._od_list(wl))
        self._refresh_preset_buttons(wl)

    def delete_preset(self, wl, idx):
        od = self.od_vars[wl].get().strip() or DEFAULT_OD
        try:
            p = self.presets[wl][od][idx]
        except (KeyError, IndexError):
            return
        if messagebox.askyesno("삭제", f"'{wl} · {od} · {p['label']} ({p['percent']} %)' 삭제?"):
            self.presets[wl][od].pop(idx)
            save_json(PRESET_FILE, self.presets)
            self._refresh_preset_buttons(wl)

    def destroy(self):
        try:
            if self.connected:
                self.dev.close()
        finally:
            super().destroy()


if __name__ == "__main__":
    App().mainloop()