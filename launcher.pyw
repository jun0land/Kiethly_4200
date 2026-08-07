# -*- coding: utf-8 -*-
"""
launcher.pyw — PD 측정 스테이션 런처
==========================================================
바탕화면 바로가기로 두고 쓰는 실행/업데이트 창.

왜 exe로 안 만들고 이렇게 하는가:
  PyInstaller 같은 걸로 exe를 만들면 코드가 그 안에 굳어버려서, 수정할
  때마다 새 exe를 다시 만들어 전달해야 한다. 반면 이 런처는 코드를 git
  저장소로 두고 '업데이트' 버튼이 git pull을 대신 눌러주는 방식이라,
  **런처는 한 번만 배포하면 되고 이후 수정은 버튼 하나로 반영된다.**

확장자가 .pyw 인 이유: pythonw.exe로 실행돼 검은 콘솔 창이 안 뜬다.

이 런처 자체는 아무 파이썬(32/64비트)으로 돌아도 되지만, 측정 프로그램은
반드시 32비트로 띄운다(KXCIclient.dll / Mightex DLL이 32비트 전용).
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import messagebox, ttk

APP_DIR = os.path.dirname(os.path.abspath(__file__))
MAIN_SCRIPT = "pd_iv_station.py"

# (import 이름, pip 패키지명) — import 이름과 패키지명이 다른 경우가 있다
# sv-ttk는 쓰지 않는다 — 위젯이 PNG 스프라이트로 그려져 강조색을 파란색에서
# 바꿀 수 없었다(ui_theme.py 주석 참고). 테마는 내장 clam 을 직접 칠해서 쓴다.
PACKAGES = [
    ("openpyxl", "openpyxl"),   # 엑셀 내보내기 (필수)
    ("serial", "pyserial"),     # 레거시 cli_tools 용
]

# 콘솔 창이 깜빡이지 않게 (Windows 전용 플래그)
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def run(cmd, cwd=APP_DIR, timeout=120):
    """명령을 실행하고 (성공여부, 출력문자열)을 돌려준다.
    git 출력은 한글 Windows에서 cp949로 나오는 경우가 있어 errors='replace'."""
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, timeout=timeout,
                           creationflags=NO_WINDOW)
    except FileNotFoundError:
        return False, f"실행 파일을 찾을 수 없습니다: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return False, f"시간 초과({timeout}초): {' '.join(cmd)}"
    out = (p.stdout or b"").decode("utf-8", errors="replace")
    err = (p.stderr or b"").decode("utf-8", errors="replace")
    return p.returncode == 0, (out + err).strip()


def find_py32():
    """32비트 파이썬 실행 방법을 찾는다. 버전을 하드코딩하지 않는다."""
    for args in (["py", "-3-32"], ["py", "-3.13-32"], ["py", "-3.12-32"]):
        ok, out = run(args + ["-c", "import struct;print(struct.calcsize('P')*8)"], timeout=20)
        if ok and out.strip().endswith("32"):
            return args
    # 마지막 수단: 지금 이 런처가 32비트면 그걸 쓴다
    if 8 * __import__("ctypes").sizeof(__import__("ctypes").c_void_p) == 32:
        return [sys.executable]
    return None


class Launcher(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("PD 측정 스테이션 — 런처")
        self.geometry("760x480")
        self.minsize(680, 420)

        # 측정 프로그램과 같은 디자인 토큰 적용 (실패해도 그냥 기본 모양)
        try:
            sys.path.insert(0, APP_DIR)
            import ui_theme
            ui_theme.apply(self)
        except Exception:  # noqa: BLE001
            pass

        head = ttk.Frame(self, padding=12)
        head.pack(fill="x")
        ttk.Label(head, text="PD 측정 스테이션", style="H1.TLabel").pack(anchor="w")
        self.ver_lbl = ttk.Label(head, text="버전 확인 중…", style="Muted.TLabel")
        self.ver_lbl.pack(anchor="w", pady=(2, 0))

        btns = ttk.Frame(self, padding=(12, 0))
        btns.pack(fill="x")
        self.run_btn = ttk.Button(btns, text="▶  측정 프로그램 실행", style="Accent.TButton",
                                  command=self.launch_app)
        self.run_btn.pack(side="left", ipady=6, ipadx=10)
        self.upd_btn = ttk.Button(btns, text="⟳  업데이트 (git pull)", command=self.do_update)
        self.upd_btn.pack(side="left", padx=8, ipady=6, ipadx=6)
        self.dep_btn = ttk.Button(btns, text="⤓  필수 구성요소 설치/확인", command=self.do_install_deps)
        self.dep_btn.pack(side="left", padx=(0, 8), ipady=6, ipadx=4)
        ttk.Button(btns, text="폴더 열기", command=lambda: os.startfile(APP_DIR)).pack(side="left", padx=4)

        ttk.Label(self, text="상태 / 로그", padding=(12, 8, 12, 0)).pack(anchor="w")
        box = ttk.Frame(self, padding=(12, 0, 12, 12))
        box.pack(fill="both", expand=True)
        sb = ttk.Scrollbar(box, orient="vertical")
        self.log = tk.Text(box, height=12, yscrollcommand=sb.set, wrap="word")
        sb.config(command=self.log.yview)
        sb.pack(side="right", fill="y")
        self.log.pack(side="left", fill="both", expand=True)

        self.write(f"작업 폴더: {APP_DIR}")
        self.after(100, self.refresh_version)

    def write(self, msg):
        self.log.insert("end", str(msg).rstrip() + "\n")
        self.log.see("end")
        self.update_idletasks()

    # ---------- 버전 표시 ----------
    def refresh_version(self):
        if not os.path.isdir(os.path.join(APP_DIR, ".git")):
            self.ver_lbl.config(text="⚠ git 저장소가 아닙니다 — 업데이트 버튼을 쓸 수 없습니다",
                                foreground="#a33")
            self.upd_btn.state(["disabled"])
            self.write("이 폴더는 git clone으로 받은 게 아니라서 업데이트 기능이 비활성화됩니다.\n"
                       "  업데이트를 쓰려면 다음처럼 받아주세요:\n"
                       "  git clone https://github.com/jun0land/Kiethly_4200.git")
            return
        ok, out = run(["git", "log", "-1", "--format=%h  %ad  %s", "--date=format:%Y-%m-%d %H:%M"])
        if ok:
            self.ver_lbl.config(text=f"현재 버전: {out}", foreground="#555")
        else:
            self.ver_lbl.config(text="git을 찾을 수 없습니다 (Git for Windows 설치 필요)",
                                foreground="#a33")
            self.upd_btn.state(["disabled"])
            self.write(out)

    # ---------- 실행 ----------
    def launch_app(self):
        script = os.path.join(APP_DIR, MAIN_SCRIPT)
        if not os.path.exists(script):
            messagebox.showerror("파일 없음", f"{MAIN_SCRIPT} 을 찾을 수 없습니다:\n{script}")
            return
        self.write("32비트 파이썬을 찾는 중…")
        py = find_py32()
        if py is None:
            self.write("✘ 32비트 파이썬을 찾지 못했습니다.")
            messagebox.showerror(
                "32비트 파이썬 필요",
                "이 프로그램은 32비트 파이썬이 필요합니다.\n"
                "(Keithley·BioLED DLL이 32비트 전용)\n\n"
                "python.org 에서 'Windows installer (32-bit)'를 설치한 뒤\n"
                "다시 시도하세요.")
            return
        self.write(f"실행: {' '.join(py)} {MAIN_SCRIPT}")
        try:
            # 런처는 계속 떠 있고 측정 프로그램은 별도 프로세스로 띄운다
            subprocess.Popen(py + [script], cwd=APP_DIR, creationflags=NO_WINDOW)
            self.write("측정 프로그램을 시작했습니다. (창이 뜨기까지 몇 초 걸릴 수 있음)")
        except Exception as e:  # noqa: BLE001
            self.write(f"✘ 실행 실패: {e}")
            messagebox.showerror("실행 실패", str(e))

    # ---------- 필수 구성요소 ----------
    def do_install_deps(self):
        """측정 프로그램이 필요로 하는 파이썬 패키지를 설치/확인한다.

        파이썬 자체가 없는 컴퓨터는 이 런처가 아예 안 뜨므로, 그 경우는
        '최초설치.bat'(파이썬 없이 도는 배치 파일)이 담당한다."""
        self.dep_btn.state(["disabled"])
        self.upd_btn.state(["disabled"])
        self.run_btn.state(["disabled"])
        self.write("\n=== 필수 구성요소 확인 ===")
        threading.Thread(target=self._deps_worker, daemon=True).start()

    def _deps_worker(self):
        try:
            py = find_py32()
            if py is None:
                self.write("✘ 32비트 파이썬을 찾지 못했습니다.")
                self.write("  → '최초설치.bat' 을 실행하세요 (파이썬까지 자동 설치합니다).")
                return
            self.write(f"32비트 파이썬: {' '.join(py)}")

            need = []
            for mod, pkg in PACKAGES:
                ok, _ = run(py + ["-c", f"import {mod}"], timeout=30)
                self.write(f"  {'✔' if ok else '✘'} {pkg}" + ("" if ok else "  (설치 필요)"))
                if not ok:
                    need.append(pkg)

            if not need:
                self.write("✔ 필요한 패키지가 모두 설치돼 있습니다.")
                return

            self.write(f"설치 시작: {', '.join(need)} … (인터넷 필요, 잠시 걸립니다)")
            ok, out = run(py + ["-m", "pip", "install", "--upgrade"] + need, timeout=600)
            self.write(out[-2000:] if out else "(출력 없음)")
            if ok:
                self.write("✔ 설치 완료. 측정 프로그램을 실행하면 반영됩니다.")
            else:
                self.write("✘ 설치 실패 — 인터넷 연결 또는 권한 문제일 수 있습니다.")
        finally:
            self.after(0, self._deps_done)

    def _deps_done(self):
        for b in (self.dep_btn, self.upd_btn, self.run_btn):
            b.state(["!disabled"])
        self.write("=== 확인 종료 ===\n")

    # ---------- 업데이트 ----------
    def do_update(self):
        self.upd_btn.state(["disabled"])
        self.run_btn.state(["disabled"])
        self.write("\n=== 업데이트 시작 ===")
        threading.Thread(target=self._update_worker, daemon=True).start()

    def _update_worker(self):
        try:
            ok, out = run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
            branch = out.strip() if ok else "main"
            self.write(f"브랜치: {branch}")

            # 내 쪽에 커밋 안 된 수정이 있으면 pull이 막힐 수 있으니 미리 알린다
            ok, out = run(["git", "status", "--porcelain"])
            if ok and out.strip():
                self.write("⚠ 로컬에 수정된 파일이 있습니다:")
                self.write(out)
                self.write("  (설정 파일이라면 무시해도 됩니다 — .gitignore에 등록돼 있으면 여기 안 뜹니다)")

            ok, out = run(["git", "pull", "--ff-only", "origin", branch], timeout=180)
            self.write(out or "(출력 없음)")
            if ok:
                if "Already up to date" in out or "이미 최신" in out:
                    self.write("✔ 이미 최신 버전입니다.")
                else:
                    self.write("✔ 업데이트 완료. 측정 프로그램을 다시 실행하면 반영됩니다.")
            else:
                self.write("✘ 업데이트 실패.")
                self.write("  흔한 원인:\n"
                           "   · 인터넷/GitHub 로그인 문제\n"
                           "   · 이 폴더에서 코드를 직접 고쳐서 충돌 (git status 확인)\n"
                           "   · --ff-only 라서 갈라진 이력은 자동 병합하지 않음")
        finally:
            self.after(0, self._update_done)

    def _update_done(self):
        self.upd_btn.state(["!disabled"])
        self.run_btn.state(["!disabled"])
        self.refresh_version()
        self.write("=== 업데이트 종료 ===\n")


if __name__ == "__main__":
    Launcher().mainloop()
