"""타깃(선박) 시뮬레이션 탭 (Radar=TTM / AIS=VDM).

- 탭별 IP/Port/간격(초)로 독립 멀티캐스트 송신 (자체 소켓 소유)
- 여러 '선박'을 추가/삭제할 수 있고, 선박별 '전송' 체크로 송신 여부 선택
- after() 루프로 주기 전송 — 매 tick마다 각 선박 입력칸을 다시 읽으므로
  값을 수정하면 다음 전송부터 자동 반영된다.
- UdPbC 토글(기본 OFF): 켜면 UdPbC\\x00(+선택 TAG) 프레이밍.
- 설정/선박 목록은 targets_config.json 에 저장.
"""
from __future__ import annotations

from datetime import datetime
import tkinter as tk
from tkinter import messagebox, ttk

from ..core import MulticastGroup, create_sender, nmea, targets
from .sensor_tab import _make_field
from .widgets import LogView, ScrollFrame

COLS_PER_ROW = 4

# 필드 스펙: (attr, 라벨, width). + 숫자 필드 step/음수/각도 맵.
_TTM_SPECS = [
    ("talker", "Talker", 5), ("target_num", "타깃#", 6),
    ("name", "이름", 12), ("status", "상태(L/Q/T)", 8),
    ("distance", "거리", 8), ("bearing", "방위(°)", 8),
    ("bearing_tr", "방위T/R", 6), ("speed", "속력", 8),
    ("course", "침로(°)", 8), ("course_tr", "침로T/R", 6),
    ("cpa", "CPA", 8), ("tcpa", "TCPA(분)", 9),
    ("units", "단위(K/N/S)", 8), ("ref_target", "기준(R)", 6),
    ("acq_type", "획득(A/M/R)", 8), ("utc", "UTC", 11),
]
_TTM_META = {
    "step": {"target_num": "1", "distance": "0.1", "bearing": "0.1",
             "speed": "0.1", "course": "0.1", "cpa": "0.1", "tcpa": "0.1"},
    "neg": {"tcpa"}, "ang": {"bearing", "course"},
}

_VDM_SPECS = [
    ("talker", "Talker", 5), ("channel", "채널(A/B)", 7),
    ("mmsi", "MMSI", 11), ("nav_status", "항행상태", 8),
    ("sog", "SOG(kn)", 8), ("cog", "COG(°)", 8),
    ("heading", "선수(°)", 8), ("rot", "ROT(raw)", 8),
    ("lon", "경도(°)", 12), ("lat", "위도(°)", 12),
    ("pos_accuracy", "정확도", 7), ("timestamp", "초", 6),
    ("maneuver", "기동", 6), ("raim", "RAIM", 6),
]
_VDM_META = {
    "step": {"mmsi": "1", "nav_status": "1", "rot": "1", "sog": "0.1",
             "pos_accuracy": "1", "lon": "0.0001", "lat": "0.0001",
             "cog": "0.1", "heading": "1", "timestamp": "1",
             "maneuver": "1", "raim": "1"},
    "neg": {"lon", "lat"}, "ang": {"cog", "heading"},
}

SPEC = {"radar": (_TTM_SPECS, _TTM_META), "ais": (_VDM_SPECS, _VDM_META)}


class _ShipBlock:
    """선박 하나의 편집 UI (전송 체크 + 삭제 버튼 + 필드들)."""

    def __init__(self, parent, kind: str, values: dict, on_remove):
        self.kind = kind
        self.enable = tk.BooleanVar(value=bool(values.get("_enable", True)))
        self.frame = ttk.LabelFrame(parent, text="선박")
        self.frame.pack(fill="x", padx=6, pady=4)

        head = ttk.Frame(self.frame)
        head.pack(fill="x")
        ttk.Checkbutton(head, text="전송", variable=self.enable).pack(side="left", padx=4, pady=2)
        ttk.Button(head, text="삭제", width=6,
                   command=lambda: on_remove(self)).pack(side="right", padx=4)

        grid = ttk.Frame(self.frame)
        grid.pack(fill="x", padx=2, pady=2)
        specs, meta = SPEC[kind]
        self.entries: dict[str, ttk.Widget] = {}
        for i, (attr, label, width) in enumerate(specs):
            r, c = divmod(i, COLS_PER_ROW)
            ttk.Label(grid, text=label).grid(
                row=r, column=c * 2, sticky="e", padx=(6, 2), pady=2)
            e = _make_field(grid, attr, width, str(values.get(attr, "")),
                            numeric_step=meta["step"], negative=meta["neg"],
                            angle=meta["ang"])
            e.grid(row=r, column=c * 2 + 1, sticky="w", padx=(0, 8), pady=2)
            self.entries[attr] = e

    def set_title(self, title: str) -> None:
        self.frame.configure(text=title)

    def read(self):
        return targets.ship_from_dict(
            self.kind, {a: e.get() for a, e in self.entries.items()})

    def to_dict(self) -> dict:
        d = {a: e.get() for a, e in self.entries.items()}
        d["_enable"] = self.enable.get()
        return d

    def destroy(self) -> None:
        self.frame.destroy()


class TargetTab(ttk.Frame):
    """Radar/AIS 공통 베이스. 서브클래스는 config_key/kind/title_word 만 지정."""

    config_key = ""     # "radar" / "ais"
    kind = ""           # SPEC 키 (config_key 와 동일)
    title_word = "선박"

    def __init__(self, master):
        super().__init__(master)
        self._cfg_all = targets.load_config()
        self._cfg = self._cfg_all[self.config_key]
        self._running = False
        self._after_id: str | None = None
        self._sock = None

        self._build_topbar()
        self._build_shiparea()

        ttk.Label(self, text="송신 로그").pack(anchor="w", padx=8)
        self._log = LogView(self, height=6)
        self._log.pack(fill="x", padx=8, pady=4)

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
        ttk.Label(bar, text="간격(초):").pack(side="left")
        self._interval = ttk.Entry(bar, width=6)
        self._interval.insert(0, str(self._cfg["interval_sec"]))
        self._interval.pack(side="left", padx=(2, 8))

        bar2 = ttk.Frame(self)
        bar2.pack(fill="x", padx=8, pady=(0, 4))
        self._udpbc = tk.BooleanVar(value=bool(self._cfg["udpbc"]))
        ttk.Checkbutton(bar2, text="UdPbC 헤더", variable=self._udpbc,
                        command=self._sync_tag_state).pack(side="left")
        ttk.Label(bar2, text="TAG본문(UdPbC ON):").pack(side="left", padx=(8, 2))
        self._tag = ttk.Entry(bar2, width=26)
        self._tag.insert(0, str(self._cfg["tag"]))
        self._tag.pack(side="left", padx=(0, 8))
        self._btn = ttk.Button(bar2, text="전송 시작", command=self._toggle)
        self._btn.pack(side="left", padx=(8, 4))
        ttk.Button(bar2, text="한 번 보내기", command=self._send_once).pack(side="left")
        ttk.Button(bar2, text="설정 저장", command=self._save_config).pack(side="left", padx=4)
        self._sync_tag_state()

    def _build_shiparea(self) -> None:
        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=8, pady=(2, 0))
        ttk.Button(bar, text=f"+ {self.title_word} 추가",
                   command=lambda: self._add_ship()).pack(side="left")
        self._count = ttk.Label(bar, text="")
        self._count.pack(side="left", padx=8)

        self._scroll = ScrollFrame(self)
        self._scroll.pack(fill="both", expand=True, padx=4, pady=2)

        self._ships: list[_ShipBlock] = []
        for values in self._cfg["ships"]:
            self._add_ship(values)

    def _add_ship(self, values: dict | None = None) -> None:
        if values is None:
            values = {}     # 데이터클래스 기본값으로 새 선박
        block = _ShipBlock(self._scroll.inner, self.kind, values, self._remove_ship)
        self._ships.append(block)
        self._renumber()

    def _remove_ship(self, block: _ShipBlock) -> None:
        block.destroy()
        self._ships.remove(block)
        self._renumber()

    def _renumber(self) -> None:
        for i, b in enumerate(self._ships, 1):
            b.set_title(f"{self.title_word} {i}")
        self._count.configure(
            text=f"총 {len(self._ships)}척 (전송 {sum(b.enable.get() for b in self._ships)}척)")

    def _sync_tag_state(self) -> None:
        self._tag.configure(state="normal" if self._udpbc.get() else "disabled")

    # --- 프레이밍 / 송신 --------------------------------------------------
    def _frame(self, sentence: str) -> bytes:
        """완성된 NMEA 문장 문자열 → 전송 바이트열 (UdPbC 토글에 따라)."""
        if self._udpbc.get():
            tag = self._tag.get().strip()
            head = nmea.PREFIX
            if tag:
                return head + (nmea.build_tag_block(tag) + sentence + "\r\n").encode("ascii")
            return head + (sentence + "\r\n").encode("ascii")
        return (sentence + "\r\n").encode("ascii")

    def _active_ships(self) -> list[_ShipBlock]:
        return [s for s in self._ships if s.enable.get()]

    def _build_datagrams(self) -> list[bytes]:
        return [self._frame(s.read().sentence()) for s in self._active_ships()]

    def _collect_warnings(self) -> list[str]:
        w: list[str] = []
        for s in self._active_ships():
            w.extend(s.read().warnings())
        return w

    def _dest(self) -> tuple[str, int]:
        return (self._ip.get().strip(), int(self._port.get()))

    def _toggle(self) -> None:
        self._stop() if self._running else self._start()

    def _start(self) -> None:
        try:
            port = int(self._port.get())
            interval_ms = int(float(self._interval.get()) * 1000)
            ttl = int(self._cfg.get("ttl", 1))
        except ValueError:
            messagebox.showerror("입력 오류", "Port 는 정수, 간격은 숫자(초)여야 합니다.")
            return
        if interval_ms <= 0:
            messagebox.showerror("입력 오류", "간격(초)은 0보다 커야 합니다.")
            return
        if not self._active_ships():
            messagebox.showinfo("알림", "전송할 선박이 없습니다. '전송'을 체크하거나 선박을 추가하세요.")
            return
        try:
            warns = self._collect_warnings()
        except ValueError as exc:
            messagebox.showerror("입력 오류", f"선박 값에 오류가 있습니다: {exc}")
            return
        if warns:
            msg = "\n".join("• " + w for w in warns) + "\n\n그래도 전송을 시작할까요?"
            if not messagebox.askyesno("규격 경고", msg):
                return

        try:
            self._sock = create_sender(MulticastGroup(
                self.config_key, self._ip.get().strip(), port,
                self._iface.get().strip(), ttl))
        except OSError as exc:
            messagebox.showerror("소켓 오류", str(exc))
            return

        self._save_config()
        self._running = True
        self._interval_ms = interval_ms
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
            return
        self._after_id = self.after(self._interval_ms, self._tick)

    def _send_once(self) -> None:
        if not self._active_ships():
            messagebox.showinfo("알림", "전송할 선박이 없습니다.")
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
            self._cfg["interval_sec"] = float(self._interval.get())
        except ValueError:
            pass
        self._cfg["udpbc"] = self._udpbc.get()
        self._cfg["tag"] = self._tag.get()
        self._cfg["ships"] = [b.to_dict() for b in self._ships]

    def _save_config(self) -> None:
        self._gather_config()
        try:
            targets.save_config(self._cfg_all)
        except OSError as exc:
            messagebox.showerror("저장 실패", str(exc))

    def shutdown(self) -> None:
        self._stop()
        try:
            self._save_config()
        except Exception:  # noqa: BLE001 - 종료 경로에서는 조용히
            pass


class RadarTab(TargetTab):
    config_key = "radar"
    kind = "radar"
    title_word = "타깃"


class AisTab(TargetTab):
    config_key = "ais"
    kind = "ais"
    title_word = "선박"
