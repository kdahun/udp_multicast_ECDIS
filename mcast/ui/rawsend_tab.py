"""HEX/바이너리 원시 송신 탭.

NMEA 문장이 아닌 '바이트열 그대로'를 멀티캐스트로 쏜다. 송신 메시지 탭과의 차이:

- 입력을 hex 로 해석해 **바이너리로** 보낸다 (송신 탭은 입력을 UTF-8 텍스트로 보냄).
- 데이터를 **여러 데이터그램으로 분할**해 순차 전송한다 (송신 탭은 1회 sendto).
- 바이너리 파일을 그대로 보낼 수 있다 (파일당 1 데이터그램, 또는 파일 내부 분할).
- 로그에 **실제 sendto 한 바이트 수**를 조각별로 찍는다 → 수신측이 다른 크기를
  보고한다면 그건 수신측 버퍼/파서 문제로 바로 구분된다.

자체 소켓을 소유하므로 '설정' 탭에서 엔진을 시작하지 않아도 동작한다.
설정은 rawsend_config.json 에 저장.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from ..core import MulticastGroup, create_sender, rawsend
from .widgets import LogView

# 로그 1줄이 너무 길어지지 않게 조각 앞부분만 보여줄 바이트 수
HEAD_BYTES = 16


class RawSendTab(ttk.Frame):
    """hex/파일 → 바이너리 데이터그램 분할 송신."""

    def __init__(self, master):
        super().__init__(master)
        self._cfg = rawsend.load_config()
        self._files: list[Path] = []
        self._sock = None
        self._after_id: str | None = None
        self._sending = False
        self._pending: list[bytes] = []
        self._cursor = 0
        self._sent_bytes = 0

        self._build_topbar()
        self._build_input()

        ttk.Label(self, text="송신 로그").pack(anchor="w", padx=8)
        self._log = LogView(self, height=8)
        self._log.pack(fill="both", expand=True, padx=8, pady=(0, 6))

        self._sync_states()

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

        ttk.Label(bar, text="TTL:").pack(side="left")
        self._ttl = ttk.Spinbox(bar, width=4, from_=1, to=255, increment=1)
        self._ttl.set(str(self._cfg["ttl"]))
        self._ttl.pack(side="left", padx=(2, 8))

        # --- 입력 소스 ---
        src = ttk.LabelFrame(self, text="입력 소스")
        src.pack(fill="x", padx=8, pady=4)
        self._source = tk.StringVar(value="hex")
        ttk.Radiobutton(src, text="HEX 텍스트", value="hex", variable=self._source,
                        command=self._sync_states).pack(side="left", padx=(6, 10))
        ttk.Radiobutton(src, text="바이너리 파일", value="file", variable=self._source,
                        command=self._sync_states).pack(side="left")
        self._pick_btn = ttk.Button(src, text="파일 선택…", command=self._pick_files)
        self._pick_btn.pack(side="left", padx=6)
        self._files_label = ttk.Label(src, text="(선택된 파일 없음)")
        self._files_label.pack(side="left", padx=4)

        # --- 분할 방식 ---
        sp = ttk.LabelFrame(self, text="데이터그램 분할 (조각 1개 = UDP 데이터그램 1개)")
        sp.pack(fill="x", padx=8, pady=4)
        self._mode = tk.StringVar(value=str(self._cfg["mode"]))
        ttk.Radiobutton(sp, text="분할 없음", value="none", variable=self._mode,
                        command=self._sync_states).grid(row=0, column=0, sticky="w",
                                                        padx=6, pady=2)
        ttk.Radiobutton(sp, text="고정 크기", value="fixed", variable=self._mode,
                        command=self._sync_states).grid(row=0, column=1, sticky="w",
                                                        padx=6, pady=2)
        self._chunk = ttk.Spinbox(sp, width=7, from_=1, to=rawsend.UDP_MAX_PAYLOAD,
                                  increment=1)
        self._chunk.set(str(self._cfg["chunk_size"]))
        self._chunk.grid(row=0, column=2, sticky="w")
        ttk.Label(sp, text=f"B (MTU 1500 기준 최대 {rawsend.MTU_PAYLOAD})")\
            .grid(row=0, column=3, sticky="w", padx=(2, 10))

        ttk.Radiobutton(sp, text="줄 단위 (HEX 1줄 = 1개)", value="lines",
                        variable=self._mode, command=self._sync_states)\
            .grid(row=1, column=0, columnspan=2, sticky="w", padx=6, pady=2)
        ttk.Radiobutton(sp, text="마커마다", value="marker", variable=self._mode,
                        command=self._sync_states)\
            .grid(row=1, column=1, sticky="w", padx=6, pady=2)
        self._marker = ttk.Entry(sp, width=16)
        self._marker.insert(0, str(self._cfg["marker"]))
        self._marker.grid(row=1, column=2, sticky="w")
        ttk.Label(sp, text="(hex, 예: 556450624300 = UdPbC\\x00)")\
            .grid(row=1, column=3, sticky="w", padx=(2, 10))

        # --- 실행 ---
        run = ttk.Frame(self)
        run.pack(fill="x", padx=8, pady=(2, 4))
        ttk.Label(run, text="조각 간격(ms):").pack(side="left")
        self._gap = ttk.Spinbox(run, width=6, from_=0, to=10000, increment=1)
        self._gap.set(str(self._cfg["gap_ms"]))
        self._gap.pack(side="left", padx=(2, 10))

        ttk.Label(run, text="반복:").pack(side="left")
        self._repeat = ttk.Spinbox(run, width=5, from_=1, to=10000, increment=1)
        self._repeat.set(str(self._cfg["repeat"]))
        self._repeat.pack(side="left", padx=(2, 10))

        ttk.Button(run, text="조각 확인", command=self._preview).pack(side="left")
        self._send_btn = ttk.Button(run, text="송신", command=self._toggle_send)
        self._send_btn.pack(side="left", padx=4)
        ttk.Button(run, text="설정 저장", command=self._save_config).pack(side="left", padx=4)
        ttk.Button(run, text="로그 지우기", command=self._log_clear).pack(side="left")

    def _build_input(self) -> None:
        ttk.Label(
            self,
            text="HEX 입력 (공백·줄바꿈·0x·: - , 는 무시 — 덤프 붙여넣기 그대로 가능)",
        ).pack(anchor="w", padx=8)
        wrap = ttk.Frame(self)
        wrap.pack(fill="both", expand=True, padx=8, pady=(0, 4))
        self._hex = tk.Text(wrap, height=10, wrap="char", undo=True)
        self._hex.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(wrap, orient="vertical", command=self._hex.yview)
        sb.pack(side="left", fill="y")
        self._hex.configure(yscrollcommand=sb.set)
        if self._cfg["hex"]:
            self._hex.insert("1.0", str(self._cfg["hex"]))

    def _sync_states(self) -> None:
        """입력 소스/분할 방식에 따라 관련 위젯만 활성화한다."""
        is_hex = self._source.get() == "hex"
        self._hex.configure(state="normal" if is_hex else "disabled")
        self._pick_btn.configure(state="disabled" if is_hex else "normal")
        mode = self._mode.get()
        self._chunk.configure(state="normal" if mode == "fixed" else "disabled")
        self._marker.configure(state="normal" if mode == "marker" else "disabled")

    def _log_clear(self) -> None:
        self._log.clear()

    def _pick_files(self) -> None:
        paths = filedialog.askopenfilenames(
            title="보낼 바이너리 파일 선택 (여러 개 가능 — 선택 순서대로 전송)")
        if not paths:
            return
        self._files = [Path(p) for p in paths]
        total = sum(p.stat().st_size for p in self._files if p.exists())
        names = ", ".join(p.name for p in self._files[:3])
        more = f" 외 {len(self._files) - 3}개" if len(self._files) > 3 else ""
        self._files_label.configure(text=f"{names}{more}  (합계 {total:,} B)")

    # --- 조각 만들기 ------------------------------------------------------
    @staticmethod
    def _int(widget, label: str, minimum: int) -> int:
        """숫자 입력칸을 읽는다. 비정상 입력은 한글 메시지로 바꿔 던진다."""
        raw = widget.get().strip()
        try:
            value = int(raw)
        except ValueError:
            raise ValueError(f"{label} 는 정수여야 합니다 (입력값: '{raw}').") from None
        if value < minimum:
            raise ValueError(f"{label} 는 {minimum} 이상이어야 합니다 (입력값: {value}).")
        return value

    def _marker_bytes(self) -> bytes:
        return rawsend.parse_hex(self._marker.get())

    def _split(self, data: bytes) -> list[bytes]:
        """분할 방식에 따라 바이트열 하나를 조각 리스트로 만든다."""
        mode = self._mode.get()
        if mode == "fixed":
            return rawsend.split_fixed(data, self._int(self._chunk, "조각 크기", 1))
        if mode == "marker":
            return rawsend.split_marker(data, self._marker_bytes())
        return [data]          # none

    def _build_chunks(self) -> list[bytes]:
        """현재 입력으로 보낼 데이터그램 목록을 만든다. 실패 시 ValueError."""
        mode = self._mode.get()
        if self._source.get() == "file":
            if not self._files:
                raise ValueError("보낼 파일을 선택하세요.")
            if mode == "lines":
                raise ValueError("'줄 단위' 분할은 HEX 텍스트 입력에만 쓸 수 있습니다.")
            out: list[bytes] = []
            for path in self._files:
                try:
                    data = path.read_bytes()
                except OSError as exc:
                    raise ValueError(f"{path.name} 읽기 실패: {exc}") from exc
                if not data:
                    raise ValueError(f"{path.name} 이 빈 파일입니다.")
                out.extend(self._split(data))
            return out

        text = self._hex.get("1.0", "end-1c")
        if mode == "lines":
            return rawsend.parse_hex_lines(text)
        return self._split(rawsend.parse_hex(text))

    def _dest(self) -> tuple[str, int]:
        ip = self._ip.get().strip()
        if not ip:
            raise ValueError("대상 IP 를 입력하세요.")
        port = self._int(self._port, "Port", 1)
        if port > 65535:
            raise ValueError(f"Port 는 1~65535 범위여야 합니다 (입력값: {port}).")
        return (ip, port)

    # --- 미리보기 ---------------------------------------------------------
    def _preview(self) -> None:
        try:
            chunks = self._build_chunks()
            dest = self._dest()
        except ValueError as exc:
            messagebox.showerror("입력 오류", str(exc))
            return
        total = sum(len(c) for c in chunks)
        self._log.append(
            f"── 조각 확인: {len(chunks)}개 / 합계 {total:,} B  → {dest[0]}:{dest[1]} "
            "(전송 안 함)")
        for i, c in enumerate(chunks[:50], start=1):
            self._log.append(
                f"   #{i}/{len(chunks)}  {len(c):>6,} B  {rawsend.describe(c, HEAD_BYTES)}")
        if len(chunks) > 50:
            self._log.append(f"   … 이하 {len(chunks) - 50}개 생략")
        for w in rawsend.size_warnings(chunks):
            self._log.append(f"   [경고] {w}")

    # --- 송신 -------------------------------------------------------------
    def _toggle_send(self) -> None:
        if self._sending:
            self._finish("사용자 중지")
        else:
            self._start_send()

    def _start_send(self) -> None:
        try:
            chunks = self._build_chunks()
            dest = self._dest()
            gap = self._int(self._gap, "조각 간격(ms)", 0)
            repeat = self._int(self._repeat, "반복", 1)
            ttl = self._int(self._ttl, "TTL", 1)
        except ValueError as exc:
            messagebox.showerror("입력 오류", str(exc))
            return

        warns = rawsend.size_warnings(chunks)
        if warns:
            msg = "\n".join("• " + w for w in warns) + "\n\n그래도 보낼까요?"
            if not messagebox.askyesno("크기 경고", msg):
                return

        try:
            self._sock = create_sender(
                MulticastGroup("rawsend", dest[0], dest[1],
                               self._iface.get().strip(), ttl))
        except (OSError, ValueError) as exc:
            messagebox.showerror("소켓 오류", str(exc))
            return

        self._save_config()
        self._pending = chunks * repeat
        self._cursor = 0
        self._sent_bytes = 0
        self._sending = True
        self._gap_ms = gap
        self._dest_cache = dest
        self._send_btn.configure(text="중지")
        total = sum(len(c) for c in self._pending)
        rep = f" ×{repeat}회" if repeat > 1 else ""
        self._log.append(
            f"── 송신 시작: 데이터그램 {len(self._pending)}개{rep} / 합계 {total:,} B "
            f"→ {dest[0]}:{dest[1]}  (간격 {gap}ms)")
        self._pump()

    def _pump(self) -> None:
        """조각 하나를 보내고, 간격만큼 쉬었다가 다음 조각으로 넘어간다.

        after() 체인으로 돌려 GUI 가 멈추지 않게 한다(조각이 수천 개여도 반응 유지).
        """
        self._after_id = None
        if not self._sending or self._cursor >= len(self._pending):
            self._finish("완료")
            return
        data = self._pending[self._cursor]
        try:
            n = self._sock.sendto(data, self._dest_cache)
        except OSError as exc:
            self._log.append(f"   [실패] #{self._cursor + 1}: {exc}")
            self._finish(f"송신 실패 ({exc})")
            messagebox.showerror("송신 실패", f"#{self._cursor + 1} 조각: {exc}")
            return
        self._cursor += 1
        self._sent_bytes += n
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        short = "" if n == len(data) else f"  [주의] 요청 {len(data)}B 중 {n}B 만 전송"
        self._log.append(
            f"[{ts}] #{self._cursor}/{len(self._pending)}  {n:>6,} B 전송  "
            f"{rawsend.describe(data, HEAD_BYTES)}{short}")
        if self._cursor >= len(self._pending):
            self._finish("완료")
            return
        self._after_id = self.after(max(self._gap_ms, 0), self._pump)

    def _finish(self, reason: str) -> None:
        if self._after_id is not None:
            self.after_cancel(self._after_id)
            self._after_id = None
        was_sending = self._sending
        self._sending = False
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        self._send_btn.configure(text="송신")
        if was_sending:
            self._log.append(
                f"── {reason}: {self._cursor}/{len(self._pending)}개, "
                f"{self._sent_bytes:,} B 전송")

    # --- 설정 -------------------------------------------------------------
    def _gather_config(self) -> None:
        self._cfg["ip"] = self._ip.get().strip()
        for key, widget in (("port", self._port), ("ttl", self._ttl),
                            ("chunk_size", self._chunk), ("gap_ms", self._gap),
                            ("repeat", self._repeat)):
            try:
                self._cfg[key] = int(widget.get())
            except ValueError:
                pass
        self._cfg["iface"] = self._iface.get().strip()
        self._cfg["mode"] = self._mode.get()
        self._cfg["marker"] = self._marker.get().strip()
        self._cfg["hex"] = self._hex.get("1.0", "end-1c")

    def _save_config(self) -> None:
        self._gather_config()
        try:
            rawsend.save_config(self._cfg)
        except OSError as exc:
            messagebox.showerror("저장 실패", str(exc))

    def shutdown(self) -> None:
        """앱 종료 시 호출: 전송 중단 + 설정 저장."""
        self._finish("종료")
        try:
            self._save_config()
        except Exception:  # noqa: BLE001 - 종료 경로에서는 조용히
            pass
