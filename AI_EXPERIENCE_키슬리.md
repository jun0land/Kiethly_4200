# 키슬리 원격제어 시스템

> **작성 기준일:** 2026-08-03
> 이 문서의 모든 수치는 실제 명령 실행 결과이며, 각 항목에 사용한 명령을 병기했다.
> 확인되지 않은 항목은 "확인 불가"로 남겼다.

> ### ⚠ 의뢰서 전제와 실제 구현이 다른 3가지 (먼저 읽을 것)
> 포트폴리오 의뢰서에는 "pyvisa TCPIP 리소스", "SCPI 명령 시퀀스"라는 전제가
> 있었으나 **저장소 실제 코드와 다르다.** 오히려 이 차이 자체가 이 프로젝트의
> 핵심 기술 서사이므로 그대로 기록한다.
>
> | 의뢰서 전제 | 실제 |
> |---|---|
> | pyvisa TCPIP 소켓 | **전면 폐기됨.** 최종은 벤더 DLL(`KXCIclient.dll`) + `ctypes` |
> | SCPI 명령 | **SCPI 아님.** KXCI 고유의 *페이지 기반* 명령어(DE/SS/SM/MD) |
> | 하위 도구 `photodetector-studio` | 실제 이름은 `photodetector-app` (패키지명 `pd_app`) |
>
> 또한 이 시스템은 Keithley 단독이 아니라 **Keithley 4200-SCS + Mightex BioLED
> 광원**을 함께 제어한다. 광원 쪽은 통신 방식이 이더넷이 아니라 **USB HID**다.

---

- **기간 / 상태:**
  - 작업 기간: **2026-07-29 ~ 2026-08-03** (실작업 3일: 07-29, 07-30, 08-03)
    - 근거: `python`으로 세션 로그 `timestamp` 집계 →
      `2026-07-29: 674건 / 2026-07-30: 387건 / 2026-08-03: 40건`
  - 상태: **파일럿(베타).** 프로그램 내 사용법 탭 첫 줄에 스스로 명시
    (`grep -n "파일럿" pd_iv_station.py`)
  - 하드웨어 검증 현황이 기능별로 다름 — 아래 "정량 결과" 참조

- **문제 정의 (구형 장비 수동 조작의 병목):**
  - 기존 워크플로: Keithley KITE에서 **손으로** I-V 측정 → Origin으로 수동 작도
  - 구형 장비(KTEI V9.1)의 구조적 제약: **실행(Run)과 Append만 가능**하고
    시트 이름 지정·중간 시트 삭제·순서 변경이 **장비 소프트웨어 수준에서 불가능**
  - 연구 프로토콜상 한 샘플당 트레이스가 여러 개 누적됨
    (Dark 음/양 2회 + 파장별 광전류 n회) → 수동 반복과 파일 정리 부담이 큼
  - 측정 결과를 하위 분석 앱(`pd_app`)이 읽는 포맷으로 **매번 수동 변환**해야 했음

- **사용한 AI 도구·모델·인터페이스:**
  - **Claude Code** (VSCode 확장 인터페이스에서 실행)
    - 근거: 세션 로그 경로 `~/.claude/projects/c--Users-mintj-Kiethly-4200/`
  - 모델: **claude-sonnet-5 (611회)** / **claude-opus-5 (18회)**
    - 근거: 세션 `.jsonl`의 assistant 레코드 `message.model` 집계
  - 사용자 설정: `~/.claude/settings.json` → `{"model": "claude-sonnet-5", "autoUpdatesChannel": "latest", "theme": "dark"}`
  - **커스텀 설정 자산은 없음:** `CLAUDE.md`, `.claude/` 프로젝트 디렉터리,
    커스텀 슬래시 커맨드, 스킬, 훅, MCP 서버 **모두 없음**
    - 근거: `ls -la CLAUDE.md .claude` → `No such file or directory`,
      `~/.claude/plugins/`에 `known_marketplaces.json`과 빈 `marketplaces/`만 존재
    - 즉 **기본 상태의 Claude Code만으로 진행**했고, 프로젝트 지식은 코드 주석과
      `HANDOFF_keithley_automation.md`(788줄) 문서에 축적하는 방식을 택함

---

### 동기

페로브스카이트/실리콘 듀얼모드 광검출기 특성 평가에서 **① 측정 자동화**와
**② 기존 분석 앱이 바로 읽는 포맷으로 자동 저장** 두 가지가 목표였다.

단순 스크립트가 아니라 **KITE와 같은 스타일(SMU 구성 / 측정 설정 / 실행 분리)의
GUI 플랫폼** 형태를 요구사항으로 명시했다 — 명령줄 도구는 실험자가 쓰기 어렵다는
판단. (근거: `HANDOFF_keithley_automation.md` 1절 "최종 지향점")

연구실 측정 프로토콜을 코드가 강제하도록 설계했다:

| 항목 | 규칙 |
|---|---|
| Dark | `0 → −1 V`, `0 → +1 V` **두 번 나눠서** |
| 광전류 | `−1 → +1 V` **한 번에** 스윕 |
| Range I | 광전류가 컴플라이언스에 안 걸리는 선에서 **가장 작고 동일한 값**으로 통일 (노이즈 바닥을 맞춰야 트레이스 간 비교 성립) |
| 파장 변경 | 수동 (사람이 LED 교체 후 프로그램에서 선택) |
| 광 세기 | 파장별 **%로** 사전 등록 |

---

### 워크플로우

AI 도구 사용 패턴을 세션 로그에서 정량화했다
(근거: `.jsonl`의 `tool_use` 블록 집계):

| 도구 | 호출 수 |
|---|---|
| Bash | 117 |
| Edit | 88 |
| Read | 81 |
| TodoWrite | 30 |
| Write | 8 |
| PowerShell | 6 |
| Glob | 4 |
| Grep | 2 |
| AskUserQuestion | 2 |
| ToolSearch | 1 |
| **합계** | **329** |

- 총 레코드 1,291줄 / 4.2 MB, assistant 629건, 실제 사용자 텍스트 입력 **약 22턴**
  - 근거: `wc -l`, `ls -la`, `.jsonl` 파싱
- **특징: 사용자 입력 22턴 대비 도구 호출 329회** — 한 번의 지시가 다수의
  탐색·편집·검증 사이클로 전개되는 패턴
- `Bash`가 최다 호출인 이유는 **검증 중심 진행** 때문:
  문법 검사(`py_compile`), dry-run 스모크 테스트, 그리고 **하위 분석 앱의 실제
  파서를 import해 직접 실행**하는 방식으로 호환성을 확인함(추측 배제)
- `AskUserQuestion` 2회는 사람이 결정해야 할 지점에서만 사용
  (동기화 방식 선택, UI 문구 네이밍)

---

### 통신 방식 선정 (검토와 기각 사유)

#### Keithley 4200-SCS 측
저장소에 **"실패한 접근 — 재시도 금지"** 절이 명시적으로 남아 있다
(`HANDOFF_keithley_automation.md` 3절, 원문 인용):

| 시도 | 결과 |
|---|---|
| `pyvisa` + `TCPIP::192.168.0.200::8888::SOCKET` | 포트 8888은 **틀린 번호** (참고자료 오류). 실제는 **2105** |
| `pyvisa` + `TCPIP::...::2105::SOCKET` | 소켓은 열리나 **모든 명령이 무응답** |
| 종단문자 `\n` / `\r` / `\r\n` / 없음 × 명령 `*IDN?`/`ID`/`US`/`VE`/`UO`/`DE` (18조합) | **전부 타임아웃** |
| 연결 직후 배너 수신 대기 (raw socket) | 장비가 먼저 말을 걸지 않음 |
| STX(0x02)/ETX(0x03) 프레이밍 5종 | **전부 무응답** |

> **근본 원인:** GPIB의 EOI는 인쇄 가능한 문자가 아니라 **버스의 물리적 하드웨어
> 신호**다. 따라서 raw socket에서 문자로 흉내낼 수 없다. Keithley가 이 변환을
> 대신 처리해주는 전용 클라이언트 DLL을 제공한다.
>
> **결론: `pyvisa` 경로는 완전히 폐기. 반드시 `KXCIclient.dll` + `ctypes`를 쓸 것.**

이 발견이 프로젝트의 분기점이다. **"종단문자를 더 시도한다"는 방향 자체가
틀렸음**을 규명한 것 — 24가지 조합(18 + 배너 + STX/ETX 5)을 소진한 뒤
문제를 프로토콜 계층에서 재정의했다.

관련 흔적:
- `cli_tools/kxci_dll_test.py:6` — *"매뉴얼 확인 결과, GPIB의 EOI는 물리적 하드웨어 신호라..."*
- `cli_tools/pd_iv.py:5` — *"2026-07-29 개정: pyvisa raw socket 방식은 KXCI가 응답하지 않아 전면 폐기."*
- `cli_tools/pd_it.py:22` — 폐기된 리소스 문자열이 구버전 파일에 그대로 남아 있음:
  `PyVISA Raw Socket: TCPIP::192.168.0.200::2105::SOCKET`
- `it_config.json:2` — `"keithley_resource": "TCPIP::192.168.0.200::2105::SOCKET"` (레거시 잔존 키)

**RS-232:** Keithley 측에서 RS-232를 검토한 코드·주석은 **없음**(확인 불가).
단, `cli_tools/pd_it.py:6`에 *"Keithley 통신 케이블(GPIB-USB) 확보 전까지는
--dry-run으로..."* 라는 기록이 있어 **GPIB-USB 하드웨어 경로도 대안으로
고려되었으나 케이블 미확보로 이더넷+DLL 경로를 택한 정황**이 확인된다.

#### Mightex BioLED 광원 측 (2차 기각 사례)
초기 구현은 **pyserial 기반 ASCII 시리얼 통신**(`MODE`/`NORMAL`/`CURRENT`)을
가정했으나 **전부 추측이었고 틀렸다.** 실제 장치(BLS-SA02-U)의 공식 SDK 매뉴얼을
확인한 결과:

> *"the BIOLED Control driver is designed as a HID device"*
> — Mightex bioLED Controller SDK Manual v1.2.1

즉 **USB HID 장치**여서 장치관리자에 COM 포트로 뜰 수 없고 pyserial로 열 방법이
원천적으로 없었다. 사용자가 "COM 포트가 안 보인다"고 반복 보고한 현상의 원인이
여기였다. (근거: `pd_iv_station.py:346-354` 주석, `HANDOFF` 0-5절)

→ `Mightex_BLSDriver_SDK.dll`(cdecl, 32비트) + `ctypes`로 **전면 재작성**.
Keithley와 동일한 패턴으로 수렴시켰다.

#### 최종 통신 스택

| 항목 | Keithley 4200-SCS | Mightex BioLED |
|---|---|---|
| 물리 계층 | PC(Wi-Fi) → ipTIME Extender-A3MU → Cat.6 → K4200 Ethernet | USB |
| 논리 계층 | **벤더 DLL `KXCIclient.dll`** (`ctypes.CDLL`, cdecl) | **벤더 DLL `Mightex_BLSDriver_SDK.dll`** (`ctypes.CDLL`, cdecl) |
| 주소 | `IP = b"192.168.0.200"`, `PORT = 2105` | 없음 (HID 열거, `OpenDevice(0)`) |
| 버퍼 | `BUF_SIZE = 4096` | — |
| 종단문자 | **해당 없음** — DLL이 GPIB EOI를 대신 처리 | 해당 없음 |
| 타임아웃 | `wait_done(poll_s=0.2, max_wait_s=120)` (상태바이트 폴링) | — |
| 명령 체계 | **KXCI 페이지 명령** (SCPI 아님) | SDK 함수 호출 |
| 비트수 제약 | **32비트 파이썬 전용** (DLL이 x86) | 동일 |

- 근거: `grep -n "^IP\|^PORT\|^DLL_NAME\|^BUF_SIZE" pd_iv_station.py` →
  `33:IP = b"192.168.0.200"` / `34:PORT = 2105` / `35:DLL_NAME = "KXCIclient.dll"` / `36:BUF_SIZE = 4096`

---

### 핵심 구현

#### 1) 통신 계층 — `class Keithley4200` (`pd_iv_station.py:141~`)

`ctypes`로 4개 export 함수를 바인딩. **`WinDLL`이 아니라 `CDLL`** (cdecl 규약)인
점이 중요 — 접미사 없는 stdcall 버전은 VB용이라 사용하지 않음.

```python
dll = ctypes.CDLL(dll_path)
dll.OpenKXCIConnection_C.argtypes = [c_char_p, c_int, POINTER(c_int)]
dll.SendKXCICommand_C.argtypes    = [c_char_p, c_char_p, POINTER(c_int)]
dll.GetKXCISpollByte_C.argtypes   = [POINTER(c_ushort), POINTER(c_int)]
dll.CloseKXCIConnection_C.argtypes = []
```

**성공 판정의 반직관성:** `OpenKXCIConnection_C`의 반환값 의미가 매뉴얼에
없어, 실측으로 *성공 시 `ret=1`* 임을 확인하고 **`socket_err == 0`을 판정
기준**으로 삼았다(0이 성공이 아님). 코드에 그대로 반영:
```python
if sock_err.value != 0:
    raise RuntimeError(f"KXCI 연결 실패 (socket_err={sock_err.value})")
```

#### 2) 측정 시퀀스 — 페이지 기반 상태 머신

KXCI는 SCPI와 달리 **페이지를 먼저 전환한 뒤 그 페이지의 명령을 보내는** 구조다.
`_do_sweep()`(`pd_iv_station.py:1555`)의 실제 순서:

```
DE                              ← 채널 정의 페이지
  CH1,'VK','IK',3,3             ← SMU1 = Cathode, Common 모드
  CH2,'VA','IA',1,1             ← SMU2 = Anode, 전압원 + VAR1 스윕
  CH3..CH8                      ← 미사용 채널 명시적 OFF
IT 1 / RS 6                     ← 적분시간 / 분해능(전역)
SS                              ← 소스 설정 페이지
  VR1,start,stop,step,compliance ← 선형 스윕 + 컴플라이언스
SM                              ← 측정 설정 페이지
  DM2                           ← 리스트 데이터 모드(조회 가능하게)
  RI2,<range>,<compliance>      ← Range I 고정 (실패 시 RG로 폴백)
MD                              ← 측정 제어 페이지
  ME1                           ← 트리거
[상태바이트 B0(Data Ready) 폴링]
DO 'VA' / DO 'IA'               ← 데이터 조회
```

**채널 정의를 매 측정마다 재전송**한다 — 장비 상태를 매번 확정해 이전 측정의
잔여 설정이 새는 것을 막는 설계(`_prep_and_apply`, 주석에 의도 명시).

#### 3) 응답 파싱과 단위/상태 처리

장비 응답은 `N-1.00000E+00,N 0.00000E+00,...` 형태로 **각 값 앞에 1글자 상태
코드**가 붙는다. 초기에는 숫자만 뽑았으나(`_NUM`), 이후 상태 코드까지 보존하도록
확장했다:

```python
_TOK_STATUS = re.compile(r"([A-Za-z])\s*([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)")
```

- 단위: 장비가 SI 지수 표기(`E-06`)로 반환 → `float`로 그대로 수용, 변환 없음
- **문자열 앞부분을 자르는 방식 대신 정규식**을 쓴 이유가 주석에 명시:
  헤더 형태가 바뀌면 깨지기 때문
- 상태 코드 `'N'`(Normal) 외의 값은 **컴플라이언스/오버플로 의심**으로 간주해
  측정 직후 개수를 로그로 경고하고, CSV/엑셀에 `Status` 열로 영구 보존

#### 4) 자료구조 — 측정 순서 변경·삭제 (장비 제약 우회)

`Session.traces`는 **딕셔너리의 리스트**이며, 리스트 인덱스 자체가 측정 순서다:

```python
self.traces = []  # [{index, label, range_i_A, range_i_str, data, csv_path}]
```

| 연산 | 구현 | 핵심 |
|---|---|---|
| 삭제 | `remove_at(idx)` | `pop(idx)` → CSV 파일도 삭제 → `_renumber()` |
| 순서 변경 | `move(idx, delta)` | 튜플 스왑 → `_renumber()` |
| 라벨 수정 | `update_label(idx, new)` | 브래킷 코드가 자동 재계산됨 |

`_renumber()`가 모든 변경 후 `index`를 1부터 다시 매겨 **리스트 위치와 표시
번호의 정합성을 보장**한다. 모든 변경은 즉시 `_save_meta()`로 `session.json`에 반영.

> 설계 근거(코드 주석 원문): *"실제 4200(KITE)은 실행/Append만 가능해 중간
> 트레이스를 못 지우지만, 여기서는 엑셀을 우리가 직접 생성하므로 순서·구성에
> 제약이 없다."*
>
> → **장비의 구조적 제약을 소프트웨어 계층에서 무력화한 것이 이 프로젝트의
> 실질적 가치 중 하나.**

#### 5) 광원–측정 동기화

**I-V (단일 세기):** 순서 보장을 `try/finally`로 강제
```python
self.led.set_percent(ch, pct)          # 점등
try:
    data = self._do_sweep(...)          # 스윕
finally:
    self.led.off(ch)                    # 예외가 나도 반드시 소등
```
→ **측정 실패 시에도 광원이 켜진 채 방치되지 않음** (소자 보호)

**I-T (다중 세기 시퀀스):** `dark → P1 → dark → … → Pn → dark(끝)` 타임라인을
프리셋 개수 n에서 자동 생성(dark n+1회, light n회). **누적 목표시각 기반
스케줄링**으로 구간별 드리프트를 방지:
```python
elapsed_target += dur
edge = t0 + elapsed_target      # 절대 시각 기준 (dur 누적 오차 방지)
while time.time() < edge:
    time.sleep(0.01)
```

**안정화 대기 시간:**
- I-T 프리스캔에서 **`time.sleep(1.0)`** (LED 점등 후 전류 안정화 대기) — 유일한 명시적 settle
- **I-V 스윕에는 별도 안정화 대기가 없음** — 점등 직후 바로 스윕 시작
  (근거: `grep -n "time.sleep" pd_iv_station.py` → 253/1743/1782 세 곳뿐)
  → 아래 "실패 기록"에 개선 후보로 기록

#### 6) 소자 보호

- 컴플라이언스를 **모든 소스 명령의 필수 인자**로 전달
  (`VR`/`IR`/`VC`/`IC`/`RI` 전부) — 기본값 `1e-3 A`
- Range I 고정으로 과전류 구간 진입 억제
- I-T는 최대 세기에서 **프리스캔으로 실측 |I|max를 측정**한 뒤
  `pick_fixed_range(exp, margin=3.0)`으로 3배 여유를 두고 레인지 결정
- 미사용 SMU 채널은 `CH<n>`만 전송해 **명시적으로 OFF**

#### 7) 저장 경로·파일명 규칙과 하위 분석 앱 연동

**측정 중 (유실 방지):** 측정이 끝날 때마다 즉시 디스크에 기록
```
sessions/<샘플명>_<YYMMDD_HHMMSS>/trace_NN_<라벨>.csv   ← 개별 트레이스
sessions/<샘플명>_<YYMMDD_HHMMSS>/session.json          ← 메타데이터
```
→ 앱이 죽어도 개별 트레이스는 남는다. 내보내기는 이를 합치는 작업일 뿐.

**최종 산출물 (분석 앱 입력):**
```
(<샘플명>)[<브래킷코드>].xlsx
```

하위 분석 앱 `pd_app`의 파서(`photodetector-app/pd_app/parsing.py`)와의 계약을
**실제 코드를 읽어 역설계**해 맞췄다:

| 계약 항목 | 분석 앱 요구 | 본 시스템 구현 |
|---|---|---|
| 파일명 샘플명 | `re.search(r"\(([^)]*)\)", ...)` | `({safe_filename(name)})` |
| 파일명 트레이스 코드 | `re.search(r"\[([^\]]+)\]", ...)`, **길이 == 데이터시트 수** | `bracket_code()`가 트레이스 수만큼 생성 |
| 시트 이름 | `Data`, `Append1`, `Append2`… | 동일 |
| 데이터 컬럼 | `AnodeV`, `AnodeI` (이름으로 선택) | `AnodeV`, `AnodeI`, `Status` |
| Settings 블록 | `Initial Run` / `Append N` 하위 `Range I` | 동일 + `Label` 추가 |
| 심볼 맵 | `d`=Dark, `8`=940nm … `1`=365nm | `LABEL_TO_SYMBOL` 동일 값 |

- 근거: `grep -n "SYMBOL_MAP" -A 12 photodetector-app/pd_app/constants.py`,
  `parsing.py:226-242`
- **길이 불일치 시 분석 앱이 경고를 내고 일반 라벨로 폴백**하므로, 트레이스를
  삭제·재정렬하면 브래킷 코드도 반드시 함께 재계산되어야 한다 →
  `bracket_code()`를 저장 시점에 항상 재생성하는 설계로 대응

---

### 설계 트레이드오프와 실패 기록

#### 트레이드오프

| 결정 | 트레이드오프 |
|---|---|
| **벤더 DLL + ctypes** (pyvisa 대신) | 이식성 상실(32비트 Windows 고정, DLL 동봉 필수) ↔ **유일하게 동작하는 경로** |
| **32비트 파이썬 강제** | 최신 패키지 생태계 제약 ↔ DLL이 x86이라 선택지 없음. `_check_bitness()`로 시작 시 검사 후 명확히 안내 |
| **pandas/numpy 미사용** | 데이터 처리 코드가 길어짐 ↔ 32비트 휠 부재 위험 회피. 실제로 `openpyxl` 단 하나만 외부 의존 |
| **tkinter (Streamlit 배제)** | UI 표현력 제한 ↔ Streamlit은 상호작용마다 스크립트를 재실행해 **측정 중 상태가 날아감** (사용자가 명시적으로 배제 요청) |
| **그래프 자체 구현** (matplotlib 미사용) | 기능 단순 ↔ 의존성 0, 32비트 호환 확실 |
| **PC측 트레이스 누적** (장비 버퍼 대신) | 장비 네이티브 기능 미활용 ↔ 삭제·재정렬 자유 확보 |

#### 실패 기록 (모두 문서에 남김)

1. **pyvisa 24조합 전수 실패** → 프로토콜 계층 오인. 위 "통신 방식 선정" 참조.
2. **BioLED = 시리얼 장치라는 오판** → 실제로는 USB HID.
   초기 코드의 ASCII 명령은 전부 추측이었고, 원본 파일 주석에 스스로
   *"⚠️ 모델마다 다를 수 있으니 확인할 것"* 이라 적혀 있었음에도 검증이
   늦어져 사용자가 존재하지 않는 COM 포트를 반복 탐색하게 만듦.
3. **채널 이름 6글자 초과 → "0점 수신"**
   매뉴얼 표기 `'BBBBBB'`가 정확히 6글자인데 기본값으로 `'CathodeV'`(8글자)를
   넣어 `CH1` 정의가 **조용히 Syntax Error**. 더 큰 문제는 실패했는데도
   *"채널 정의(DE) 전송 완료"* 로그가 찍혔다는 점 — **실패가 성공처럼 보였다.**
   → 대응: 모든 설정 명령을 `_w_checked()`(전송 직후 상태바이트 확인)로 교체 +
   이름 길이 자동 절단 + `DO` 원본 응답 상시 로깅.
4. **Dry-run이 재시작마다 켜짐** → 사용자가 "실측 모드"로 측정했다고 믿었으나
   실제로는 명령이 나가지 않던 상태. 로그 형태로 역추적해 발견.
   → `station_config.json`에 상태 영속화 + **상단에 색상 배너**(🔶/🔴) 추가.
5. **`export_excel()` 변수 섀도잉 버그** — 시트 이름 변수와 샘플명 변수가 둘 다
   `name`이라 파일명이 `(Append1)[...]`로 잘못 생성됨. **스모크 테스트 중 발견**해
   `display_name`/`sheet_name`으로 분리.
6. **전류 0 값이 그래프에서 사라짐** — `i != 0` 필터 때문에 "측정은 됐지만 값이 0"인
   정상 상황이 "데이터 없음"으로 표시됨. → 0을 축 하단에 그리도록 수정.
7. **`MSVCR120.dll` 미설치로 타 PC에서 실행 실패**
   `KXCIclient.dll`의 의존성을 PE 헤더에서 직접 파싱해 규명
   (`WS2_32.dll`, `KERNEL32.dll`, **`MSVCR120.dll`**) → VC++ 2013 재배포
   패키지(x86) 설치 필요를 특정.

#### 알려진 미해결 항목 (문서 9절)

- BioLED HID 재작성분 **실기 미검증** (최우선 과제)
- `IT`/`RS` 명령의 유효 페이지 컨텍스트가 매뉴얼에 불명확 → 현재는 MD 진입 직전 전송
- 상태 코드 `'N'` 외 문자들의 정확한 의미 미확정
- **종료 시 SMU 출력을 명시적으로 OFF(스탠바이)하는 코드 없음**
  (근거: `grep -n '"ST\|standby' pd_iv_station.py` → 결과 없음).
  `disconnect_all()`은 DLL 연결만 닫음 → **개선 필요 지점**
- 재시도(retry) 로직 없음 — 타임아웃 시 경고 로그만 남기고 반환

---

### 정량 결과

#### 코드 규모 (`git ls-files` + `wc -l`)

| 파일 | 줄 수 | 역할 |
|---|---|---|
| `pd_iv_station.py` | **1,833** | 메인 GUI (5탭), 통신·세션·내보내기 전부 |
| `HANDOFF_keithley_automation.md` | **788** | 작업 인계 문서 (실패 기록 포함) |
| `cli_tools/pd_it.py` | 409 | 레거시 I-T (pyvisa, 참고용) |
| `cli_tools/bioled_controller.py` | 361 | BioLED 단독 GUI |
| `cli_tools/pd_iv.py` | 253 | CLI I-V 스윕 |
| `cli_tools/bls_dll_test.py` | 118 | BioLED HID 진단 |
| `cli_tools/kxci_dll_test.py` | 102 | Keithley DLL 진단 |
| `it_config.json` | 60 | I-T 전역 설정 |
| **코드+문서 합계** | **약 3,924줄** | (DLL 바이너리 3종 제외) |

#### Git 이력 — **주의: 실제 작업량을 심하게 과소평가함**

| 항목 | 값 | 명령 |
|---|---|---|
| 총 커밋 수 | **2** | `git rev-list --all --count` |
| 최초 커밋 | 2026-07-30 15:46:07 +0900 | `git log --reverse --format=... --date=iso` |
| 최종 커밋 | 2026-07-30 15:47:03 +0900 | `git log --format=... --date=iso` |
| 월별 분포 | 2026-07: 2건 | `git log --format="%ad" --date=format:"%Y-%m" \| sort \| uniq -c` |
| 총 추가 라인 | **3,940** / 삭제 0 | `git log --numstat --format="" \| awk ...` |

> **해석 주의:** 저장소를 **개발이 거의 끝난 시점(3일차)에 초기화**했기 때문에
> 커밋 2건·삭제 0줄로 나타난다. 실제 개발 과정의 반복·폐기는 git이 아니라
> **세션 로그(1,291 레코드)와 `HANDOFF` 문서의 실패 기록**에 남아 있다.
> 이 문서에서 개발 타임라인의 근거로 세션 로그를 우선한 이유다.

#### 하드웨어 검증 현황 (기능별로 다름 — 정직하게 구분)

| 항목 | 상태 | 근거 |
|---|---|---|
| Keithley 이더넷+DLL 연결 | ✅ **검증됨** | `ret=1, socket_err=0`, ID 응답 `KI4200 V9.1-SP1` |
| Dark 스윕 (0→−1 V, 0.05 V step) | ✅ **21점 수신** | 실기 로그 |
| 광전류 스윕 (−1→+1 V) | ✅ **41점 수신** | 실기 로그, `(1-(-1))/0.05+1 = 41` 이론값과 정확히 일치 |
| `RI` → `RG` 자동 폴백 | ✅ **실기 확인** | 이 장비는 `RI`에서 Syntax Error → `RG`로 폴백해야 통과 |
| 엑셀 → `pd_app` 호환성 | ✅ **실제 파서로 3회 검증, `warnings: []`** | `parse_file()` 직접 import 실행 |
| BioLED HID 제어 | ❌ **실기 미검증** | 재작성분 dry-run만 통과 |
| I-T 탭 | ❌ **실기 미검증** | 로직만 dry-run 확인 |

#### AI 협업 정량

| 지표 | 값 |
|---|---|
| 세션 기간 | 2026-07-29 ~ 2026-08-03 (실작업 3일) |
| 세션 로그 크기 | 4.2 MB / 1,291 레코드 |
| assistant 응답 | 629건 (sonnet-5 611 / opus-5 18) |
| 사용자 텍스트 입력 | 약 22턴 |
| 도구 호출 | 329회 |
| **입력 1턴당 도구 호출** | **약 15회** |

---

### 객관적 증거

**증거 수집에 사용한 실제 명령 (재현 가능):**

```bash
# 1) Git 이력
git log --oneline --all
git rev-list --all --count
git log --all --reverse --format="%h %ad %an %s" --date=iso | head -1
git log --all --format="%ad" --date=format:"%Y-%m" | sort | uniq -c
git log --all --numstat --format="" | awk '{add+=$1; del+=$2} END {print add, del}'

# 2) 파일 규모
git ls-files | while read f; do printf "%6d %s\n" "$(wc -l < "$f")" "$f"; done | sort -rn

# 3) 의존성 (requirements 파일 부재 확인 후 import 전수 조사)
ls requirements*.txt setup.py pyproject.toml Pipfile     # → No such file
grep -rhn "^import \|^from " --include="*.py" . | sort -u
grep -rn "import pyvisa\|import serial\|from openpyxl" --include="*.py" .

# 4) Claude Code 자산
ls -la CLAUDE.md .claude                                  # → 없음
ls -la ~/.claude/plugins ~/.claude/projects
cat ~/.claude/settings.json

# 5) 세션 로그 분석 (모델/도구/일자 집계)
wc -l ~/.claude/projects/c--Users-mintj-Kiethly-4200/*.jsonl
python  # .jsonl 파싱 → type/model/tool_use/timestamp 집계

# 6) 통신 계층
grep -n "^IP\|^PORT\|^DLL_NAME\|^BUF_SIZE" pd_iv_station.py
grep -n '_w(\|_w_checked(' pd_iv_station.py
grep -n "def wait_done\|def _w_checked\|def set_range_fixed" -A 15 pd_iv_station.py

# 7) 기각된 대안 흔적
grep -rn "GPIB\|RS-232\|pyvisa\|SOCKET\|EOI\|COM 포트" --include="*.py" --include="*.md" .

# 8) 자료구조 / 동기화
grep -n "def remove_at\|def move\|def _renumber\|def bracket_code" -A 14 pd_iv_station.py
grep -n "def _measure_photo" -A 42 pd_iv_station.py
grep -n "time.sleep" pd_iv_station.py

# 9) 하위 분석 앱 계약
grep -n "SYMBOL_MAP" -A 12 ../photodetector-app/pd_app/constants.py
grep -n "m_sample\|bracket = " -B2 -A4 ../photodetector-app/pd_app/parsing.py

# 10) DLL 의존성 (PE 헤더 직접 파싱)
python pe_imports.py KXCIclient.dll   # → WS2_32.dll, MSVCR120.dll, KERNEL32.dll
```

**저장소:** https://github.com/jun0land/Kiethly_4200.git (main)

**핵심 산출물:**
- `pd_iv_station.py` — 5탭 GUI (사용법 / SMU 구성 / 측정 설정 / 측정 실행 / I-T)
- `HANDOFF_keithley_automation.md` — 788줄 인계 문서.
  "실패한 접근 — 재시도 금지" 절을 명시적으로 유지해 **동일 실수 반복을 차단**
- `cli_tools/kxci_dll_test.py`, `cli_tools/bls_dll_test.py` — 계층별 진단 스크립트
  (문제 발생 시 최하위 계층부터 좁히는 절차를 문서 10절에 규정)

**확인 불가 항목:**
- 자동화 이전 수동 측정 소요 시간 (측정된 기록 없음 → 시간 절감률 산출 불가)
- Keithley 측 RS-232 검토 흔적 (코드·주석에 없음)
- 프로젝트 착수 이전의 사전 조사 기간
