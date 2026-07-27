# UDP Multicast 송수신 툴

여러 개의 UDP 멀티캐스트 그룹을 설정하고, 그룹별로 메시지를 송·수신하는 GUI 툴.
표준 라이브러리(tkinter)만 사용하며 별도 설치가 필요 없다.

## 실행

```bash
python main.py
# 또는
python -m mcast
```

## 구조

```
mcast/
├── app.py            # 애플리케이션 조립 (노트북 + 탭 배선)
├── core/             # 네트워킹·도메인 (tkinter 비의존 → 단위테스트 가능)
│   ├── models.py     # MulticastGroup, ReceivedMessage
│   ├── sockets.py    # 수신/송신 소켓 생성 헬퍼
│   ├── engine.py     # MulticastEngine (select 단일 스레드 수신)
│   └── config.py     # JSON 설정 로드/저장
└── ui/               # 프레젠테이션 (탭별)
    ├── widgets.py    # LogView (상한 있는 로그 창)
    ├── config_tab.py # 설정 탭
    ├── send_tab.py   # 송신 탭
    └── receive_tab.py# 수신 탭
```

## 설계 원칙

- **의존성 단방향**: `ui → core`. 코어는 tkinter 를 import 하지 않아 헤드리스 테스트가 가능하다.
- **부하 최소화**: 수신은 `select()` 기반 단일 스레드(그룹당 스레드 X), GUI 는 `after()` 폴링 + thread-safe 큐로 busy-loop 없음.
- **모델 기반 통신**: 계층 간에는 `dataclass`(MulticastGroup / ReceivedMessage) 로 데이터를 주고받는다.

## 탭

| 탭 | 기능 |
|----|------|
| UDP MULTICAST 설정 | 그룹 테이블(이름/IP/포트/인터페이스/TTL/활성) 관리, 저장, 시작/정지 |
| 송신 메시지 | 활성 그룹 선택 후 메시지 송신, 송신 로그 |
| 수신 메시지 | 그룹 필터로 수신 로그 표시, 일시정지/지우기 |
```
