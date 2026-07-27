"""센서 시뮬레이션 탭 (EPFS / Heading / SDME).

- 탭별 IP/Port/간격으로 독립 멀티캐스트 송신 (자체 소켓 소유)
- after() 루프로 주기 전송 — 매 tick마다 입력칸을 다시 읽으므로
  필드를 수정하면 다음 전송부터 자동 반영된다.
- UdPbC 토글(기본 OFF): 켜면 UdPbC\\x00(+선택 TAG) 프레이밍, 끄면 순수 $문장.
- 설정/필드값은 sensors_config.json 에 시작 시·종료 시 저장.
"""
from __future__ import annotations

from datetime import datetime
import tkinter as tk
from tkinter import messagebox, ttk

from ..core import MulticastGroup, create_sender, nmea, sensors
from .widgets import LogView

# 문장별 편집 필드 스펙: (attr, 라벨, Entry width)
SENTENCE_SPECS: dict[str, list[tuple[str, str, int]]] = {
    "DTM": [
        ("talker", "Talker", 5), ("datum", "Local datum", 8), ("subdiv", "Subdiv", 5),
        ("lat_off", "Lat off(분)", 10), ("lat_ns", "N/S", 4),
        ("lon_off", "Lon off(분)", 10), ("lon_ew", "E/W", 4),
        ("alt_off", "Alt off(m)", 10), ("ref_datum", "Ref datum", 8),
    ],
    "GGA": [
        ("talker", "Talker", 5), ("utc", "UTC", 11),
        ("lat", "Lat(ddmm.mmmm)", 13), ("lat_ns", "N/S", 4),
        ("lon", "Lon(dddmm.mmmm)", 13), ("lon_ew", "E/W", 4),
        ("quality", "Quality", 7), ("num_sat", "위성수", 6), ("hdop", "HDOP", 6),
        ("alt", "고도(m)", 8), ("geoid", "Geoid(m)", 8),
        ("dgps_age", "DGPS age", 8), ("dgps_id", "기준국ID", 8),
    ],
    "VTG": [
        ("talker", "Talker", 5), ("cog_t", "COG 진(T)", 9), ("cog_m", "COG 자(M)", 9),
        ("sog_n", "SOG(kn)", 9), ("sog_k", "SOG(km/h)", 10), ("mode", "Mode", 5),
    ],
    "THS": [
        ("talker", "Talker", 5), ("heading", "Heading(°)", 10), ("mode", "Mode", 5),
    ],
    "VBW": [
        ("talker", "Talker", 5),
        ("water_long", "대수 종(kn)", 10), ("water_trans", "대수 횡(kn)", 10),
        ("water_status", "대수 St", 6),
        ("ground_long", "대지 종(kn)", 10), ("ground_trans", "대지 횡(kn)", 10),
        ("ground_status", "대지 St", 6),
        ("stern_water_trans", "선미대수 횡", 11), ("stern_water_status", "선미대수 St", 10),
        ("stern_ground_trans", "선미대지 횡", 11), ("stern_ground_status", "선미대지 St", 10),
    ],
}

# 한 줄에 배치할 (라벨+입력칸) 쌍 개수
COLS_PER_ROW = 4

# 숫자 필드 → 상하 화살표(Spinbox) 증분 step. 여기 없으면 일반 텍스트 Entry.
# (utc(hhmmss.ss)는 앞자리 0이 깨지기 쉬워 의도적으로 제외 → 텍스트 입력)
NUMERIC_STEP: dict[str, str] = {
    "lat_off": "0.0001", "lon_off": "0.0001", "alt_off": "0.1",
    "lat": "0.0001", "lon": "0.0001",
    "quality": "1", "num_sat": "1", "hdop": "0.1",
    "alt": "0.1", "geoid": "0.1", "dgps_age": "0.1", "dgps_id": "1",
    "cog_t": "0.1", "cog_m": "0.1", "sog_n": "0.1", "sog_k": "0.1",
    "heading": "0.1",
    "water_long": "0.1", "water_trans": "0.1",
    "ground_long": "0.1", "ground_trans": "0.1",
    "stern_water_trans": "0.1", "stern_ground_trans": "0.1",
}
# 음수 허용 필드 (고도/지오이드/속도 성분 — 후진/좌현). 나머지 숫자 필드는 0 이상.
NEGATIVE_ATTRS = {
    "alt_off", "alt", "geoid",
    "water_long", "water_trans", "ground_long", "ground_trans",
    "stern_water_trans", "stern_ground_trans",
}
# 각도 필드 (0~360 순환).
ANGLE_ATTRS = {"cog_t", "cog_m", "heading"}


def _make_field(parent, attr: str, width: int, value: str):
    """숫자 필드면 Spinbox(상하 화살표), 아니면 Entry 를 만든다."""
    step = NUMERIC_STEP.get(attr)
    if step is None:
        w = ttk.Entry(parent, width=width)
        w.insert(0, value)
        return w
    inc = float(step)
    dec = len(step.split(".")[1]) if "." in step else 0
    if attr in ANGLE_ATTRS:
        lo, hi, wrap = 0.0, 360.0, True
    else:
        lo = -1_000_000.0 if attr in NEGATIVE_ATTRS else 0.0
        hi, wrap = 1_000_000.0, False
    w = ttk.Spinbox(parent, width=width, from_=lo, to=hi,
                    increment=inc, format=f"%.{dec}f", wrap=wrap)
    w.set(value)   # 초기값은 서식 재적용 없이 그대로 (앞자리 0 등 보존)
    return w


class _SentenceBlock:
    """문장 하나의 편집 UI 묶음 (enable 체크 + 필드 Entry들)."""

    def __init__(self, parent, key: str, values: dict, with_enable: bool):
        self.key = key
        self.enable = tk.BooleanVar(value=bool(values.get("_enable", True)))

        title = key if not with_enable else ""
        frame = ttk.LabelFrame(parent, text=title)
        frame.pack(fill="x", padx=6, pady=4)

        if with_enable:
            ttk.Checkbutton(frame, text=f"{key} 전송", variable=self.enable)\
                .grid(row=0, column=0, columnspan=COLS_PER_ROW * 2, sticky="w",
                      padx=4, pady=(2, 4))
        base_row = 1 if with_enable else 0

        self.entries: dict[str, ttk.Widget] = {}
        for i, (attr, label, width) in enumerate(SENTENCE_SPECS[key]):
            r, c = divmod(i, COLS_PER_ROW)
            ttk.Label(frame, text=label).grid(
                row=base_row + r, column=c * 2, sticky="e", padx=(6, 2), pady=2)
            e = _make_field(frame, attr, width, str(values.get(attr, "")))
            e.grid(row=base_row + r, column=c * 2 + 1, sticky="w", padx=(0, 8), pady=2)
            self.entries[attr] = e

    def read(self):
        """현재 입력칸 값으로 문장 데이터클래스 인스턴스를 만든다."""
        return sensors.sentence_from_dict(
            self.key, {a: e.get() for a, e in self.entries.items()})

    def to_dict(self) -> dict:
        d = {a: e.get() for a, e in self.entries.items()}
        d["_enable"] = self.enable.get()
        return d


class SensorTab(ttk.Frame):
    """센서 탭 공통 베이스. 서브클래스는 config_key / 문장 키 목록만 지정."""

    config_key: str = ""
    sentence_keys: list[str] = []

    def __init__(self, master):
        super().__init__(master)
        self._cfg_all = sensors.load_config()
        self._cfg = self._cfg_all[self.config_key]
        self._running = False
        self._after_id: str | None = None
        self._sock = None

        self._build_topbar()
        self._build_sentences()

        ttk.Label(self, text="송신 로그").pack(anchor="w", padx=8)
        self._log = LogView(self)
        self._log.pack(fill="both", expand=True, padx=8, pady=4)

    # --- UI ---------------------------------------------------------------
    def _build_topbar(self) -> None:
        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=8, pady=(8, 2))

        ttk.Label(bar, text="IP:").pack(side="left")
        self._ip = ttk.Entry(bar, width=15)
        self._ip.insert(0, str(self._cfg["ip"]))
        self._ip.pack(side="left", padx=(2, 8))

        ttk.Label(bar, text="Port:").pack(side="left")
        self._port = ttk.Entry(bar, width=7)
        self._port.insert(0, str(self._cfg["port"]))
        self._port.pack(side="left", padx=(2, 8))

        ttk.Label(bar, text="iface:").pack(side="left")
        self._iface = ttk.Entry(bar, width=13)
        self._iface.insert(0, str(self._cfg["iface"]))
        self._iface.pack(side="left", padx=(2, 8))

        ttk.Label(bar, text="간격(ms):").pack(side="left")
        self._interval = ttk.Entry(bar, width=7)
        self._interval.insert(0, str(self._cfg["interval_ms"]))
        self._interval.pack(side="left", padx=(2, 8))

        bar2 = ttk.Frame(self)
        bar2.pack(fill="x", padx=8, pady=(0, 4))
        self._udpbc = tk.BooleanVar(value=bool(self._cfg["udpbc"]))
        ttk.Checkbutton(bar2, text="UdPbC 헤더", variable=self._udpbc,
                        command=self._sync_tag_state).pack(side="left")
        ttk.Label(bar2, text="TAG본문(UdPbC ON):").pack(side="left", padx=(8, 2))
        self._tag = ttk.Entry(bar2, width=30)
        self._tag.insert(0, str(self._cfg["tag"]))
        self._tag.pack(side="left", padx=(0, 8))

        self._btn = ttk.Button(bar2, text="전송 시작", command=self._toggle)
        self._btn.pack(side="left", padx=(8, 4))
        ttk.Button(bar2, text="한 번 보내기", command=self._send_once).pack(side="left")
        ttk.Button(bar2, text="설정 저장", command=self._save_config).pack(side="left", padx=4)
        self._sync_tag_state()

    def _build_sentences(self) -> None:
        wrap = ttk.Frame(self)
        wrap.pack(fill="x", padx=4, pady=2)
        with_enable = len(self.sentence_keys) > 1
        self._blocks: list[_SentenceBlock] = []
        for key in self.sentence_keys:
            values = self._cfg["sentences"].get(key, {})
            self._blocks.append(_SentenceBlock(wrap, key, values, with_enable))

    def _sync_tag_state(self) -> None:
        self._tag.configure(state="normal" if self._udpbc.get() else "disabled")

    # --- 프레이밍 / 송신 --------------------------------------------------
    def _frame(self, body: str) -> bytes:
        """문장 본문 → 전송 바이트열 (UdPbC 토글에 따라)."""
        if self._udpbc.get():
            tag = self._tag.get().strip()
            if tag:
                return nmea.build_datagram(tag, body)
            return nmea.PREFIX + (nmea.build_sentence(body) + "\r\n").encode("ascii")
        return (nmea.build_sentence(body) + "\r\n").encode("ascii")

    def _active_blocks(self) -> list[_SentenceBlock]:
        return [b for b in self._blocks if b.enable.get()]

    def _build_datagrams(self) -> list[bytes]:
        return [self._frame(b.read().body()) for b in self._active_blocks()]

    def _collect_warnings(self) -> list[str]:
        w: list[str] = []
        for b in self._active_blocks():
            w.extend(b.read().warnings())
        return w

    def _dest(self) -> tuple[str, int]:
        return (self._ip.get().strip(), int(self._port.get()))

    def _toggle(self) -> None:
        if self._running:
            self._stop()
        else:
            self._start()

    def _start(self) -> None:
        try:
            port = int(self._port.get())
            interval = int(self._interval.get())
            ttl = int(self._cfg.get("ttl", 1))
        except ValueError:
            messagebox.showerror("입력 오류", "Port·간격은 정수여야 합니다.")
            return
        if interval <= 0:
            messagebox.showerror("입력 오류", "간격(ms)은 1 이상이어야 합니다.")
            return
        if not self._active_blocks():
            messagebox.showinfo("알림", "전송할 문장이 없습니다. 문장을 체크하세요.")
            return

        warns = self._collect_warnings()
        if warns:
            msg = "\n".join("• " + w for w in warns) + "\n\n그래도 전송을 시작할까요?"
            if not messagebox.askyesno("규격 경고", msg):
                return

        ip = self._ip.get().strip()
        iface = self._iface.get().strip()
        try:
            self._sock = create_sender(
                MulticastGroup(self.config_key, ip, port, iface, ttl))
        except OSError as exc:
            messagebox.showerror("소켓 오류", str(exc))
            return

        self._save_config()
        self._running = True
        self._interval_ms = interval
        self._btn.configure(text="전송 중지")
        self._set_inputs_state("disabled")
        self._tick()

    def _stop(self) -> None:
        self._running = False
        if self._after_id is not None:
            self.after_cancel(self._after_id)
            self._after_id = None
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        self._btn.configure(text="전송 시작")
        self._set_inputs_state("normal")

    def _set_inputs_state(self, state: str) -> None:
        for w in (self._ip, self._port, self._iface, self._interval):
            w.configure(state=state)

    def _tick(self) -> None:
        if not self._running:
            return
        if not self._send_current():
            return  # 오류 시 _send_current 안에서 _stop
        self._after_id = self.after(self._interval_ms, self._tick)

    def _send_once(self) -> None:
        if not self._active_blocks():
            messagebox.showinfo("알림", "전송할 문장이 없습니다. 문장을 체크하세요.")
            return
        temp = self._sock is None
        if temp:
            try:
                self._sock = create_sender(MulticastGroup(
                    self.config_key, self._ip.get().strip(), int(self._port.get()),
                    self._iface.get().strip(), int(self._cfg.get("ttl", 1))))
            except (OSError, ValueError) as exc:
                messagebox.showerror("송신 실패", str(exc))
                return
        self._send_current()
        if temp and self._sock is not None:
            self._sock.close()
            self._sock = None

    def _send_current(self) -> bool:
        """현재 필드값으로 활성 문장들을 1회 송신. 성공 True."""
        try:
            dest = self._dest()
            for data in self._build_datagrams():
                self._sock.sendto(data, dest)
                ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                self._log.append(f"[{ts}] → {dest[0]}:{dest[1]}  {data!r}")
        except (OSError, ValueError) as exc:
            messagebox.showerror("송신 실패", str(exc))
            self._stop()
            return False
        return True

    # --- 설정 -------------------------------------------------------------
    def _gather_config(self) -> None:
        self._cfg["ip"] = self._ip.get().strip()
        try:
            self._cfg["port"] = int(self._port.get())
        except ValueError:
            pass
        self._cfg["iface"] = self._iface.get().strip()
        try:
            self._cfg["interval_ms"] = int(self._interval.get())
        except ValueError:
            pass
        self._cfg["udpbc"] = self._udpbc.get()
        self._cfg["tag"] = self._tag.get()
        for b in self._blocks:
            self._cfg["sentences"][b.key] = b.to_dict()

    def _save_config(self) -> None:
        self._gather_config()
        try:
            sensors.save_config(self._cfg_all)
        except OSError as exc:
            messagebox.showerror("저장 실패", str(exc))

    def shutdown(self) -> None:
        """앱 종료 시 호출: 루프 정지 + 설정 저장."""
        was_running = self._running
        self._stop()
        try:
            self._save_config()
        except Exception:  # noqa: BLE001 - 종료 경로에서는 조용히
            pass
        _ = was_running


class EpfsTab(SensorTab):
    config_key = "epfs"
    sentence_keys = ["DTM", "GGA", "VTG"]


class HeadingTab(SensorTab):
    config_key = "heading"
    sentence_keys = ["THS"]


class SdmeTab(SensorTab):
    config_key = "sdme"
    sentence_keys = ["VBW"]
