"""VDR 탭.

- 상단: IP / Port 입력 + 시작/정지
- 좌: 수신한 이미지의 소스정보 테이블
- 우: 선택한 행의 이미지 표시 + [원문][디코딩] 버튼
"""
from __future__ import annotations

import base64
import math
import queue
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from ..core import VdrImage, VdrReceiver, load_groups, vdr

POLL_MS = 150
MAX_ROWS = 100
TARGET_W, TARGET_H = 820, 470

VDR_COLS = ("time", "addr", "loc", "src", "res", "size", "parts")
VDR_HEAD = {"time": "Time", "addr": "Address", "loc": "Location",
            "src": "Source", "res": "Resolution", "size": "Size", "parts": "Packets"}
VDR_W = {"time": 100, "addr": 150, "loc": 70, "src": 80,
         "res": 90, "size": 74, "parts": 62}


class VdrTab(ttk.Frame):
    def __init__(self, master):
        super().__init__(master)
        self._queue: "queue.Queue[VdrImage]" = queue.Queue()
        self._rx = VdrReceiver(self._queue)
        self._images: dict[str, VdrImage] = {}   # tree iid -> VdrImage
        self._photo: tk.PhotoImage | None = None

        self._build_controls()
        self._build_body()
        self.after(POLL_MS, self._drain)

    # --- 상단 컨트롤 ------------------------------------------------------
    def _build_controls(self) -> None:
        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=8, pady=8)
        ttk.Label(bar, text="IP").pack(side="left")
        self._ip = ttk.Entry(bar, width=16)
        self._ip.pack(side="left", padx=(2, 8))
        ttk.Label(bar, text="Port").pack(side="left")
        self._port = ttk.Entry(bar, width=8)
        self._port.pack(side="left", padx=(2, 8))
        self._prefill_from_config()
        self._btn = ttk.Button(bar, text="▶ 시작", command=self._toggle)
        self._btn.pack(side="left", padx=3)
        self._autosave = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar, text="자동 저장", variable=self._autosave).pack(side="left", padx=(10, 0))
        self._saved = 0
        self._status = ttk.Label(bar, text="정지됨", foreground="gray")
        self._status.pack(side="left", padx=10)

    def _prefill_from_config(self) -> None:
        """설정 탭에 저장된 그룹(가능하면 이름에 VDR 포함)의 IP/Port를 미리 채운다."""
        groups = load_groups()
        if not groups:
            return
        g = next((x for x in groups if "VDR" in x.name.upper()), groups[0])
        self._ip.insert(0, g.ip)
        self._port.insert(0, str(g.port))

    # --- 본문(좌 테이블 / 우 이미지) -------------------------------------
    def _build_body(self) -> None:
        paned = ttk.PanedWindow(self, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        # 좌: 소스정보 테이블
        left = ttk.LabelFrame(paned, text="Received images")
        wrap = ttk.Frame(left)
        wrap.pack(fill="both", expand=True, padx=4, pady=4)
        self._tree = ttk.Treeview(wrap, columns=VDR_COLS, show="headings", height=16)
        for c in VDR_COLS:
            self._tree.heading(c, text=VDR_HEAD[c])
            self._tree.column(c, width=VDR_W[c],
                              anchor="w" if c in ("addr",) else "center")
        self._tree.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(wrap, orient="vertical", command=self._tree.yview)
        sb.pack(side="left", fill="y")
        self._tree.configure(yscrollcommand=sb.set)
        self._tree.bind("<<TreeviewSelect>>", lambda _e: self._on_select())
        paned.add(left, weight=1)

        # 우: 이미지 + 버튼
        right = ttk.LabelFrame(paned, text="Image")
        self._canvas_bg = tk.Frame(right, bg="#2b2b2b")
        self._canvas_bg.pack(fill="both", expand=True, padx=4, pady=4)
        self._img_label = tk.Label(self._canvas_bg, bg="#2b2b2b", fg="#cccccc",
                                   text="(행을 선택하면 이미지가 표시됩니다)")
        self._img_label.pack(fill="both", expand=True)

        btnbar = ttk.Frame(right)
        btnbar.pack(fill="x", padx=4, pady=(0, 4))
        ttk.Button(btnbar, text="디코딩", command=self._show_decoded).pack(side="right", padx=3)
        ttk.Button(btnbar, text="원문", command=self._show_raw).pack(side="right", padx=3)
        ttk.Button(btnbar, text="💾 저장", command=self._save_selected).pack(side="right", padx=3)
        paned.add(right, weight=3)

    # --- 시작/정지 --------------------------------------------------------
    def _toggle(self) -> None:
        if self._rx.running:
            self._rx.stop()
            self._btn.config(text="▶ 시작")
            self._status.config(text="정지됨", foreground="gray")
            return
        ip = self._ip.get().strip()
        try:
            port = int(self._port.get().strip())
        except ValueError:
            messagebox.showwarning("입력 오류", "포트는 숫자여야 합니다.")
            return
        if not ip:
            messagebox.showwarning("입력 오류", "IP를 입력하세요.")
            return
        try:
            self._rx.start(ip, port)
        except OSError as exc:
            messagebox.showerror("수신 실패", str(exc))
            return
        self._btn.config(text="■ 정지")
        self._status.config(text=f"수신 중 · {ip}:{port}", foreground="green")

    def shutdown(self) -> None:
        """앱 종료 시 수신 스레드 정리."""
        self._rx.stop()

    # --- 큐 폴링 → 행 추가 ------------------------------------------------
    def _drain(self) -> None:
        added = False
        for _ in range(50):
            try:
                img = self._queue.get_nowait()
            except queue.Empty:
                break
            self._add_row(img)
            if self._autosave.get():
                try:
                    vdr.save_image(img)
                    self._saved += 1
                except OSError:
                    pass
            added = True
        # 상태줄에 실시간으로 패킷 수·이미지 수 표시 (수신 진단용)
        if self._rx.running:
            n = len(self._images)
            extra = f" · 저장 {self._saved}장" if self._autosave.get() else ""
            err = f" · 무시 {self._rx.errors}" if self._rx.errors else ""
            self._status.config(
                text=f"수신 중 · 패킷 {self._rx.packets} · 이미지 {n}장{extra}{err}",
                foreground="green")
        self.after(POLL_MS, self._drain)

    def _add_row(self, img: VdrImage) -> None:
        iid = self._tree.insert("", "end", values=(
            img.timestamp, img.source,
            img.meta.get("Location", ""), img.meta.get("Source", ""),
            f"{img.width}×{img.height}", img.size_text, img.n_parts))
        self._images[iid] = img
        # 최근 MAX_ROWS 장만 유지
        children = self._tree.get_children()
        if len(children) > MAX_ROWS:
            old = children[0]
            self._tree.delete(old)
            self._images.pop(old, None)

    # --- 선택 → 이미지 표시 ----------------------------------------------
    def _current(self) -> VdrImage | None:
        sel = self._tree.selection()
        return self._images.get(sel[0]) if sel else None

    def _on_select(self) -> None:
        img = self._current()
        if img is None:
            return
        try:
            photo = tk.PhotoImage(data=base64.b64encode(img.png).decode("ascii"))
        except tk.TclError as exc:
            self._photo = None
            self._img_label.config(
                image="", text=f"이미지 표시에 Tk 8.6+ 가 필요합니다.\n{exc}")
            return
        factor = 1
        if img.width and img.height:
            factor = max(1, math.ceil(max(img.width / TARGET_W,
                                          img.height / TARGET_H)))
        if factor > 1:
            photo = photo.subsample(factor, factor)
        self._photo = photo                       # 참조 유지 (GC 방지)
        self._img_label.config(image=photo, text="")

    # --- 저장 -------------------------------------------------------------
    def _save_selected(self) -> None:
        img = self._current()
        if img is None:
            messagebox.showinfo("알림", "먼저 좌측에서 이미지를 선택하세요.")
            return
        path = filedialog.asksaveasfilename(
            title="이미지 저장", defaultextension=".png",
            initialfile=img.default_name(),
            initialdir=str(vdr.OUT_DIR),
            filetypes=[("PNG 이미지", "*.png"), ("모든 파일", "*.*")])
        if not path:
            return
        try:
            with open(path, "wb") as fp:
                fp.write(img.png)
        except OSError as exc:
            messagebox.showerror("저장 실패", str(exc))
            return
        messagebox.showinfo("저장 완료", path)

    # --- 원문 / 디코딩 팝업 ----------------------------------------------
    def _show_raw(self) -> None:
        img = self._current()
        if img is None:
            messagebox.showinfo("알림", "먼저 좌측에서 이미지를 선택하세요.")
            return
        raw = b"".join(img.packets)
        self._popup("원문 · RrUdP 패킷 (hex)",
                    _hexdump(raw, cap=131072))

    def _show_decoded(self) -> None:
        img = self._current()
        if img is None:
            messagebox.showinfo("알림", "먼저 좌측에서 이미지를 선택하세요.")
            return
        lines = [
            f"Frame ID   : 0x{img.frame_id:08x}",
            f"Source addr: {img.source}",
            f"Packets    : {img.n_parts}",
            f"PNG size   : {img.size_text} ({len(img.png)} bytes)",
            f"Resolution : {img.width} × {img.height}",
            "",
            "VDRI 메타데이터:",
        ]
        lines += [f"  {k:<13}: {v}" for k, v in img.meta.items()]
        self._popup("디코딩 결과", "\n".join(lines))

    def _popup(self, title: str, text: str) -> None:
        win = tk.Toplevel(self)
        win.title(title)
        win.geometry("760x520")
        mono = ("Menlo", 10)
        t = tk.Text(win, wrap="none", font=mono, padx=10, pady=10)
        ysb = ttk.Scrollbar(win, orient="vertical", command=t.yview)
        xsb = ttk.Scrollbar(win, orient="horizontal", command=t.xview)
        t.configure(yscrollcommand=ysb.set, xscrollcommand=xsb.set)
        ysb.pack(side="right", fill="y")
        xsb.pack(side="bottom", fill="x")
        t.pack(side="left", fill="both", expand=True)
        t.insert("1.0", text)
        t.configure(state="disabled")
        win.transient(self.winfo_toplevel())


def _hexdump(data: bytes, cap: int = 131072) -> str:
    """offset + 16바이트 hex + ascii. cap 바이트까지만."""
    view = data[:cap]
    out = []
    for off in range(0, len(view), 16):
        chunk = view[off:off + 16]
        hexs = " ".join(f"{b:02x}" for b in chunk)
        asci = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        out.append(f"{off:08x}  {hexs:<47}  {asci}")
    if len(data) > cap:
        out.append(f"... ({len(data) - cap} bytes 생략, 총 {len(data)} bytes)")
    return "\n".join(out)
