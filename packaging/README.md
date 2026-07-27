# 실행 파일 빌드 (macOS / Windows)

이 앱은 **순수 Python 표준 라이브러리 + tkinter** 로만 되어 있어 런타임 의존성이 없다.
[PyInstaller](https://pyinstaller.org) 로 각 OS에서 단일 실행 파일을 만든다.

> **중요:** PyInstaller 는 교차 컴파일을 지원하지 않는다.
> **Windows .exe 는 Windows 에서, macOS .app 은 macOS 에서** 각각 빌드해야 한다.
> 한 곳에서 둘 다 뽑으려면 아래 *GitHub Actions* 를 쓴다.

## macOS

```bash
bash packaging/build_macos.sh
# 결과: dist/UDP-Multicast-ECDIS.app
open dist/UDP-Multicast-ECDIS.app
```

서명이 없으므로 처음 실행 시 Gatekeeper 가 막으면: 우클릭 → 열기, 또는
시스템 설정 → 개인정보 보호 및 보안 → "확인 없이 열기".

## Windows

```bat
packaging\build_windows.bat
REM 결과: dist\UDP-Multicast-ECDIS.exe  (단일 파일)
```

Windows 는 **onefile(단일 exe)** 로 빌드된다 → **이 `.exe` 파일 하나만** 다른 PC로
복사하면 그대로 실행된다(별도 폴더·설치 불필요).

SmartScreen 경고가 뜨면 "추가 정보 → 실행"을 누른다(코드 서명 시 사라짐).
Windows Defender 가 미서명 onefile 을 오탐할 수 있는데, 이 경우 예외 처리하거나
코드 서명을 붙이면 된다.

## GitHub Actions (양 OS 동시 빌드)

`.github/workflows/build.yml` 이 macOS·Windows 러너에서 각각 빌드한다.

- **수동 실행:** Actions 탭 → *build-executables* → *Run workflow*
- **태그 빌드:** `git tag v1.0.0 && git push --tags`
- 완료 후 각 실행 파일이 **Artifacts** 로 첨부된다
  (`UDP-Multicast-ECDIS-macos`, `UDP-Multicast-ECDIS-windows`).

## 설정 저장 방식 (중요)

소스로 실행할 때와 번들 실행 파일일 때 저장 위치가 다르다 — `mcast/core/paths.py` 참고.

| 실행 형태 | 설정/이미지 저장 위치 |
|---|---|
| 소스(`python main.py`) | 저장소 루트 (기존과 동일) |
| **번들 .exe(Windows) / .app(macOS)** | **사용자 데이터 폴더** |

번들 실행 시 사용자 데이터 폴더:

- macOS: `~/Library/Application Support/UDP-Multicast-ECDIS/`
- Windows: `%APPDATA%\UDP-Multicast-ECDIS\`

여기에 `mc_config.json`, `bam_config.json`, `sensors_config.json`, `vdr_images/` 가 저장된다.
`mc_config.json` · `bam_config.json` 의 **기본값은 번들에 포함**되어 첫 실행 시 자동 복사되고,
`sensors_config.json` 은 코드 기본값(`sensors.default_config()`)으로 첫 실행 시 생성된다.

> 번들 내부(읽기전용/임시)에 저장하지 않으므로, 실행 파일을 옮기거나 재빌드해도 설정이 유지된다.
