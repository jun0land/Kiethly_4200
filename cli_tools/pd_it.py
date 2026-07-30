# -*- coding: utf-8 -*-
"""
pd_it_measure.py — Keithley 4200(KXCI) + Mightex BioLED I-T 측정
================================================================
※ I-V는 수동 측정으로 진행하기로 하여, 이 스크립트는 I-T 전용이다.
※ Keithley 통신 케이블(GPIB-USB) 확보 전까지는 --dry-run 으로 타임라인/Range
   결정 로직만 점검할 수 있다 (LED·Keithley 미연결 상태로 시퀀스만 출력).

동작 개요
1) ND 필터는 글러브박스 안에서 사람이 수동으로 끼운다. 프로그램엔 [파장, OD]만.
2) config에는 파장×OD별로 파워미터 사전 실측 세기(mW, 오름차순)와
   그 세기를 내는 BioLED 세기(%)가 1:1로 등록돼 있다. (LED 구동 전류가 아니라 %)
3) 시퀀스: dark → P1 → dark → P2 → ... → dark → Pn → dark(끝)
   ※ 끝에도 dark 한 구간이 들어간다.
4) Range I 정책: 이 [파장, OD] 세트의 최대 세기(Pn) 기준으로 세그먼트 전체
   (dark 포함) 하나의 고정 Range I. OD가 다르면 Range 달라도 됨. dark도 같은 Range.
5) dark/light 구간 길이는 실행 시 직접 입력(--dark-s / --light-s), 미지정 시
   config 기본값. 세기별로 light 길이를 다르게 주고 싶으면 config의 light_s 사용.

[연결 구조]  PC(Wi-Fi) → ipTIME Extender-A3MU → Cat.6 랜선 → K4200 Ethernet
             K4200 고정 IP 192.168.0.200 / 서브넷 255.255.255.0 / GW 192.168.0.1
             PyVISA Raw Socket:  TCPIP::192.168.0.200::2105::SOCKET

[구동 전제]  ① K4200에서 KITE 완전 종료 (외부 통신 충돌 방지)
             ② KXCI 실행(활성화) 상태여야 원격 명령 수신
             ③ BioLED는 이 PC에 USB로 연결 (Mightex 전용 SW는 종료)

필요 패키지: pip install pyvisa pyvisa-py pyserial
  └ pyvisa-py = 순수 파이썬 백엔드. NI-VISA 없이 TCPIP SOCKET 사용 가능

첫 실행 시 반드시:  python pd_it_measure.py --test-connection
[VERIFY] 주석 = KXCI Reference Manual과 명령 대조 필요
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import time
from datetime import datetime

# ==========================================================
# config 스키마 (없으면 예시 생성)
# ==========================================================
DEFAULT_CONFIG = {
    "keithley_resource": "TCPIP::192.168.0.200::2105::SOCKET",
    "visa_backend": "@py",          # pyvisa-py 사용. NI-VISA 쓰려면 "" 로 변경
    "visa_timeout_ms": 120000,      # 장시간 I-T 측정 대비
    "mightex_port": "COM4",
    "mightex_baud": 9600,
    # 파장 -> {channel, max_mA}
    "channels": {
        "530nm": {"channel": 3, "max_mA": 1000},
        "850nm": {"channel": 4, "max_mA": 1000},
    },
    "it": {
        "bias_V": -1.0,
        "dark_s": 5.0,          # dark 구간 기본 길이 (--dark-s로 덮어쓰기)
        "light_s": 5.0,         # light 구간 기본 길이 (--light-s로 덮어쓰기)
        "sample_interval_s": 0.05,
        "compliance_A": 1e-3,
        "range_margin": 3.0,
        # 파장 -> OD -> {powers_mW(오름차순), percents(%, 1:1), expected_imax_A}
        "powers": {
            "530nm": {
                "OD0": {
                    "powers_mW": [0.1, 0.2, 0.5, 1.0],
                    "percents":  [1.1, 2.2, 5.4, 10.9],   # BioLED 세기(%)
                    "expected_imax_A": None               # null=프리스캔 실측
                },
                "OD1": {
                    "powers_mW": [0.01, 0.02, 0.05, 0.1],
                    "percents":  [1.1, 2.2, 5.4, 10.9],
                    "expected_imax_A": None
                }
            }
        }
    },
    "output_dir": "it_data",
    "sample_name": "FAPbI3_Si"
}

FIXED_RANGES_A = [1e-9, 1e-8, 1e-7, 1e-6, 1e-5, 1e-4, 1e-3, 1e-2, 1e-1]


def pick_fixed_range(i_max_A, margin):
    need = abs(i_max_A) * margin
    for r in FIXED_RANGES_A:
        if r >= need:
            return r
    return FIXED_RANGES_A[-1]


# ==========================================================
# Mightex BioLED (세기 = %)
# ==========================================================
class MightexBioLED:
    def __init__(self, port, baud=9600, timeout=1.0, dry=False):
        self.dry = dry
        if dry:
            self.ser = None
            return
        import serial
        self.ser = serial.Serial(port, baudrate=baud, timeout=timeout)
        time.sleep(0.3)
        self._cmd("ECHOOFF")

    def _cmd(self, s):
        if self.dry:
            print(f"    [LED] {s}")
            return ""
        self.ser.reset_input_buffer()
        self.ser.write((s + "\n\r").encode("ascii"))
        time.sleep(0.03)
        return self.ser.read_all().decode(errors="ignore").strip()

    def set_percent(self, ch_info, percent):
        """percent(%)를 채널 최대 전류 기준 mA로 환산해 인가."""
        imax = ch_info["max_mA"]
        cur = round(imax * percent / 100.0)
        self._cmd(f"MODE {ch_info['channel']} 1")
        self._cmd(f"NORMAL {ch_info['channel']} {int(imax)} {int(cur)}")
        self._cmd(f"CURRENT {ch_info['channel']} {int(cur)}")
        return cur

    def off(self, ch_info):
        self._cmd(f"MODE {ch_info['channel']} 0")

    def close(self):
        if not self.dry and self.ser:
            self.ser.close()


# ==========================================================
# Keithley 4200 (KXCI) — I-T 샘플링
# ==========================================================
class Keithley4200:
    def __init__(self, resource, dry=False, backend="@py", timeout_ms=120000):
        self.dry = dry
        if dry:
            self.inst = None
            return
        import pyvisa
        # backend="@py" -> pyvisa-py(NI-VISA 불필요). ""  -> 시스템 기본(NI-VISA)
        rm = pyvisa.ResourceManager(backend) if backend else pyvisa.ResourceManager()
        # Raw Socket 은 종단문자를 명시하지 않으면 명령이 씹히거나 타임아웃 난다
        self.inst = rm.open_resource(
            resource,
            read_termination="\n",
            write_termination="\n",
            timeout=timeout_ms,
        )
        print(f"[4200] 연결: {resource}")
        try:
            print(f"[4200] 응답: {self.inst.query('ID').strip()}")   # [VERIFY] KXCI 식별 명령
        except Exception as e:
            print(f"[4200] ⚠ ID 조회 실패({e}) — KXCI 실행 상태와 종단문자를 확인하세요")

    def _w(self, cmd):
        if self.dry:
            print(f"    [4200] {cmd}")
            return
        self.inst.write(cmd)

    # KXCI 응답에는 채널 헤더(N1A, IA 등)와 지수 표기(E-06)가 섞여 온다.
    # lstrip 으로 접두문자를 깎는 방식은 헤더 형태가 바뀌면 깨지므로 정규식으로 추출.
    _NUM = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")

    def _fetch(self, name):
        if self.dry:
            return []
        raw = self.inst.query(f"DO '{name}'")
        out = []
        for tok in raw.split(","):
            m = self._NUM.search(tok)
            if m:
                out.append(float(m.group()))
        return out

    def wait_done(self, poll_s=0.5):
        if self.dry:
            return
        while True:
            try:
                if "1" not in self.inst.query("SP"):   # [VERIFY]
                    return
            except Exception:
                pass
            time.sleep(poll_s)

    def it_start(self, bias_V, total_s, interval_s, compliance_A, fixed_range_A):
        n = int(total_s / interval_s) + 1
        self._w("DE")
        self._w("CH1,'VA','IA',1,1")
        self._w("SS")
        self._w(f"VC1,{bias_V},{compliance_A}")   # 정전압 소스
        self._w("SM")
        self._w("WT 0")
        self._w(f"IN {interval_s:g}")             # [VERIFY] 샘플 간격
        self._w(f"NR {n}")                        # [VERIFY] 포인트 수
        self._w("DM2")
        if fixed_range_A is not None:
            self._w(f"RG1,{fixed_range_A:g}")     # [VERIFY] 고정 레인지
        self._w("MD")
        self._w("ME1")
        return n

    def it_collect(self):
        self.wait_done()
        t = self._fetch("T")
        i = self._fetch("IA")
        if not t:
            t = list(range(len(i)))
        return list(zip(t, i))

    def close(self):
        if not self.dry and self.inst:
            self.inst.close()


# ==========================================================
# 저장
# ==========================================================
def save_csv(path, header, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    print(f"    -> 저장: {path}")


# ==========================================================
# I-T 실행
# ==========================================================
def run_it(cfg, smu, led, wavelength, od, bias_V, dark_s, light_s):
    itc = cfg["it"]
    entry = itc["powers"][wavelength][od]
    powers = entry["powers_mW"]
    percents = entry["percents"]
    assert len(powers) == len(percents), "powers_mW와 percents 길이 불일치"
    assert powers == sorted(powers), "powers_mW는 오름차순이어야 합니다"

    ch = cfg["channels"][wavelength]

    # --- Range I 결정: 이 [파장, OD]의 최대 세기 기준 (dark 포함 공통) ---
    exp = entry.get("expected_imax_A")
    if exp is None:
        print(f"[IT] 프리스캔: {wavelength}/{od} 최대 세기({powers[-1]} mW, "
              f"{percents[-1]} %)에서 {bias_V} V 전류 실측 ...")
        led.set_percent(ch, percents[-1])
        time.sleep(1.0)
        smu.it_start(bias_V, 2.0, 0.2, itc["compliance_A"], None)
        data = smu.it_collect()
        led.off(ch)
        exp = max((abs(i) for _, i in data), default=itc["compliance_A"])
        print(f"    실측 |I|max = {exp:.3e} A")
    fixed_range = pick_fixed_range(exp, itc["range_margin"])
    print(f"[IT] 고정 Range I = {fixed_range:g} A  (dark 포함 세트 공통)")

    # --- 타임라인: dark, P1, dark, P2, ..., dark, Pn, dark(끝) ---
    timeline = [(None, "dark", dark_s)]     # 시작 dark
    for p, pc in zip(powers, percents):
        timeline.append((pc, f"{p}mW", light_s))
        timeline.append((None, "dark", dark_s))   # 각 light 뒤 dark (끝 포함)
    total_s = sum(d for _, _, d in timeline)
    print(f"[IT] {len(timeline)}구간, 총 {total_s:.0f}s, bias {bias_V} V")
    print(f"     dark={dark_s}s, light={light_s}s, 끝은 dark로 종료")

    # --- 샘플링 시작(논블로킹) + LED 타임라인 병렬 ---
    led.off(ch)
    smu.it_start(bias_V, total_s + 1.0, itc["sample_interval_s"],
                 itc["compliance_A"], fixed_range)
    t0 = time.time()
    events = []
    elapsed_target = 0.0
    for level, label, dur in timeline:
        if level is None:
            led.off(ch)
        else:
            led.set_percent(ch, level)
        events.append((round(time.time() - t0, 3), label))
        elapsed_target += dur
        edge = t0 + elapsed_target
        while time.time() < edge:
            time.sleep(0.01)
    led.off(ch)

    data = smu.it_collect()
    stamp = datetime.now().strftime("%y%m%d_%H%M")
    outdir = os.path.join(cfg["output_dir"], f"IT_{stamp}")
    base = f"{cfg['sample_name']}_{wavelength}_{od}_{bias_V:+.0f}V"
    save_csv(os.path.join(outdir, base + "_IT.csv"),
             ["Time (s)", "Current (A)"], data)
    save_csv(os.path.join(outdir, base + "_events.csv"),
             ["Elapsed (s)", "Segment"], events)
    print("[IT] 완료.")


# ==========================================================
# 연결 점검 — 첫 실행 시 이것부터
# ==========================================================
def test_connection(cfg):
    """Keithley 소켓 통신과 BioLED 시리얼을 순서대로 점검한다.
    실패 지점을 좁혀 주는 것이 목적이므로, 각 단계를 개별적으로 보고한다."""
    ok = True

    print("=" * 58)
    print("[1] Keithley 4200 (TCPIP SOCKET)")
    print(f"    resource : {cfg['keithley_resource']}")
    print(f"    backend  : {cfg.get('visa_backend') or '시스템 기본(NI-VISA)'}")
    try:
        import pyvisa
        be = cfg.get("visa_backend", "@py")
        rm = pyvisa.ResourceManager(be) if be else pyvisa.ResourceManager()
        inst = rm.open_resource(
            cfg["keithley_resource"],
            read_termination="\n", write_termination="\n",
            timeout=10000,          # 점검은 짧게
        )
        print("    소켓 열림 ✔")
        try:
            print(f"    ID 응답  : {inst.query('ID').strip()}  ✔")
        except Exception as e:
            ok = False
            print(f"    ID 응답  : ✘ {e}")
            print("      → KITE 종료 / KXCI 실행 상태 확인")
            print("      → 응답이 '\\n' 으로 끝나지 않으면 read_termination 을 '\\r' 등으로 변경")
        inst.close()
    except Exception as e:
        ok = False
        print(f"    소켓 열기 실패 ✘ {e}")
        print("      → ping 192.168.0.200 먼저 확인")
        print("      → pip install pyvisa-py 확인")

    print("\n[2] Mightex BioLED (USB 시리얼)")
    print(f"    port : {cfg['mightex_port']}")
    try:
        led = MightexBioLED(cfg["mightex_port"], cfg["mightex_baud"])
        print("    포트 열림 ✔")
        led.close()
    except Exception as e:
        ok = False
        print(f"    포트 열기 실패 ✘ {e}")
        print("      → 장치관리자에서 COM 번호 확인 / Mightex 전용 SW 종료")

    print("\n" + "=" * 58)
    print("결과:", "모두 정상 — 측정 실행 가능" if ok else "위 ✘ 항목을 해결한 뒤 재시도")
    return ok


# ==========================================================
# 진입점
# ==========================================================
def main():
    ap = argparse.ArgumentParser(description="4200+BioLED I-T 측정")
    ap.add_argument("--config", default="it_config.json")
    ap.add_argument("--wavelength", help="예: 530nm  (--test-connection 시 불필요)")
    ap.add_argument("--od", help="예: OD1  (--test-connection 시 불필요)")
    ap.add_argument("--test-connection", action="store_true",
                    help="장비 연결만 점검하고 종료 (첫 실행 시 권장)")
    ap.add_argument("--bias", type=float, help="바이어스(V), 미지정 시 config")
    ap.add_argument("--dark-s", type=float, help="dark 구간 길이(s), 미지정 시 config")
    ap.add_argument("--light-s", type=float, help="light 구간 길이(s), 미지정 시 config")
    ap.add_argument("--dry-run", action="store_true",
                    help="장치 없이 시퀀스/Range 로직만 출력")
    args = ap.parse_args()

    if os.path.exists(args.config):
        with open(args.config, encoding="utf-8") as f:
            cfg = json.load(f)
    else:
        with open(args.config, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, indent=2, ensure_ascii=False)
        print(f"config 생성: {args.config} — 값 채운 뒤 재실행")
        return

    itc = cfg["it"]
    bias = itc["bias_V"] if args.bias is None else args.bias
    dark_s = itc["dark_s"] if args.dark_s is None else args.dark_s
    light_s = itc["light_s"] if args.light_s is None else args.light_s

    if args.test_connection:
        test_connection(cfg)
        return

    if not (args.wavelength and args.od):
        raise SystemExit("--wavelength 와 --od 는 필수입니다 "
                         "(연결 점검만 하려면 --test-connection)")

    led = MightexBioLED(cfg["mightex_port"], cfg["mightex_baud"], dry=args.dry_run)
    smu = Keithley4200(cfg["keithley_resource"], dry=args.dry_run,
                       backend=cfg.get("visa_backend", "@py"),
                       timeout_ms=cfg.get("visa_timeout_ms", 120000))
    try:
        run_it(cfg, smu, led, args.wavelength, args.od, bias, dark_s, light_s)
    finally:
        try:
            led.off(cfg["channels"][args.wavelength])
        except Exception:
            pass
        led.close()
        smu.close()


if __name__ == "__main__":
    main()