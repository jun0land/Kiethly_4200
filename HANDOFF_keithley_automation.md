# Keithley 4200-SCS 측정 자동화 — 작업 인계 문서

> **대상:** VSCode의 Claude Code
> **최종 갱신:** 2026-08-07 — **I-V 측정이 실기에서 정상 동작하는 것까지 확인됨**
> **작업 폴더:** `C:\Users\mintj\Kiethly_4200\` (GitHub: `jun0land/Kiethly_4200`, Public)
>
> 이 문서만 읽고 바로 이어서 작업할 수 있도록, **이미 검증된 사실 / 실패해서
> 재시도하면 안 되는 것 / 남은 작업**을 모두 담았다.
> ⚠ 특히 "3. 실패한 접근"은 반드시 읽을 것. 여기 적힌 방법들은 이미 수 시간을
> 들여 배제했으므로 다시 시도하면 시간 낭비다.

### 처음 읽는다면 이 순서로

1. **0-4절 ⭐** — 측정이 되게 만든 결정적 수정 2가지(`LI` 누락, 컴플라이언스>Range).
   측정 결과가 이상하면 여기부터.
2. **2절** — 32비트 파이썬 제약 (모든 것의 전제)
3. **3절** — 실패한 접근(재시도 금지)
4. **10절** — 문제 생겼을 때 좁혀가는 순서 + 로그 읽는 법
5. 나머지 0-x절은 **역순 개발 일지**다(위가 최신). 필요할 때만 찾아보면 된다.

> 📌 0-x절 중 서로 모순돼 보이는 서술이 있으면 **번호가 큰 쪽(=아래쪽,
> 오래된 것)이 아니라 0-4절 같은 '정정' 항목이 최종 결론**이다. 잘못된 중간
> 결론도 판단 과정을 남기려고 지우지 않고 ⚠ 표시와 함께 두었다.

## 0-1. 실측 모드에서만 연결 실패 — `SystemExit`이 `except Exception`을 빠져나간 버그

증상: **Dry-run에서는 "연결됨"이 뜨는데 실측 모드에서는 연결 버튼이 먹통.**
오류창조차 안 떴다.

원인 두 가지가 겹쳐 있었다:

1. **Dry-run은 애초에 아무것도 검증하지 않는다.** `Keithley4200.__init__`이
   `if dry: return`으로 **DLL을 건드리기 전에 반환**한다. 그래서 dry-run의
   "연결 성공"은 성공이 아니라 *아무 일도 안 한 것*이다 — 실측 모드와 비교
   대조군이 될 수 없다.
2. **`SystemExit`은 `Exception`이 아니라 `BaseException` 직속이다.**
   `_check_bitness()`와 DLL 부재 검사가 `SystemExit`을 던졌는데, GUI의
   `except Exception as e: messagebox.showerror(...)` 는 이걸 **못 잡는다.**
   결과적으로 예외가 tkinter 콜백 밖으로 빠져나가 stderr로만 출력되고
   (콘솔 없이 실행하면 보이지도 않음), 사용자에겐 **버튼이 아무 반응 없는
   것처럼** 보였다.

   ```
   >>> issubclass(SystemExit, Exception)
   False
   >>> SystemExit.__mro__
   (SystemExit, BaseException, object)
   ```

**수정:**
- `_check_bitness()`와 DLL 관련 실패를 전부 **`RuntimeError`**(=`Exception` 하위)로 변경
- `connect_smu()` / `connect_led()`를 **`except BaseException`**으로 방어하고,
  실패 시 **로그창에도 반드시 남기도록** 변경(`✘ ... 실패: {타입}: {메시지}`)
- 연결 시도 시작도 로그에 남김 → 버튼이 눌렸는지 자체를 확인 가능
- 검증: 64비트 파이썬에서 실측 연결 시도 시 예전엔 무반응이었으나, 이제
  로그에 `✘ Keithley 연결 실패: RuntimeError: ...32비트 전용...`이 뜨는 것 확인

**교훈:** GUI 콜백 안에서는 `except Exception`만으로 부족하다. CLI 스크립트
(`cli_tools/*.py`)의 `SystemExit`은 터미널에 메시지를 찍고 정상 종료하는
올바른 동작이므로 **그대로 두었다** — 문제는 GUI 컨텍스트에서만 발생.

## 0-2. DLL 경로 자동 탐색 — 컴퓨터를 바꿔도 코드 수정 불필요

원래도 `os.path.dirname(os.path.abspath(__file__))` 기준이라 **폴더를 통째로
옮겨도 코드를 고칠 필요는 없었다**(스크립트 위치를 따라감). 다만 못 찾았을 때
메시지가 불친절해서 "경로 문제인가?" 하고 헤매기 쉬웠다.

`find_dll(name)` / `load_cdecl_dll(name)` 헬퍼를 추가해:
- 스크립트 폴더 → `cli_tools/` → 상위 폴더 → CWD → `CWD/cli_tools` 순으로 자동 탐색
- 못 찾으면 **뒤진 경로를 전부 나열**해서 안내
- 파일은 있는데 로드가 실패하면 → **의존 DLL 누락**임을 명시하고
  VC++ 2013 재배포 패키지(x86) 링크를 안내

  ⚠ 이게 다른 노트북에서 겪은 그 오류다. `KXCIclient.dll`은
  **`MSVCR120.dll`**(VC++ 2013 x86)을 필요로 하는데 Windows 기본에는 없다.
  이때 파이썬 메시지가 `Could not find module ... (or one of its
  dependencies)` 라서 **경로 문제처럼 보이지만 경로가 맞아도 나는 오류**다.
  (근거: PE 헤더 직접 파싱 → `WS2_32.dll`, `MSVCR120.dll`, `KERNEL32.dll`)

  BioLED DLL 2종은 시스템 기본 DLL만 쓰므로 이 문제가 없다.

  **⚠ 2026-09-04, 같은 오류가 이 개발 PC에서 또 났다.** 원인은 코드가 아니라
  **설치 절차**였다 — 이 의존성이 여기 문서에만 적혀 있고 `최초설치.bat`은
  설치하지 않아서, 사람이 기억해서 직접 깔아야만 동작하는 상태였다.
  (실측: 레지스트리에 VC++ 재배포 패키지 0개, `SysWOW64\msvcr120.dll` 없음)
  이제 `최초설치.bat`이 직접 설치하고 로드까지 검증한다 — 0-6절 참고.

**결론: 다운로드 폴더 같은 곳으로 경로를 고정할 필요 없다.** `git clone` 하면
DLL이 같이 딸려오고, 코드가 알아서 자기 옆에서 찾는다.

## 0-3. Git으로 두 노트북 동기화하기

측정에 실제로 쓸 노트북과 개발 중인 이 PC를 코드 기준으로 맞추기 위해
git 저장소로 초기화했다(2026-07-30, 최초 커밋 `a3085d4`). `.gitignore`로
`sessions/`, `it_data/`, `cli_tools/iv_data/`(측정 데이터, 코드 아님)와
`__pycache__/`는 제외했다 — DLL(`KXCIclient.dll`, `Mightex_BLSDriver_SDK.dll`,
`HIDDLL.dll`)과 설정 JSON은 전부 포함(재현에 필요하고 민감정보 없음).

**원격 저장소는 아직 안 만들어짐 — 사용자가 GitHub에 비공개 저장소를 만들고
아래 명령으로 최초 푸시해야 한다** (로그인이 필요한 단계라 에이전트가
대신 못 함):

```powershell
# 1) github.com에서 새 저장소 생성 (Private 필수, README/gitignore/license 체크 해제)
#    예: kiethly-4200-automation

# 2) 이 폴더에서 원격 연결 + 푸시 (최초 1회, <URL>은 방금 만든 저장소 주소)
cd C:\Users\mintj\Kiethly_4200
git remote add origin <URL>
git branch -M main
git push -u origin main
```

**새 노트북에서 받아올 때** (Git for Windows만 있으면 됨, VSCode 불필요):
```powershell
git clone <URL>
```

**이후 업데이트가 있을 때마다** (이 PC에서 커밋+푸시된 뒤):
```powershell
cd Kiethly_4200
git pull
```

## 0-4. ⭐ 측정이 실제로 동작하게 된 결정적 수정 2가지 (반드시 읽을 것)

**이 두 가지를 고치고 나서야 측정이 제대로 됐다.** 둘 다 "명령은 나가는데
아무 오류도 안 나면서 결과만 틀린" 유형이라 찾기 어려웠다.

### ① `LI` 명령 누락 → 전류가 전부 정확히 0

증상: 전압은 201점 완벽하게 돌아오는데 **전류가 201개 전부
`0.00000E+00`**. 노이즈도 누설도 아닌 *정확한* 0이라는 게 단서였다
(개방회로라도 pA 단위 노이즈는 섞이므로 이렇게 깨끗한 0은 물리적으로 이상).

원인: 매뉴얼 5.4절의 `LI 'n1','n2'` = **리스트 모드에서 측정할 함수 지정**.
이걸 안 보내면 스윕 변수인 전압만 돌아오고 **전류는 측정 대상에 등록조차
되지 않는다.** 9절 미해결 항목 #4에 "현재 미사용이나 41점 정상 수신됨"이라고
적어두고 넘어갔던 바로 그 항목인데, **점 개수만 맞고 전류는 계속 0이었던 걸
놓친 것**이 화근이었다.

```
DE → CH1,'VK','IK',3,3 → CH2,'VA','IA',1,1
SS → VR1,-1,1,0.01,0.0001
SM → DM2 → LI 'VA','IA'      ← 이 줄이 없어서 전류가 안 잡혔다
BC → MD → ME1
```

**부수 효과:** 전류를 실제로 적분하게 되면서 측정 시간이 늘어난다. 그전에
"빨랐던" 것은 **전류를 아예 안 재고 있었기 때문**이므로, 예전 속도와
비교하면 안 된다.

### ② 컴플라이언스 > Range → `RI` 거부 (RI 미지원이 아니었음)

`RI`가 Syntax Error를 내서 한동안 "이 장비는 RI를 지원하지 않는다"고
결론냈었는데(0-7절), **틀렸다.** 당시 기본값이 **Range 10uA + 컴플라이언스
1mA**로, 컴플라이언스가 레인지보다 100배 컸다. 10uA까지만 측정하도록
고정해놓고 1mA까지 흘려도 된다고 한 셈이라 장비가 거부한 게 당연하다.

제약: **컴플라이언스 ≤ Range × 1.05**
근거는 실제 KITE 산출물(`example/15s_1 [dd876543].xls`):
- SMU1 컴플라이언스 `0.105 A` = 100 mA 레인지의 정확히 **105%**
- SMU2는 컴플라이언스 11 uA인데 Range가 10 uA가 아니라 **100 uA** — 11 uA가
  10 uA의 105%(=10.5 uA)를 넘어 담기지 않기 때문
- ⚠ 105%는 위 수치에서 **역산한 추론**이고 매뉴얼 원문 확인값은 아니다

→ 탭2에서 Range↔컴플라이언스를 **양방향 자동 보정**하도록 구현(KITE와 동일).
Range를 낮추면 초과 컴플라이언스가 자동으로 낮아지고, 컴플라이언스를 키우면
Range가 자동으로 올라간다. 고정 레인지(RI) 모드에서만 동작.

**⚠ 속도와도 직결된다.** `RG` 폴백은 레인지 고정이 아니라 오토레인징
하한만 정하는 것이라 **매 점마다 레인지를 탐색해 훨씬 느리다.** 측정이
비정상적으로 느리면 로그에 `RI2 Syntax Error — RG2로 폴백`이 뜨는지 먼저 볼 것.

### 그 밖에 이 시기에 고친 것
- `trigger()`에서 `ME1` 앞에 **`BC`**(데이터 버퍼·Data Ready 비트 클리어)를
  보낸다. 이전 측정의 Data Ready가 남아 있으면 `wait_done()`이 첫 폴링에서
  바로 완료로 판단해 **스윕이 끝나기도 전에 낡은 데이터를 읽는다.**
- 스윕마다 소요 시간 / 점당 시간 / 수신 점수 vs 예상 점수를 로그에 남기고,
  불일치하거나 전류가 전부 0이면 확인 순서를 안내한다.
- 기본값: 전압 스텝 **0.01 V**, Range I **100uA**, 컴플라이언스 **100uA**,
  적분시간 **Medium**(= KITE의 Speed "Normal", 실제 랩 측정 파일과 동일).

## 0-5. 배포·업데이트 운영 메모

- **저장소는 Public**이다. `git pull` 에 GitHub 로그인이 필요 없다.
  (한동안 "로그인 문제"로 오해했는데, 런처가 실패 시 *추측 목록*을 찍고 있었던
  탓이다. 지금은 git 출력을 실제로 분류해 원인과 해결 명령을 알려준다.)
- 업데이트가 안 될 때 실제로 많은 원인: **폴더를 복사해 옴**(=git 저장소가
  아님), 또는 **이 PC에서 push를 안 함**. 런처 상단의 커밋 해시로 어느
  버전인지 먼저 확인할 것.
- 측정용 PC를 GitHub 최신으로 강제로 맞추려면:
  `git fetch origin && git reset --hard origin/main`
  (사용자 설정 4종은 `.gitignore`에 있어 이 명령에도 보존된다)

## 0-6. 런처(바탕화면 바로가기) + 버튼 하나로 업데이트

측정용 노트북에서 터미널을 열지 않고 쓰도록 런처를 만들었다.

| 파일 | 역할 |
|---|---|
| `launcher.pyw` | 실행/업데이트 GUI. `.pyw`라서 검은 콘솔 창이 안 뜬다 |
| `바로가기_만들기.bat` | 바탕화면에 "PD 측정 스테이션" 바로가기 생성 (한 번만 실행) |
| `런처_실행.bat` | 바로가기 없이 바로 런처를 띄우는 예비 수단 |
| `최초설치.bat` | 새 PC에 필요한 것을 전부 설치 (아래 참고) |
| `dll_check.py` | DLL 3개가 **실제로 로드되는지** 확인. 설치 마지막 검증 단계 |

**런처 기능**
- `▶ 측정 프로그램 실행` — 32비트 파이썬을 자동으로 찾아 `pd_iv_station.py` 실행.
  버전을 하드코딩하지 않고 `py -3-32` → `py -3.13-32` → … 순으로 탐색하므로
  노트북마다 파이썬 버전이 달라도 동작한다. 못 찾으면 32비트 설치 안내.
- `⟳ 업데이트 (git pull)` — PowerShell을 사용자가 직접 열 필요 없이
  `git pull --ff-only`를 대신 실행하고 결과를 로그창에 보여준다.
- 상단에 현재 버전(커밋 해시·날짜·메시지) 표시.

**exe로 안 만든 이유(중요):** PyInstaller로 exe를 만들면 코드가 그 안에
굳어서 수정할 때마다 새 exe를 다시 만들어 전달해야 한다. 런처 방식은
코드를 git 저장소로 두고 버튼이 `git pull`을 눌러주는 구조라 **런처는 한 번만
배포하면 되고, 이후 수정은 사용자가 버튼 한 번 누르는 것으로 반영된다.**

**⚠ 업데이트가 막히지 않도록 `.gitignore`를 손봤다.**
`station_config.json` / `station_presets.json` / `bioled_presets.json` /
`bioled_settings.json`은 노트북마다 값이 다른 사용자 설정이다. 이게 추적되면
`git pull` 때마다 충돌이 나서 업데이트가 막히므로 전부 무시 목록에 넣었다.
(`it_config.json`은 템플릿 성격이라 추적 유지)

**`최초설치.bat`이 까는 것 (2026-09-04 개정)**

1. 32비트 파이썬 — DLL 3종이 전부 x86이라 64비트 파이썬에서는 로드 자체가 안 됨
2. **Visual C++ 2013 재배포 패키지 (x86)** — `KXCIclient.dll`의 `MSVCR120.dll`
   의존성. 0-2절의 그 오류를 막는 단계다. **이번에 새로 추가됨**
3. Git for Windows — 업데이트 버튼용
4. `openpyxl`, `pyserial`
5. **업데이트 연결** — 복사해 온 폴더를 그 자리에서 git 저장소로 승격
6. `dll_check.py`로 **DLL 3개를 실제로 `ctypes.CDLL`로 열어보는 검증**

⚠ 2단계에서 **x64가 아니라 x86**을 깐다. 64비트 Windows에서도 그렇다 — 정작
필요한 건 32비트 DLL이 링크하는 32비트 런타임이기 때문이다. 그래서 설치 여부도
`System32`가 아니라 `SysWOW64\msvcr120.dll`로 확인한다(64비트 Windows에서
`System32`는 64비트용 폴더라, 거기를 보면 x64 재배포만 깔린 PC를 '이미 설치됨'
으로 잘못 판정한다).

⚠ `winget install`에 **`--source winget`을 반드시 붙인다.** 안 붙이면 msstore
소스까지 뒤지는데, 실제로 이 PC에서 msstore 조회가 실패해서 설치가 통째로
깨졌다. (이 인자는 저장소에 **한 번도 커밋된 적이 없었다** — 배포용
`Downloads\Kiethly_4200_설치파일` 사본에만 손으로 들어가 있어서, 새 PC에
`git clone`으로 받으면 없는 상태였다. 이번에 커밋에 포함시켰다.)

⚠ **"설치했다"가 아니라 "로드된다"를 확인해야 한다.** DLL 의존성 누락은 파일이
제자리에 멀쩡히 있어도 발생하므로, `ctypes`로 직접 열어보기 전에는 드러나지
않는다. 5단계 검증이 그 역할이다.

### 5단계 '업데이트 연결' — 복사해 온 폴더도 업데이트가 되게 (2026-09-04 추가)

업데이트 버튼은 `git pull`이라 폴더에 `.git`이 있어야 한다. 그런데 폴더를
통째로 **복사**해 오면 파일은 최신이어도 `.git`이 없어서 업데이트가 막힌다.
실제로 `Downloads` 배포 폴더가 그 상태였다. clone을 다시 받게 하는 대신,
있는 폴더를 그 자리에서 저장소로 승격시킨다:

```
git init -b main
git remote add origin <REPO_URL>
git fetch origin
git reset --quiet origin/main          # ← mixed. --hard 아님. 아래 이유 참고
git branch --set-upstream-to=origin/main main
```

**⚠ 여기서 `--hard`를 쓰면 안 된다 — 실행 중인 배치 파일 자신이 덮어써진다.**
`cmd.exe`는 배치 파일을 통째로 읽어두지 않고 **줄 단위로 그때그때 다시 읽는다.**
`git reset --hard`가 작업 파일을 갈아끼우면 그 대상에 지금 실행 중인
`최초설치.bat` 자신이 포함되고, cmd가 예전 파일 오프셋으로 바뀐 파일을 읽어
엉뚱한 줄로 튄다. mixed reset은 HEAD와 인덱스만 맞추고 **작업 파일은 전혀
건드리지 않으므로** 이 사고가 원천적으로 없다.

파일 내용을 실제로 저장소에 맞추는 일은 스크립트 **맨 마지막**으로 미뤘다.
거기서 `git status --porcelain -uno`로 다른 파일이 있는지 보고, 있으면 목록을
보여준 뒤 `choice`로 확인을 받는다. 덮어쓰기는 되돌릴 수 없으니 묻지 않고
실행하지 않는다. 확인 후 실행하는 줄은 이렇게 생겼다:

```
pushd "%APPDIR%" & git checkout -- . & popd & ... & pause & exit /b 0
```

**한 줄에 종료까지 몰아넣은 게 핵심이다.** cmd는 논리적 한 줄을 먼저 읽어
파싱한 뒤 실행하므로, 이 줄은 이미 메모리에 올라와 있다. 그래서 `git checkout`이
파일을 갈아끼워도 뒤이은 `pause`/`exit /b`는 파일을 다시 읽지 않고 안전하게
끝난다. 여기서 `goto`를 쓰거나 다음 줄로 넘어가면 파일을 다시 읽게 되어 위험하다.

부수적으로 `-uno`와 `core.quotepath=false`를 쓴다. `-uno`는 추적하지 않는 파일
(측정 데이터, 설정 JSON)을 목록에서 빼서 사용자 데이터가 위험해 보이지 않게
하고, `quotepath=false`는 한글 파일명이 8진수 이스케이프로 깨지는 것을 막는다
(끄지 않으면 `최초설치.bat`이 알아볼 수 없는 문자열로 나온다).

**검증:** 저장소 파일을 `.git` 없이 임시 폴더에 복사해 실제 실행. 승격 후
`main...origin/main` 추적 확인, Y/N 두 경로 모두 정상 종료, 사용자 설정
(`station_config.json`)과 추적되지 않는 파일이 보존되는 것 확인.

**전제:** 그 노트북에 **Git for Windows**가 설치돼 있어야 한다. 이제 폴더를
복사해 와도 `최초설치.bat`이 저장소로 승격시켜 주므로 `git clone`이 필수는
아니다. 승격 전(그냥 복사만 한 상태)에는 런처가 그 사실을 알려주고 업데이트
버튼을 비활성화한다.

## 0. 이번 개정에서 달라진 것 (요약)

- **`pd_iv_station.py`(KITE 스타일 4탭 GUI)를 새로 작성 완료.** 8절에서 요구한
  구조(SMU 구성 / 측정 설정 / 측정 실행 / I-T)를 갖췄다. 아래 7절 참고.
- **엑셀 내보내기를 실제 `pd_app.parsing.parse_file`로 돌려서 검증함** (요약이나
  추측이 아니라 pandas/streamlit을 설치해 진짜로 실행). 결과: `warnings: []`,
  Range I·라벨·브래킷 코드 모두 정상 인식. 상세는 6절 끝부분 참고.
- **9절 미해결 항목 #1(소자 결선)이 실측 예시 파일로 해소됨.**
  `C:\Users\mintj\photodetector-app\example\15s_1 [dd876543].xls`의 Settings
  시트를 직접 열어보니 **SMU1 = Cathode = Common(모드3), SMU2 = Anode =
  Voltage Sweep(모드1/func1)** 이 실제 랩 관행이었다. `pd_iv_station.py`의
  기본 SMU 구성값을 이에 맞춰 넣어뒀다(탭1에서 다르면 바로 수정 가능).
- Range I 문자열 표기를 `"10 uA"`(공백 있음)에서 실제 KITE 산출물과 동일한
  `"10uA"`(공백 없음)로 맞췄다.
- **폴더를 정리했다:**
  - 루트: `pd_iv_station.py`(메인 GUI, 실행 진입점) + `KXCIclient.dll` +
    `it_config.json` — 앱을 실행하려면 이 셋이 필요.
  - `cli_tools/`: 예전 단독 CLI 스크립트(`pd_iv.py`, `pd_it.py`,
    `bioled_controller.py`, `kxci_dll_test.py`) + DLL 사본 + `iv_data/`.
    GUI가 대부분의 기능을 흡수했지만, 개별 점검용으로 남겨둠.
  - `_archive_failed_pyvisa_probes/`: 3절에 기록된, **완전히 실패하고 폐기된**
    pyvisa raw-socket 탐색 스크립트 3개(`kxci_probe*.py`). `kxci_dll_test.py`로
    완전히 대체되었으므로 **필요 없으면 지워도 되는 폴더** — 참고용으로만 남겨둠.
- **아직 실기(하드웨어) 테스트는 안 함.** 이번 세션은 DLL 없이 Dry-run
  모드로만 GUI 로직을 검증했다(연결 시퀀스, 채널 구성 전송, 세션 누적, CSV
  즉시 기록, 엑셀 내보내기). 다음 실기 접속 때 10절 순서대로 확인할 것.

## 0-7. 같은 날 저녁 — 1차 실기 테스트 결과 및 후속 수정

사용자가 실제로 4200에 연결해 처음 돌려봄. 로그:

```
[4200] 연결 (DLL): ret=1, socket_err=0
[4200] 응답: KI4200 V9.1-SP1
[SMU] 채널 정의(DE) 전송 완료
[세션] 시작: sessions\Sample_260729_190525
[측정] Dark 0.0V→-1.0V ...
    ⚠ RI2 Syntax Error — RG2로 폴백
[측정] Dark 완료: 0점 -> sessions\Sample_260729_190525\trace_01_Dark.csv
```

**좋은 소식 2가지:**
- **연결 자체는 완전히 정상.** `ret=1, socket_err=0`, ID 응답까지 정확.
- **RI → RG 자동 폴백 로직이 실제로 동작하는 것을 확인.** (다만 아래 ⚠ 참고)

  > ⚠ **이때 내린 "이 장비는 RI가 안 먹힌다"는 결론은 나중에 틀린 것으로
  > 밝혀졌다.** 진짜 원인은 컴플라이언스가 Range보다 컸던 것이다(당시 기본값
  > Range 10uA + 컴플라이언스 1mA = 100배). 자세한 내용은 **0-4절**.
  > 이 문단은 당시 판단 과정을 남겨두기 위해 그대로 둔다.

**나쁜 소식 1가지 — 근본 원인 찾아 수정함:**
- **"Dark 완료: 0점"** — 스윕은 실행됐는데 데이터가 하나도 안 왔다.
  원인으로 가장 유력한 것: 매뉴얼 5.2절의 채널 이름 자리표시자 `'BBBBBB'`,
  `'CCCCCC'`가 **정확히 6글자**인데, 그날 기본값으로 넣어둔 `'CathodeV'`
  (8글자)/`'CathodeI'`(8글자)가 이를 넘겨서 `CH1` 정의 자체가 조용히
  Syntax Error 났을 가능성이 높다. 문제는 `configure_channels()`가 그
  실패를 체크하지 않고 무조건 "채널 정의(DE) 전송 완료"라고 로그를 찍었다는
  것 — **실패가 성공처럼 보였다.**
- **수정 내용:**
  1. 기본 채널 이름을 6글자 이내로 변경: `VK`/`IK`(SMU1, Common),
     `VA`/`IA`(SMU2, 스윕 — 4.3절에서 41점 수신까지 검증됐던 바로 그 이름).
  2. 탭1에서 이름을 6글자 넘게 입력하면 자동으로 잘라내고 로그에 경고.
  3. **모든 설정 명령(`DE`/`CH`/`SS`/`VR`/`IR`/`VC`/`IC`/`IT`/`RS`/`DM2`
     등)에 대해 전송 직후 상태 바이트를 확인하는 `_w_checked()`로 교체.**
     이제 Syntax Error가 나면 그 즉시, 어떤 명령이 실패했는지 로그에 뜬다
     (이전엔 `RI`만 이렇게 확인하고 있었음).
  4. `DO` 조회의 **원본 응답을 항상 로그에 남기도록** 변경(`[DO 'IA'] raw=...`).
     "0점" 같은 문제는 파싱 전 raw 문자열을 봐야 원인을 알 수 있다.
  - **⚠ 이 수정 자체는 아직 실기로 재확인 안 됨.** 다음 실기 세션에서 Dark를
    다시 돌려서 이번엔 몇 점이 오는지, 그리고 Syntax Error 로그가 완전히
    사라졌는지 확인할 것.

**이번에 추가된 기능 (사용자 요청):**
- **탭3에 실시간 누적 그래프.** `tkinter.Canvas`로 직접 그림(numpy/matplotlib
  없이) — 전압 선형·|전류| 로그스케일, 트레이스마다 다른 색(가능하면 `pd_app`
  기본 배색과 동일하게 맞춤). 측정/삭제/라벨수정/순서변경 시마다 다시 그려짐.
- **트레이스 목록에서 임의 위치 삭제 / 라벨 수정 / 순서 변경(위·아래).**
  실제 4200(KITE)은 실행·Append만 가능하고 시트 이름 지정이나 중간 삭제가
  안 되지만, 이 프로그램은 엑셀을 매번 새로 생성하기 때문에 이런 제약이 없다
  — `Session.remove_at`/`update_label`/`move`가 순서를 바꾸면 브래킷 코드와
  시트 이름(`Data`/`AppendN`)은 내보내기 시점에 현재 순서 기준으로 다시 계산됨.
- **엑셀 파일명의 샘플명을 세션 시작 이후에도, 내보내기 직전까지 자유롭게
  수정 가능.** (세션 폴더 이름 자체는 세션 시작 시점 이름으로 고정 — CSV
  백업 경로일 뿐 엑셀 파일명과는 무관)
- **탭0 "사용법"** — 처음 쓰는 사람을 위한 상세 안내(연결 순서, 탭별 설명,
  로그 읽는 법, 문제 발생 시 절차). 아직 파일럿 단계임을 상단에 명시해 둠.
- `openpyxl` 미설치 시 "32비트 파이썬에 설치하라"는 명확한 안내 메시지로 교체.
  **주의: `pip install openpyxl`을 64비트 기본 파이썬에 설치해도 GUI를 돌리는
  32비트 파이썬에는 안 잡힌다.** 반드시
  `py -3.13-32 -m pip install openpyxl pyserial` 로 설치할 것.
- 이번 라운드에서 트레이스 삭제/재배치/재라벨/파일명 분리 로직을 실제로
  스모크 테스트하다가 **버그 하나를 잡았다**: `export_excel()` 안에서 시트
  이름을 담는 반복문 변수와 샘플명 변수 이름이 둘 다 `name`이라 시트 이름이
  샘플명을 덮어써 파일명이 엉뚱하게(`(Append1)[...]` 식으로) 나갔었음.
  변수명을 분리(`display_name`/`sheet_name`)해서 수정, 재검증 완료(파일명이
  올바르게 나오는 것 + `pd_app.parsing.parse_file()`로 경고 0건 재확인).

## 0-8. 2번째 실기 로그 — 사실은 Dry-run이 켜져 있었던 것

사용자가 채널명 수정 후 다시 돌렸는데 또 "0점"이 나왔다. 로그를 보니 모든
명령이 `[4200] DE`, `[4200] CH1,...` 식으로 그대로 echo만 되고, `RI2` Syntax
Error 체크도 전혀 안 뜨고, `DO` 응답이 통째로 `''`였다 — 이건 하드웨어 문제가
아니라 **`_raw_send()`가 딱 이 형태로 로그를 남기는 건 `dry=True`일 때뿐**이라
**Dry-run 체크박스가 켜진 채로 측정한 것**이었다. `App.dry_run`이
`tk.BooleanVar(value=True)`로 **앱을 켤 때마다 무조건 True로 초기화**되던 게
원인 — 이전 세션에서 껐어도 앱을 재시작(코드 업데이트 반영, openpyxl 설치 후
재실행 등)하면 조용히 다시 켜졌다.

**수정:**
- Dry-run 상태를 `station_config.json`에 저장하고 다음 실행 때 그 값으로
  복원하도록 변경(`_on_dry_run_change`).
- 창 맨 위에 상태를 절대 놓칠 수 없게 **색깔 배너**를 추가:
  주황(`🔶 DRY-RUN 켜짐`) / 빨강(`🔴 실기 모드`).
- **다음에 "0점"이 또 나오면 제일 먼저 이 배너부터 확인할 것.**

## 0-9. BioLED 포트 설정 — "USB"는 포트 이름이 아님

사용자가 `it_config.json`의 `"mightex_port"`를 `"USB"`로 바꿔놨었는데, 이건
동작하지 않는다. BioLED는 USB 케이블로 연결되지만 pyserial이 실제로 여는
대상은 **Windows가 붙이는 COM 번호(COM3, COM7 등)** 다 — 장치관리자 → 포트
(COM & LPT)에서 확인해야 한다. 게다가 `it_config.json`의 `mightex_port`는
**레거시 `cli_tools/pd_it.py` 전용**이라, 이 값을 고쳐도 메인 GUI(`pd_iv_station.py`)
의 BioLED 연결에는 전혀 영향이 없었다 — 두 config가 별개라는 걸 문서에 명시만
해놓고 UI에는 안 드러나 있었던 게 문제.

**수정:** 상단 바에 "BioLED 포트"/보드레이트 입력칸을 직접 추가했다(더 이상
JSON을 손으로 안 고쳐도 됨). 연결에 성공하면 그 값이 `bioled_settings.json`에
저장되어 다음 실행 때 자동으로 채워진다. **아직 실제 COM 번호로 연결 테스트는
안 됨 — 장치관리자에서 번호 확인 후 여기 입력하고 "BioLED 연결" 눌러볼 것.**

## 0-9-1. 파장→포트 기본 배정이 틀려서 850 nm가 조용히 안 켜졌다 (2026-09-04)

**증상:** 드롭다운에서 `8: 940 nm`를 고르면 불이 들어오는데 `7: 850 nm`로
바꾸면 오류 한 줄 없이 불만 안 들어온다.

**원인:** 기본 배정이 `{wl: {"channel": i + 1}}`, 즉 파장 목록 순서대로
1~8번 포트였다. 940 nm는 목록 첫 번째라 포트 1, 850 nm는 두 번째라 포트 2다.
실제 장비는 2채널이고 LED는 포트 1 하나에만 꽂혀 있었으므로, 850 nm를 고르면
아무것도 안 꽂힌 포트 2로 전류가 나갔다.

짚어둘 점 셋:

- **`_check_channel`이 이걸 못 잡는다.** 포트 2는 장비에 실제로 있는 채널이라
  범위 검사를 통과한다. "포트는 있는데 아무것도 안 꽂혀 있다"는 상태는
  소프트웨어가 알 방법이 없다. 검사는 `nch`보다 큰 번호만 걸러낸다.
- **드롭다운 숫자가 포트 번호처럼 보인다.** `8: 940 nm`의 8은 엑셀 브래킷
  코드(`LABEL_TO_SYMBOL`)인데 포트 번호와 똑같이 1~8 범위라, 8번을 골랐으니
  포트 8로 나가겠거니 하게 된다. 실제로는 정반대로 포트 1이었다.
- **파장을 바꾸면 이전 포트를 끈다**(`_apply_live_percent`). 그래서 940→850
  전환은 "안 켜진다"가 아니라 "켜져 있던 게 꺼진다"로 보인다.

**수정:**

1. `DEFAULT_BIOLED_SETTINGS`를 **전부 포트 1**로 바꿨다. 8채널 장비를 가정한
   예전 기본값은 실제 장비에서 거의 항상 틀렸다. 채널이 몇 개인 장비든 1번은
   반드시 존재하므로, 포트를 여러 개 쓰는 환경에서만 'LED 포트 배정'에서
   바꾸게 하는 편이 안전하다. `cli_tools/bioled_controller.py`의
   `DEFAULT_SETTINGS`도 같은 이유로 맞췄다(같은 `bioled_settings.json` 공유).
2. 연결할 때 **실제 배정을 로그에 항상 찍는다**(`_warn_channel_mapping`).
   `[LED] 파장 -> 포트 배정: 940 nm=포트1, 850 nm=포트1, ...` 이 한 줄이
   있었으면 이 문제를 즉시 알아봤을 것이다. 브래킷 코드와 헷갈리지 않도록
   경고 문구도 같이 남긴다.

⚠ `bioled_settings.json`은 `.gitignore` 대상(노트북마다 다른 사용자 설정)이라
**업데이트로 전파되지 않는다.** 이미 이 파일이 있는 PC는 기본값 변경의 영향을
받지 않으므로, 그 PC에서는 'LED 포트 배정'에서 직접 고쳐야 한다.

## 0-10. 같은 날, UX/기능 개선 라운드 (그래프·프리셋·상태코드 등)

사용자가 실기 성공 로그(21점, 이후 41점 정상 수신)를 확인한 뒤 요청한 내용들:

1. **파장 정렬 + 브래킷 번호 표시.** `WAVELENGTHS`를 내림차순(940 먼저)으로
   바꾸고, 드롭다운에 `"8: 940 nm"`처럼 `pd_app` 브래킷 코드 번호를 같이
   보여준다(`WL_DISPLAY`/`WL_DISPLAY_TO_KEY`, `App._wl_key()`).
2. **파일명 미리보기.** 트레이스 목록 아래 "내보낼 파일명" 라벨이
   `(샘플명)[브래킷].xlsx` 형태로 실시간 갱신됨(이미 자동 조합되던 기능이라
   존재를 몰랐던 것 — 미리보기로 눈에 보이게 함).
3. **그래프가 안 보이던 버그 수정.** 실측 데이터가 `IA` 전부 `0.0`이었는데,
   기존 `_redraw_plot()`이 `i != 0`으로 필터링해서 표시할 점 자체가 0개가
   되고 "표시할 데이터 포인트가 없습니다"만 뜨는 구조였다. 0을 숨기지 않고
   축 맨 아래에 그리도록 수정 + `winfo_width()==1`(위젯이 아직 한 번도
   그려진 적 없을 때의 tkinter 함정) 방어 코드 추가.
4. **컴플라이언스/오버플로 확인 — 상태 코드 컬럼 추가.** `DO` 응답 토큰이
   실제로 `"N-1.00000E+00"`처럼 **앞에 한 글자 상태 코드**를 달고 온다는 걸
   실측 로그에서 확인했다(`N`으로 보임). 이를 버리지 않고 파싱해서
   (`Keithley4200.fetch_with_status`) CSV/엑셀에 **"Status" 3번째 열**로
   저장하고, `N`이 아닌 점이 있으면 로그에 개수를 요약해서 경고한다.
   ⚠ `N` 등 각 코드의 정확한 의미는 아직 매뉴얼로 100% 확인 전 — 사용자가
   Reference Manual의 상태 문자 표를 갖고 있으니 대조 필요. Status 열을
   추가해도 `pd_app.parsing.parse_file()`은 `AnodeV`/`AnodeI`만 이름으로
   골라 읽으므로 호환성엔 영향 없음(재검증 완료, `warnings: []`).
5. **BioLED 세기 프리셋을 이 프로그램에서 직접 등록.** 탭3에 "+ 프리셋 추가"
   버튼 추가 — 예전엔 `cli_tools/bioled_controller.py`를 따로 열어야만
   등록할 수 있었음(같은 `bioled_presets.json`을 공유하므로 어느 쪽에서
   등록해도 서로 보임).
6. **I-T 탭을 `it_config.json`의 파장×OD 중첩 구조 대신, 탭3와 같은
   `bioled_presets.json` 프리셋을 그대로 재사용하도록 재설계.** 사용자가
   지적한 문제: "한 파장에 여러 세기로 미리 등록해둔 프리셋을 I-T에 입력할
   방법이 없다"는 것. 이제 파장만 고르면 그 파장에 등록된 프리셋 전부를
   세기 오름차순으로 가져와 `dark → P1 → dark → ... → Pn → dark(끝)`
   시퀀스를 자동 구성한다(프리셋 N개 → dark N+1번, light N번). OD별로
   프리셋을 나눠 관리해야 하는 경우는 아직 미지원 — 필요해지면 라벨에
   OD를 적어 넣고 필터링하는 방식을 추가로 논의할 것. `it_config.json`은
   이제 `sample_interval_s`/`compliance_A`/`range_margin`/`bias_V`/
   `dark_s`/`light_s` 전역값 용도로만 쓰이고, 예전 `powers`/`channels`
   중첩 구조는 더 이상 읽지 않는다(BioLED 채널/max_mA는 `bioled_settings.json`
   재사용).
7. **로그 창 높이를 사용자가 드래그로 조절**할 수 있게 `ttk.PanedWindow`로
   레이아웃 변경.
8. **Dry-run 배너 이름을 "실측 모드"로 확정.**

## 0-11. BioLED 프리셋에 OD(ND필터) 차원 추가

사용자 요청: "0~100%를 쓰지만 ND 필터를 쓰냐 안 쓰냐, 어떤 OD 값이냐에 따라
프리셋을 묶어놓고 싶다. OD=0일 때 등록한 프리셋은 I-T에서 그 파장·OD를
고르면 그 값들만 불러오게." — `bioled_presets.json` 스키마를 바꿨다.

**이전**: `{파장: [{"label","percent"}, ...]}`
**이후**: `{파장: {OD: [{"label","percent"}, ...]}}` (예: `{"530nm": {"OD0": [...], "OD1": [...]}}`)

- 탭3에 "OD(ND필터)" 입력칸(직접 타이핑 가능한 콤보박스) 추가. 파장을 바꾸면
  그 파장에 등록된 OD 목록으로 콤보박스가 갱신되고, OD를 바꾸면 세기
  프리셋 드롭다운도 그 파장·OD 조합만 걸러서 보여준다. "+ 프리셋 추가"는
  현재 선택된 OD 아래에 등록한다.
- 탭4(I-T)에도 OD 드롭다운을 추가(readonly — 이미 프리셋이 등록된 OD만
  고를 수 있음). 파장·OD 조합에 맞는 프리셋만 가져와 시퀀스를 구성한다.
- **`cli_tools/bioled_controller.py`도 같이 고쳤다** — `bioled_presets.json`을
  두 프로그램이 공유하기 때문에, 한쪽만 새 스키마를 쓰면 다른 쪽이 못
  읽거나(구버전은 dict를 list로 착각) 깨진다. 이제 두 프로그램 다 같은
  `{파장: {OD: [...]}}` 구조를 쓰고, 각자 화면에 OD 선택 UI가 있다.
  실제로 두 프로그램을 순서대로 띄워서 한쪽에서 등록한 프리셋(OD0, OD1)을
  다른 쪽이 정확히 읽어오는 것까지 스모크 테스트로 확인했다.
- 예전(OD 구분 없는 평면 리스트) 형식 파일을 만나면 `{"OD0": [...]}`로
  자동 감싸는 `normalize_led_presets`/`normalize_presets`를 양쪽에 추가해
  데이터 손실 없이 새 스키마로 넘어가게 했다(다만 이 사용자의 파일은 아직
  실제 데이터가 없어 마이그레이션이 실제로 시험되지는 않음).
- I-T 출력 CSV 파일명에도 OD를 넣었다(`{샘플}_{파장}_{OD}_{bias}V`).
- 부수 수정: `App.destroy()`가 반복 예약된 `after()` 콜백(`_drain_queue`)을
  취소하지 않아 창을 닫을 때 "invalid command name ... _drain_queue" 같은
  에러가 뜰 수 있던 것도 `after_cancel`로 고쳤다.

## 0-12. BioLED 통신 방식 전면 정정 — 시리얼이 아니라 USB HID였다

**이게 이번 세션 최대 발견.** pyserial 기반 BioLED 코드는 처음부터 끝까지
전부 추측이었다(`bioled_controller.py` 원본 docstring에도 "⚠️ 모델마다
다를 수 있으니 확인할 것"이라고 스스로 적혀있었음). 사용자가 COM 포트를
아무리 찾아도 안 나오는 걸 계속 추적하다가, 실제 장비 모델
**BLS-SA02-U**의 공식 SDK(`BLS_led_controller_software_release_V1.8_20210729`,
다운로드 폴더에 있었음)를 열어보고서야 확인됨:

> Mightex bioLED Controller SDK Manual: **"the BIOLED Control driver is
> designed as a HID device"**

즉 **시리얼(COM 포트) 장치가 아니라 USB HID 장치**다. 그래서:
- 장치관리자에 "포트(COM & LPT)"로 뜰 방법이 원천적으로 없음 (신형/구형
  PC 문제가 아니라 이 장치군 자체의 특성).
- pyserial(`serial.Serial(port, baud)`)로 열 수 있는 대상 자체가 없음.
- `BioLEDController.exe`(Mightex 자체 SW)가 정상 동작하는 이유는 HID
  인터페이스로 직접 통신하기 때문 — 우리는 그동안 완전히 잘못된 계층을
  두드리고 있었음.

**해결**: SDK에 32비트 `Mightex_BLSDriver_SDK.dll`(cdecl) +
`HIDDLL.dll`이 포함돼 있어서, Keithley `KXCIclient.dll`과 완전히 같은
ctypes 패턴으로 붙일 수 있었다. 다운로드 폴더 경로:
`C:\Users\mintj\Downloads\BLS_led_controller_software_release_V1.8_20210729\...\SDK\LIB\x86\`
에서 두 DLL을 이 프로젝트 루트와 `cli_tools/`로 복사해 넣었다.

**API 요약** (`Mightex_BLSDriver_SDK.h` / SDK Manual v1.2.1):
```
MTUSB_BLSDriverInitDevices()                      -> 연결된 장치 수
MTUSB_BLSDriverOpenDevice(0)                       -> handle (0 이상 성공, -1 실패)
MTUSB_BLSDriverSetMode(handle, ch, mode)           -> mode: 0=DISABLE 1=NORMAL 3=TRIGGER
MTUSB_BLSDriverSetNormalCurrent(handle, ch, cur)   -> cur는 "0.1%" 단위! (500=50.0%)
MTUSB_BLSDriverCloseDevice(handle)
```
채널은 1-based. **세기는 장치 API 자체가 %(0.1% 단위)로 받는다** — 그래서
예전에 쓰던 "채널 최대 전류(max_mA) × %" 환산이 아예 필요 없다.
`bioled_settings.json`에서 `max_mA`/`port`/`baud` 키를 전부 제거했다.

**변경된 파일:**
- `pd_iv_station.py`: `BioLED` 클래스 전체 재작성(ctypes). 상단 바의
  "BioLED 포트"/보드레이트 입력칸을 제거 — HID라 포트 개념이 없어서
  그냥 "BioLED 연결" 버튼만 누르면 됨.
- `cli_tools/bioled_controller.py`: `BioLEDDevice` 백엔드를 동일하게
  ctypes로 재작성. OD/프리셋 UI 로직(0-11절)은 그대로 유지 — 전송
  계층만 바뀐 것.
- **신규** `cli_tools/bls_dll_test.py`: `kxci_dll_test.py`와 동일한 패턴의
  개별 연결 진단 스크립트. 장치 수/시리얼번호/채널 수를 확인하고,
  원하면 채널1을 5%로 3초 켜보는 것까지 대화형으로 해볼 수 있음.
- `Mightex_BLSDriver_SDK.dll`, `HIDDLL.dll`을 루트와 `cli_tools/`에 배치.

**⚠ 아직 실기로 검증 안 됨.** Dry-run 로직만 확인했다. 이 세션의 도구
실행 환경 자체가 사용자의 실제 USB 하드웨어를 볼 수 없어서(샌드박스),
`InitDevices()`가 실제로 장치를 찾는지는 사용자가 직접
`cli_tools\bls_dll_test.py`로 확인해야 한다. **다음 실기 테스트 최우선
순위는 이것.** 참고로 `BioLEDController.exe`가 켜져 있으면 장치를
독점하므로 반드시 완전히 종료 후 테스트할 것.

## 0-13. `pd_app` 호환성 재확인

사용자가 다시 물어봐서 재확인: **호환된다.** 0/0-7절에서 이미 실제
`pd_app.parsing.parse_file()`을 두 번(최초 구현 시, 트레이스 편집 기능 추가
후) 직접 돌려서 `warnings: []`로 확인했다. 추측이 아니라 실행 결과다.

---

## 1. 프로젝트 목적

페로브스카이트/실리콘 듀얼모드 광검출기의 **I-V / I-T 측정을 자동화**한다.
기존에는 Keithley KITE에서 손으로 측정하고 Origin으로 그렸는데,
① 측정 자동화, ② 기존 분석 앱(`pd_app`)이 읽는 파일 포맷으로 자동 저장을 목표로 한다.

**최종 지향점:** KITE와 같은 스타일(SMU 구성 / 측정 설정 / 실행 분리)의 GUI에
자동화를 얹는 것. 명령줄이 아니라 플랫폼 형태여야 한다.

### 측정 프로토콜 (연구실 규칙 — 반드시 지킬 것)

| 항목 | 규칙 |
|---|---|
| Dark | `0 → −1 V`, `0 → +1 V` **두 번 나눠서** 측정 |
| 광전류 | `−1 → +1 V` **한 번에** 스윕 |
| Range I | 광전류들이 **컴플라이언스에 안 걸리는 선에서 가장 작고 동일한 값**으로 통일 (노이즈 바닥을 맞춰야 트레이스 간 비교가 성립) |
| 파장 변경 | **수동**. 사람이 LED를 바꿔 끼운 뒤 프로그램에서 해당 파장을 선택 |
| 광 세기 | 파장별 BioLED 세기를 **%로** 미리 등록 (예: 530 nm에서 1 mW = 10.9 %) |

---

## 2. 실행 환경 — ⚠ 32비트 제약

**`KXCIclient.dll`이 32비트(x86)라, Keithley를 제어하는 모든 코드는 32비트
파이썬에서 실행되어야 한다.** 64비트 파이썬에서는 DLL 로드 자체가 실패한다.

```powershell
# 실행 방법 (검증됨)
py -3.13-32 스크립트.py

# 비트수 확인
python -c "import struct; print(struct.calcsize('P')*8)"   # 32 여야 함
```

VSCode에서 `Ctrl+Shift+P` → "Python: Select Interpreter" → 32비트 항목을 고르면
새로 여는 터미널에 적용된다. **이미 열려 있던 터미널에는 소급 적용되지 않으므로
터미널을 새로 열어야 한다.**

### 이 제약이 라이브러리 선택에 미치는 영향

- **pandas / numpy는 피할 것** — 32비트 파이썬 3.13용 휠이 없을 가능성이 높다
- **순수 파이썬 패키지만 사용**: `openpyxl`(엑셀 쓰기), `pyserial`(BioLED)
- **GUI는 tkinter** (표준 라이브러리, 설치 불필요, 32비트에서 확실히 동작)
- **Streamlit 사용 금지** — 상호작용마다 스크립트를 재실행해서 측정 중 상태가
  날아갈 수 있다. 사용자가 명시적으로 배제를 요청함

```powershell
pip install pyserial openpyxl
```

---

## 3. ⚠ 실패한 접근 — 재시도 금지

Keithley 연결까지 오는 데 상당한 시간이 걸렸다. 아래는 **전부 시도했고 전부
실패한** 방법이므로 다시 하지 말 것.

| 시도 | 결과 |
|---|---|
| `pyvisa` + `TCPIP::192.168.0.200::8888::SOCKET` | 포트 8888은 **틀린 번호** (참고자료 오류). 실제는 **2105** |
| `pyvisa` + `TCPIP::...::2105::SOCKET` | 소켓은 열리나 **모든 명령이 무응답** |
| 종단문자 `\n` / `\r` / `\r\n` / 없음 × 명령 `*IDN?`/`ID`/`US`/`VE`/`UO`/`DE` (18조합) | **전부 타임아웃** |
| 연결 직후 배너 수신 대기 (raw socket) | 장비가 먼저 말을 걸지 않음 |
| STX(0x02)/ETX(0x03) 프레이밍 5종 | **전부 무응답** |

**근본 원인:** GPIB의 EOI는 인쇄 가능한 문자가 아니라 **버스의 물리적 하드웨어
신호**다. 따라서 raw socket에서 문자로 흉내낼 수 없다. Keithley가 이 변환을
대신 처리해주는 전용 클라이언트 DLL을 제공한다.

**결론: `pyvisa` 경로는 완전히 폐기. 반드시 `KXCIclient.dll` + `ctypes`를 쓸 것.**

---

## 4. 검증된 연결 방법 (실측 확인 완료)

### 4.1 네트워크 구성

```
PC(Wi-Fi) → ipTIME Extender-A3MU → Cat.6 랜선 → K4200 Ethernet 포트
K4200 고정 IP : 192.168.0.200
서브넷        : 255.255.255.0
게이트웨이     : 192.168.0.1
KXCI TCP 포트 : 2105          ← KCON의 KXCI 탭에서 확인/설정
```

**구동 전제:** K4200에서 **KITE를 완전히 종료**하고 **KXCI를 실행**해 두어야 한다.
(KCON에서 통신 인터페이스가 `Ethernet`으로 선택되어 있어야 함. Ethernet 모드에서는
Reading Delimiter / String Terminator 항목이 비활성화되는 것이 정상 — GPIB 전용
설정이라 Ethernet에서는 쓰이지 않는다.)

### 4.2 DLL 인터페이스 (바이너리에서 직접 확인)

파일: `KXCIclient.dll` (원본 위치 `C:\S4200\sys\bin\`), 이 폴더에 복사해 둠

```
Export (모두 cdecl — 'ret' 사용 → ctypes.CDLL 사용, WinDLL 아님):
  OpenKXCIConnection_C(char* ip, int port, int* socket_err) -> int
  SendKXCICommand_C(char* cmd, char* returned_data, int* socket_err) -> int
  GetKXCISpollByte_C(unsigned short* spoll, int* socket_err) -> int
  CloseKXCIConnection_C(void) -> void

접미사 없는 버전(OpenKXCIConnection 등)은 stdcall('ret 0xC') — VB용이므로 사용하지 않음
```

### 4.3 실측 확인된 동작

```
[4200] 연결 (DLL): ret=1, socket_err=0        ← ret=1 이 정상. 0이 아님에 주의
[4200] 응답: KI4200 V9.1-SP1                  ← ID 명령 응답
[IV] -1.0 V -> 1.0 V, step 0.05 V             ← 실제 스윕 성공
[IV] 41 points 수신                            ← (1-(-1))/0.05+1 = 41, 정확
```

**성공 판정:** `socket_err == 0` 으로 볼 것. `OpenKXCIConnection_C`의 반환값
의미는 매뉴얼에 명시되어 있지 않으나 실측상 성공 시 `1`이 나온다.

---

## 5. KXCI 명령 레퍼런스 (매뉴얼 Section 9에서 추출, 검증됨)

> 출처: *Model 4200-SCS Reference Manual*, 4200-901-01 Rev. P, Section 9 (KXCI)
> 원문 XPS는 사용자가 보유. 아래는 자동화에 필요한 부분을 정리한 것.

### 5.1 페이지 전환 명령

| 명령 | 의미 |
|---|---|
| `DE` | 채널 정의 페이지 |
| `SS` | 소스 설정 페이지 |
| `SM` | 측정 설정 페이지 |
| `MD` | 측정 제어 페이지 |
| `US` | 유저 모드 페이지 |

**각 페이지의 명령을 보내기 전에 반드시 해당 페이지 명령을 먼저 보내야 한다.**

### 5.2 채널 정의 (DE 페이지)

```
CH A,'BBBBBB','CCCCCC',D,E
  A      = SMU 채널 번호 (1~8)
  BBBBBB = 전압 이름 (임의 지정, 예: 'VA', 'V1')
  CCCCCC = 전류 이름 (임의 지정, 예: 'IA', 'I1')
  D      = 소스 모드   1=전압원  2=전류원  3=Common(high를 common에 연결)
  E      = 소스 함수   1=VAR1(스윕)  2=VAR2(스텝)  3=Constant(고정)  4=VAR1'

주의: D=3(Common)이면 E도 반드시 3(Constant)이어야 한다.
채널 번호 뒤에 아무것도 안 쓰면 그 채널은 꺼진다 (예: "CH4").

VS A,'BBBBBB',C    전압원(VSn) 정의.  C: 1=VAR1 2=VAR2 3=Constant 4=VAR1'
VM A,'BBBBBB'      전압계(VMn) 정의
```

### 5.3 소스 설정 (SS 페이지)

```
VR B,start,stop,step,compliance     VAR1 스윕 (전압원).  IR = 전류원 버전
  B = 1 Linear / 2 Log10 / 3 Log25 / 4 Log50
  ※ VR에는 채널 번호가 없다. DE에서 E=1(VAR1)로 정의된 채널이 대상이 된다.

VP/IP  start,step,steps,compliance[,index]   VAR2 스텝 설정
VC B,output,compliance                        Constant SMU 출력 (B=채널번호). IC=전류
VL/IL  ...                                    리스트 스윕 (최대 4096점)
ST A,B                                        오토 스탠바이 (A=채널, B=0/1)
RT / FS                                       VAR1' 비율 / 오프셋
```

### 5.4 측정 설정 (SM 페이지) — I-T(시간영역) 측정의 핵심

```
WT AAA.AAA    대기 시간 (0~100 초). 테스트 시작 지연
IN AA.AA      샘플 간격 (0.01~10 초)
NR AAAA       읽기 횟수 (4200 확장 모드에서 1~4096)
DM A          표시 모드  1=그래픽  2=리스트   ← 데이터 조회하려면 DM2
LI 'n1','n2'  리스트 모드에서 측정할 함수 지정 (DE에서 붙인 이름 사용, 최대 6개)
```

### 5.5 측정 제어 (MD 페이지) 및 데이터 조회

```
ME A          A=1 트리거+지운 버퍼에 저장 / (2,3,4는 매뉴얼 표 재확인 필요) / 6 중단
DO 'AAAAAA'   데이터 조회. AAAAAA = DE에서 붙인 이름 (예: DO 'VA', DO 'IA')
DO CHnT       채널 n의 시간 데이터
SV 'D name'   4200 내부에 파일 저장
```

### 5.6 전역/유틸 명령

```
IT A          적분시간  1=Short 2=Medium 3=Long
IT 4,X,Y,Z    커스텀 (4200 확장 모드 전용)
              X=지연계수 0~100, Y=필터계수 0~100, Z=A/D 적분시간(PLC) 0.01~100
RS A          측정 분해능 (3~7 digits, 4200 확장 모드)
RI A,B,C      SMU를 지정 레인지로 **즉시 고정** (A=채널, B=레인지, C=컴플라이언스)
              ← "Range I 통일"에 맞는 명령
RG A,B        오토레인징의 **하한만** 지정 (A=채널, B=최저 레인지)
              ← 전류가 커지면 위로 올라감. 통일 목적에는 RI가 맞음
              허용값: 프리앰프 없을 때 100E-9 ~ 100E-3 A
DR A          Data Ready 서비스 리퀘스트  0=비활성 1=활성
BC            데이터 버퍼 및 DataReady 비트 클리어
AC A          오토 캘리브레이션 (A=채널)
EC A          컴플라이언스 시 종료 설정
ID            장비 ID 조회  → "KI4200 V9.1-SP1"
EM A,B        4145 에뮬레이션(0) / 4200 확장모드(1) 전환
              B=0 이번 세션만, 1=이후 모든 세션(KCON 파일에 기록)
```

### 5.7 상태 바이트 (`GetKXCISpollByte_C`로 폴링)

| 비트 | 값 | 의미 |
|---|---|---|
| B0 | `0x01` | **Data Ready** — 측정 완료, 데이터 조회 가능 |
| B1 | `0x02` | **Syntax Error** — 직전 명령 문법 오류 |
| B4 | `0x10` | **Busy** — 측정 진행 중 |
| B6 | `0x40` | RQS (서비스 요청) |

**완료 판정은 B0을 폴링**하는 방식으로 구현되어 있다. B1이 서면 즉시 로그에
경고를 남기도록 되어 있다.

### 5.8 검증된 I-V 스윕 시퀀스 (실제로 41점 수신 성공)

```
DE
CH1,'VA','IA',1,1          SMU1: 전압원 모드, VAR1 스윕 함수
SS
VR1,-1.0,1.0,0.05,0.001    선형 스윕, -1→+1V, 0.05V 스텝, 컴플라이언스 1mA
SM
DM2                        리스트 모드
RI1,<range>,<compliance>   (선택) Range I 고정
MD
ME1                        측정 트리거
→ 상태바이트 B0 대기
DO 'VA'                    전압 데이터
DO 'IA'                    전류 데이터
```

응답 문자열에는 채널 헤더(`N1A` 등)와 지수 표기(`E-06`)가 섞여 오므로
**정규식으로 숫자만 추출**한다 (문자열 앞부분 깎는 방식은 헤더 형태가 바뀌면 깨짐):

```python
_NUM = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")
```

---

## 6. 출력 파일 포맷 규격 (`pd_app/parsing.py` 호환) — 검증 완료

기존 분석 앱(`pd_app`)이 그대로 읽을 수 있어야 한다.
**실제 `parsing.py`로 읽어 경고 0건으로 통과함을 확인했다.**

### 6.1 엑셀 구조

| 요소 | 규격 |
|---|---|
| 시트 이름 | 첫 측정 = `Data`, 이후 `Append1`, `Append2`, … |
| 데이터 컬럼 | `AnodeV`, `AnodeI` (헤더 1행) |
| Settings 시트 | 시트명 `Settings`. 아래 구조 반복 |

Settings 시트 내용 (A열=이름, B열=값):

```
==================================
Initial Run
Range I        10 uA
Label          Dark 0→-1V
==================================
Append 1
Range I        10 uA
Label          Dark 0→+1V
==================================
...
```

`parsing.py`는 `Initial Run` / `Append N` 블록명을 찾아 그 아래 `Range I` 값을
가져간다. 구분선(`=====`)은 건너뛴다.

### 6.2 파일명 브래킷 코드

```
"<샘플명> [<브래킷코드>].xlsx"      예)  FAPbI3_Si [dd47].xlsx
```

브래킷 코드는 **측정 순서대로 심볼 1글자씩**. 길이가 데이터 시트 수와 일치해야 한다
(불일치 시 `parsing.py`가 `Trace N`이라는 일반 라벨로 폴백하고 경고를 낸다).

```
d = Dark      8 = 940 nm    7 = 850 nm    6 = 740 nm    5 = 625 nm
4 = 530 nm    3 = 470 nm    2 = 405 nm    1 = 365 nm
```

(`pd_app/constants.py`의 `SYMBOL_MAP`과 반드시 동일해야 함)

### 6.3 파싱 검증 결과 (참고)

```
data_names: ['Data', 'Append1', 'Append2', 'Append3']
warnings : (없음)
  Dark    range_i=10 uA   legend=Dark (10 uA)
  Dark    range_i=10 uA   legend=Dark (10 uA) #2     ← 중복 Dark 자동 구분
  530 nm  range_i=10 uA   legend=530 nm (10 uA)
  850 nm  range_i=10 uA   legend=850 nm (10 uA)
```

---

## 7. 현재 파일 상태

**폴더 구조가 바뀌었다.** 루트에는 메인 GUI만 남기고, 예전 단독 스크립트는
`cli_tools/`로, 폐기된 탐색 스크립트는 `_archive_failed_pyvisa_probes/`로 옮겼다
(0절 참고).

| 파일 | 상태 | 비고 |
|---|---|---|
| `pd_iv_station.py` (루트) | ✅ **실기 동작 확인** | 5탭(사용법/SMU구성/측정설정/측정실행/I-T). I-V 측정·그래프·엑셀 내보내기까지 실기에서 정상. 측정 속도도 정상 범위 (0-4절) |
| `KXCIclient.dll` (루트) | ✅ 필수 | 32비트. `pd_iv_station.py`와 같은 폴더 |
| `Mightex_BLSDriver_SDK.dll` + `HIDDLL.dll` (루트) | ✅ 필수, **실기 동작 확인** | 32비트. BioLED가 USB HID임을 확인하고 새로 추가(0-12절) |
| `it_config.json` (루트) | ✅ 사용 중 | I-T 전역 설정(bias/dark_s/light_s/interval/compliance)만 사용. 파장별 프리셋은 이제 `bioled_presets.json` 사용 (0-11절) |
| `cli_tools/kxci_dll_test.py` | ✅ 동작(기존 검증) | Keithley DLL 연결 진단용 |
| `cli_tools/bls_dll_test.py` | 🆕 진단용 | BioLED HID DLL 연결 진단용(0-12절). BioLED 문제 생기면 이것부터 |
| `cli_tools/pd_iv.py` | ✅ 동작(기존 검증) | 예전 CLI I-V 스윕. GUI 탭3로 대체됨, 개별 점검용으로만 유지 |
| `cli_tools/bioled_controller.py` | ⚠ 단독 GUI(HID로 재작성됨) | 메인 GUI에서 프리셋 관리가 되므로 상시 필요하진 않음. 프리셋 파일은 공유(0-12절) |
| `cli_tools/pd_it.py` | ❌ 구버전(pyvisa+pyserial) | GUI 탭4로 이관 완료. 이 파일 자체는 그대로 방치(참고용, BioLED 부분도 구식 pyserial이라 실제로 안 됨) |
| `ui_theme.py` (루트) | ✅ 사용 중 | NBEDL 공용 디자인 토큰(#ed542b/Pretendard) + clam 테마 + HiDPI 처리 |
| `launcher.pyw` / `최초설치.bat` / `바로가기_만들기.bat` | ✅ 사용 중 | 실행·업데이트 런처와 최초 설치 자동화 (0-6절) |
| `_archive_failed_pyvisa_probes/*` | 🗑 폐기 후보 | 3절 실패 기록의 원본. `kxci_dll_test.py`로 완전 대체됨 — 필요 없으면 삭제해도 됨 |

### `pd_iv_station.py` 구조 (신규 구현)

```
Keithley4200   ctypes DLL 래퍼. configure_channels/setup_sources/vr_sweep/ir_sweep/
               vc_constant/setup_measure_iv/setup_measure_it/set_integration/
               set_resolution/set_range_fixed(RI 우선, Syntax Error시 RG로 자동 폴백)/
               trigger/fetch/wait_done
BioLED         pyserial. set_percent(channel, max_mA, percent). bioled_controller.py와
               설정 파일(bioled_settings.json/bioled_presets.json) 공유
Session        측정 직후 즉시 CSV 저장(trace_NN_<라벨>.csv) + session.json 갱신 +
               pd_app 호환 export_excel() (Data/Append#/Settings, 브래킷 코드 파일명)
App(tk.Tk)     ttk.Notebook 4탭. 측정은 threading + queue로 UI 스레드와 분리
```

**데이터 보호 설계 (유지됨):** 측정이 끝날 때마다 즉시
`sessions/<샘플명>_<타임스탬프>/trace_NN_<라벨>.csv`로 기록하고 `session.json`을
갱신한다. 앱이 죽어도 개별 트레이스는 디스크에 남는다. 내보내기는 그걸 합치는
작업일 뿐이다. (단, 이번 구현은 세션 재시작 시 CSV를 다시 불러와 이어가는 UI는
아직 없음 — 필요해지면 추가할 것.)

**엑셀 내보내기 실측 검증:** `pd_app`(다른 프로젝트, `C:\Users\mintj\photodetector-app`)의
`parsing.py`를 직접 import해 `parse_file()`을 돌려봤다 (pandas/streamlit을 이번
검증 목적으로 설치). 결과 `warnings: []`, `Range I: 10uA`, 브래킷 코드로부터
라벨 복원, Dark 중복 자동 `#2` 처리까지 전부 정상.

---

## 8. KITE 스타일 탭 구조 — 구현 완료, 실기 검증 남음

아래 스펙대로 `pd_iv_station.py`를 새로 작성했다 (Dry-run 로직만 검증, **실기 미검증**).
탭별로 구현 여부와 실기에서 특히 눈여겨봐야 할 지점을 표시해 둔다.

### 탭 1 · SMU 구성 (KITE의 채널 정의 화면에 대응)

- SMU 채널별 표: 채널번호 / 전압이름 / 전류이름 / 소스모드 / 소스함수 / 사용여부
- 소스 모드 드롭다운: `전압원(1)` `전류원(2)` `Common(3)`
- 소스 함수 드롭다운: `VAR1 스윕(1)` `VAR2 스텝(2)` `Constant(3)` `VAR1'(4)`
- **검증 로직 필수:** 소스 모드가 Common(3)이면 함수도 Constant(3)로 강제
- Constant로 설정된 채널은 출력값/컴플라이언스 입력란 활성화 (`VC`/`IC` 명령용)
- 미사용 채널은 `CH<n>`만 보내 끄기
- **구현 상태: ✅ 완료.** `App._build_tab_smu` / `App._collect_smu_channels` /
  `Keithley4200.configure_channels`. Common 선택 시 함수 Constant 강제하는
  검증 로직 포함(`on_mode_change`). 기본값은 0절에서 밝힌 실측 배선(SMU1=Common,
  SMU2=Sweep)으로 채워둠 — **실기에서 이 배선이 맞는지 반드시 먼저 확인**.

### 탭 2 · 측정 설정

- **스윕:** Dark 음/양 범위, 광전류 범위, 스텝, 컴플라이언스, 스윕 타입(Linear/Log)
- **적분시간(`IT`):** Short / Medium / Long / Custom(지연·필터·PLC 직접 입력)
- **분해능(`RS`):** 3~7 digits
- **Range:** Auto / `RI`(고정) / `RG`(하한만) + 레인지 값 드롭다운
- **I-T용:** 대기시간(`WT`), 샘플 간격(`IN`), 읽기 횟수(`NR`)
- 이 설정 전체를 **"측정 프리셋"으로 저장/불러오기** (KITE의 test setup처럼)
- **구현 상태: ✅ 완료.** `App._build_tab_measure`, 프리셋은
  `station_presets.json`에 이름별로 저장(`save_preset`/`save_preset_as`/`load_preset`).
  `IT`/`RS` 전역 명령은 매 측정 직전(MD 진입 전) 전송하도록 넣어뒀는데, 정확히
  어느 페이지 컨텍스트에서 유효한지는 매뉴얼에 명시가 없어 **실기 확인 필요**
  (아래 9번 새 항목 #7).

### 탭 3 · 측정 실행

- 파장별 BioLED 세기(%) 프리셋 표
- `Dark 0→−1V` / `Dark 0→+1V` / `선택 광원 I-V` 버튼
- Append 누적 목록 + 파일명 브래킷 코드 실시간 표시
- 마지막 측정 삭제 / 엑셀 내보내기
- 로그 창
- **구현 상태: ✅ 완료.** `App._build_tab_run`. BioLED 프리셋은
  `bioled_presets.json`/`bioled_settings.json`을 `cli_tools/bioled_controller.py`와
  그대로 공유하므로, 그 GUI에서 등록해둔 프리셋이 여기 드롭다운에 바로 뜬다.
  엑셀 내보내기는 실제 `parse_file()`로 검증 완료(0절).

### 탭 4 · I-T 측정

`cli_tools/pd_it.py`의 타임라인/Range 결정 로직을 DLL 방식으로 옮겨 통합.
시퀀스: `dark → P1 → dark → P2 → … → Pn → dark(끝)`, 광 세기는 %로 지정,
구간 길이(dark/light)는 사용자 입력, Range I는 해당 [파장, OD] 세트 전체에 고정.
- **구현 상태: ✅ 완료.** `App._build_tab_it` / `App._measure_it`. 기존
  `it_config.json`을 그대로 읽으므로 새 설정 파일이 필요 없다. `pd_it.py`의
  `DO 'T'`(시간 채널) 조회는 원본에도 `[VERIFY]` 표시가 있던 부분이라 그대로
  가져왔음 — 실기에서 안 되면 `DO CHnT` 형태로 바꿔야 할 수 있음(5.5절 참고).

### 공통 요구사항 (반드시 유지 — 모두 반영됨)

1. **32비트 파이썬 전제** — 시작 시 비트수 검사하고 아니면 명확한 안내 후 종료 (`_check_bitness`)
2. **측정은 워커 스레드** — UI 프리징 방지 (`_run_worker` = `threading` + `queue`)
3. **측정 직후 즉시 디스크 기록** — 데이터 유실 방지 (`Session.add_trace`)
4. **`pd_app` 호환 엑셀 출력** — 6번 규격 준수, 실제 파서로 검증됨
5. **Syntax Error 비트 감지 시 로그 경고** (`wait_done`, `set_range_fixed`)
6. pandas/numpy 미사용 (32비트 휠 부재 위험) — 실제로 사용 안 함

---

## 9. 미해결 / 확인 필요 항목

| # | 항목 | 왜 필요한가 |
|---|---|---|
| 1 | ~~소자 결선 방식~~ | **✅ 해소.** 0절 참고 — 실측 예시 파일로 SMU1=Common, SMU2=Sweep 확인, 기본값 반영함 |
| 2 | ~~BioLED COM 포트~~ | **✅ 무효한 항목이었다(0-12절).** BioLED는 시리얼이 아니라 **USB HID** 장치라 COM 포트가 애초에 안 생긴다. 지금은 포트 설정 없이 연결되며 실기 동작 확인됨 |
| 3 | ~~`RI` vs `RG` 실제 동작~~ | **✅ 해결(0-4절).** ⚠ **예전 결론이 틀렸다.** "이 장비는 RI가 안 된다"가 아니라, 우리가 보낸 **컴플라이언스가 Range보다 커서** RI가 거부한 것이었다(Range 10uA + 컴플라이언스 1mA). 컴플라이언스를 Range 이하로 맞추니 RI가 통과한다 |
| 4 | ~~`LI` 명령 필요 여부~~ | **✅ 해결(0-4절). 필수였다.** 이게 없으면 전압만 돌아오고 **전류가 전부 정확히 0**이 된다. 리스트 모드에서 '무엇을 측정할지' 지정하는 명령이라 반드시 보내야 한다 |
| 5 | `ME` 파라미터 2/3/4 정확한 의미 | 현재 `ME1`만 사용. Append 측정을 장비 버퍼 수준에서 하려면 확인 필요 (지금은 PC 쪽에서 누적하므로 불필요) |
| 6 | 파장별 광 세기(%) 실측값 | 파워미터로 측정해 `bioled_presets.json`/`it_config.json`에 등록. 예: 530 nm에서 1 mW = 10.9 % |
| 7 | `IT`/`RS` 명령을 보내는 시점 | 매뉴얼이 "전역 명령"이라고만 하고 페이지 컨텍스트를 명시 안 함. 현재 위치(MD 진입 직전, `_prep_and_apply`)에서 **실기 측정이 정상 동작하므로 문제 없어 보인다.** 다만 매뉴얼로 확인한 건 아니라 항목만 남겨둔다 |
| 8 | ~~Dark 스윕 "0점" 반환~~ | **✅ 해결.** 원인이 둘이었다: ① 채널 이름 6글자 초과(0-7절) → 점 자체가 안 옴, ② `LI` 누락(0-4절) → 점은 오는데 **전류만 전부 0**. 둘 다 고친 뒤 실기에서 정상 수신 확인 |
| 9 | ~~설정 명령이 조용히 실패할 가능성~~ | **✅ 상시 감시 중.** 모든 설정 명령을 `_w_checked()`(전송 직후 상태바이트 확인)로 보내므로, 실패하면 로그에 `⚠ Syntax Error: '...'`로 즉시 드러난다. 현재 실기 로그에서는 안 뜬다 |
| 10 | **I-T 탭 실기 미검증** | I-V는 실기 확인됐지만 **I-T(시간영역)는 아직 한 번도 실기로 안 돌려봤다.** 처음 쓸 때 Dry-run으로 흐름부터 확인할 것. `DO 'T'`(시간 채널) 조회가 안 되면 `DO CHnT` 형태로 바꿔야 할 수 있음 |
| 11 | 컴플라이언스 105% 상한의 근거 | `컴플라이언스 ≤ Range × 1.05` 는 실제 KITE 파일 수치에서 **역산한 추론**이다(0-4절). 매뉴얼 원문으로 확인하면 확정할 수 있다. 100%로 봐도 안전 쪽이라 실무 차이는 거의 없음 |
| 12 | 상태 코드 문자의 정확한 의미 | `DO` 응답 각 점 앞의 1글자(`N` 등). 현재 `N`만 정상으로 간주하고 나머지는 컴플라이언스/오버플로 의심으로 경고. Reference Manual 상태 문자 표와 대조 필요 |

---

## 10. 테스트 순서 (문제 발생 시 이 순서로 좁힐 것)

```powershell
# 1) DLL 연결만 확인 — 가장 낮은 층 (cli_tools 폴더로 이동했음)
py -3.13-32 cli_tools\kxci_dll_test.py
#    기대: ret=1, socket_err=0, "KI4200 V9.1-SP1"

# 2) CLI 단일 스윕 — 명령 시퀀스 확인 (예전 검증된 경로, 여전히 동작)
py -3.13-32 cli_tools\pd_iv.py --test-connection
py -3.13-32 cli_tools\pd_iv.py --start -1 --stop 1 --step 0.05 --compliance 1e-3 --label dark
#    기대: "41 points 수신", cli_tools/iv_data/ 에 CSV 생성
#    ⚠ 반드시 저장소 루트(Kiethly_4200\)에서 실행할 것 — cli_tools 안으로 cd하면
#      iv_data/ 등 상대경로 출력 위치가 달라진다.

# 3) BioLED HID DLL 연결만 확인 (0-12절 신규 — 아직 실기로 한 번도 안 돌려봄)
py -3.13-32 cli_tools\bls_dll_test.py
#    BioLEDController.exe는 완전히 종료한 상태여야 함(독점 점유).
#    기대: "연결된 장치 수: 1", handle>=0, Serial No.에 "04-240807-001" 비슷한 값

# 4) 신규 통합 GUI
py -3.13-32 pd_iv_station.py
#    Dry-run 체크박스를 끄고 "Keithley 연결"부터 눌러 ID 응답 확인 -> 탭1에서
#    SMU 구성을 "4200에 적용" -> 탭2 프리셋 확인 -> 탭3에서 Dark 스윕 1회 시도
#    -> "BioLED 연결" -> 탭3에서 프리셋 하나 등록 후 광전류 스윕 시도
```

**실패 시 진단 순서:** 32비트 확인 → DLL 존재 확인 → KITE 종료·KXCI 실행 확인 →
`ping 192.168.0.200` → `Test-NetConnection -ComputerName 192.168.0.200 -Port 2105`
(BioLED는 네트워크가 아니라 USB이므로 위 ping 확인은 해당 없음 — 대신
BioLEDController.exe 완전 종료 여부, BLS 전원 여부, USB 케이블 데이터선
포함 여부를 확인)

---

## 11. 참고 — 분석 앱(`pd_app`) 쪽 별건 이슈

측정과 무관하지만 기록해 둔다. 기존 분석 앱 코드 리뷰에서 발견한 것:

1. **`transparency` 기본값 불일치** — `figure.py`/`insets.py`는
   `ts.get("transparency", 40)`으로 읽는데 `state.add_file()`이 이 키를 안 넣는다.
   결과적으로 모든 신규 트레이스가 40% 투명으로 렌더링된다.
   `add_file`에 명시하든지 기본값을 0으로 통일할 것.
2. **Range I 통일 검증 부재** — 파싱은 Range I를 표시만 하고 검증하지 않는다.
   `parse_file` 끝에서 Dark 제외 트레이스의 `range_i` 집합 크기가 1보다 크면
   경고를 추가하면, 잘못 측정된 파일을 그래프 그리기 전에 잡을 수 있다.
