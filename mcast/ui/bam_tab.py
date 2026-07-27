"""BAM(Bridge Alert Management) 탭.

- 좌: ALC(활성 알람 목록/유실검증)   우: ALF(알람 상세/상태)
- 두 테이블 어느 행이든 선택 → ACK / Silence 로 ACN 명령 송신
- ACN 대상/소스 설정은 상단에서 편집·저장
- 우측 상단 'ⓘ 형식 도움말' → 형식/파싱/열 스키마 팝업
"""
from __future__ import annotations

import queue
import tkinter as tk
from datetime import datetime
from tkinter import font as tkfont
from tkinter import messagebox, ttk

from ..core import (
    AlertStore,
    BamSettings,
    MulticastGroup,
    ReceivedMessage,
    bam,
    create_sender,
    load_bam_settings,
    nmea,
    save_bam_settings,
)
from .widgets import LogView

POLL_MS = 150

ALC_COLS = ("mnem", "id", "inst", "rev")
ALC_HEAD = {"mnem": "Mnemonic", "id": "Alert ID", "inst": "Instance", "rev": "Revision"}
ALF_COLS = ("state", "pri", "cat", "mnem", "id", "inst", "time", "title")
ALF_HEAD = {"state": "State", "pri": "Priority", "cat": "Category",
            "mnem": "Mnemonic", "id": "Alert ID", "inst": "Instance",
            "time": "Time", "title": "Title"}

COL_W = {"rev": 78, "state": 108, "pri": 76, "cat": 82,
         "mnem": 88, "id": 78, "inst": 82, "time": 98, "title": 200}
COL_LEFT = {"title"}

STATE_SHORT = {"V": "unack", "S": "silenced", "A": "ack",
               "O": "transfer", "U": "rect-unack", "N": "normal"}


class BamTab(ttk.Frame):
    def __init__(self, master, recv_queue: "queue.Queue[ReceivedMessage]"):
        super().__init__(master)
        self._queue = recv_queue
        self._store = AlertStore()
        self._settings = load_bam_settings()
        self._seq = 0                       # ACN n: 카운터
        self._selected: tuple[str, str, str] | None = None
        self._dirty = False

        self._build_header()
        self._build_settings()
        self._build_tables()
        self._build_detail()
        self._build_actions()
        self._build_log()
        self._refresh_tables()

        self.after(POLL_MS, self._drain)

    # --- 헤더 (제목 + 도움말) --------------------------------------------
    def _build_header(self) -> None:
        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=8, pady=(8, 0))
        ttk.Label(bar, text="BAM · Bridge Alert Management",
                  font=("", 12, "bold")).pack(side="left")
        ttk.Button(bar, text="ⓘ 형식 도움말", command=self._show_help).pack(side="right")

    # --- 도움말 팝업 (스타일드 Text) -------------------------------------
    def _show_help(self) -> None:
        win = tk.Toplevel(self)
        win.title("ALC / ALF 형식 & 파싱 설명")
        win.geometry("900x700")
        win.minsize(720, 480)
        win.configure(bg="#dfe6ee")

        outer = tk.Frame(win, bg="#dfe6ee")
        outer.pack(fill="both", expand=True, padx=10, pady=10)

        txt = tk.Text(outer, wrap="word", bg="white", fg="#222222",
                      relief="flat", padx=18, pady=14, highlightthickness=0,
                      cursor="arrow")
        sb = ttk.Scrollbar(outer, orient="vertical", command=txt.yview)
        txt.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        txt.pack(side="left", fill="both", expand=True)

        self._configure_help_tags(txt)
        for tag, text in self._help_content():
            txt.insert("end", text + "\n", tag)
        txt.configure(state="disabled")

        ttk.Button(win, text="닫기", command=win.destroy).pack(pady=(0, 10))
        win.transient(self.winfo_toplevel())

    @staticmethod
    def _configure_help_tags(txt: tk.Text) -> None:
        base = tkfont.nametofont("TkDefaultFont").actual()["family"]
        txt.tag_configure("h1", font=(base, 13, "bold"), foreground="white",
                          background="#1f4e79", spacing1=18, spacing3=9,
                          lmargin1=10, lmargin2=10, rmargin=10)
        txt.tag_configure("h2", font=(base, 12, "bold"), foreground="#1f4e79",
                          spacing1=12, spacing3=3, lmargin1=6, lmargin2=6)
        txt.tag_configure("body", font=(base, 11), spacing1=2, spacing3=2,
                          lmargin1=14, lmargin2=14)
        txt.tag_configure("bullet", font=(base, 11), spacing1=1,
                          lmargin1=22, lmargin2=36)
        txt.tag_configure("code", font=("Menlo", 10), foreground="#0b3d2e",
                          background="#eef3f8", spacing1=2, spacing3=2,
                          lmargin1=18, lmargin2=30, rmargin=10)
        txt.tag_configure("field", font=("Menlo", 10), foreground="#2b2b2b",
                          spacing1=0, lmargin1=22, lmargin2=42)
        txt.tag_configure("note", font=(base, 10, "italic"), foreground="#7a5c00",
                          background="#fff4d6", spacing1=8, spacing3=8,
                          lmargin1=14, lmargin2=24, rmargin=14, borderwidth=6,
                          relief="flat")

    @staticmethod
    def _help_content() -> list[tuple[str, str]]:
        b = "\\"        # backslash (TAG 구분자)
        return [
            ("h1", "  IEC 61162-450 전송 프레이밍  "),
            ("body", "한 줄은 세 겹으로 감싸여 있습니다:"),
            ("code", f"UdPbC<NUL>   {b} TAG블록 *cs {b}   $ NMEA문장 *cs"),
            ("bullet", "•  UdPbC + NULL  —  61162-450 전송 헤더"),
            ("bullet", f"•  {b} … *hh {b}  —  TAG 블록 (s:소스, d:대상, g:문장그룹, n:라인번호 …)"),
            ("bullet", "•  $ … *hh  —  실제 NMEA 문장 (ALF / ALC / ACN)"),
            ("bullet", f"•  *hh  —  '{b}'~'*' 또는 '$'~'*' 사이 문자들의 XOR 체크섬"),
            ("note", "x: / z: 는 표준이 아닌 장비 고유(vendor) TAG 입니다 (이 시스템은 값 'Nav').\n"
                     "설정의 '추가 태그(tag_extra)' 가 바로 이것 — ACN 을 보낼 때 받은 그대로 붙여\n"
                     "수신 장비의 네트워크 필터/라우팅을 통과시킵니다. 몰라도 됩니다(미러링이 기본)."),

            ("h1", "  테이블 열(Column) 스키마  "),
            ("h2", "ALC · 활성 알람 목록"),
            ("field", f"{'Mnemonic':<10} 제조사 3글자 코드(알람 네임스페이스). 표준 알람이면 null."),
            ("field", f"{'Alert ID':<10} 알람 종류 식별자(최대 7자리). ~9999 표준 / 10000~ 제조사 고유."),
            ("field", f"{'Instance':<10} 같은 종류의 개별 번호(0~999999). 0 = 그룹 헤더."),
            ("field", f"{'Revision':<10} 리비전 카운터(1~99). 내용이 바뀌면 증가."),
            ("h2", "ALF · 알람 상세/상태"),
            ("field", f"{'State':<10} V unack  S silenced  A ack  O transfer  U rect-unack  N normal"),
            ("field", f"{'Priority':<10} E Emergency   A Alarm   W Warning   C Caution"),
            ("field", f"{'Category':<10} A 원격ACK불가(그래픽 필요)  B 추가정보 불필요  C 브릿지 확인불가"),
            ("field", f"{'Mnem/ID/Inst':<10} (ALC 와 동일)"),
            ("field", f"{'Time':<10} hhmmss.ss (UTC). 마지막 상태 변경 시각."),
            ("field", f"{'Title':<10} 알람 제목(최대 16자). 설명은 하단 '상세:' 줄에 함께 표시."),

            ("h1", "  ALF — 알람 발생/상태 (제목 + 설명, 2문장 1쌍)  "),
            ("code", f"UdPbC<NUL>{b}g:1-2-8,s:EI0001,n:88,x:Nav,z:Nav*74{b}"
                     "$EIALF,2,1,0,105414.14,B,W,V,MRL,9025,81,40,3,GYRO SIG Change*2E"),
            ("code", f"UdPbC<NUL>{b}g:2-2-8,s:EI0001,n:89,x:Nav,z:Nav*76{b}"
                     "$EIALF,2,2,0,,,,,MRL,9025,81,40,3,GYRO sensor signal …*62"),
            ("body", "$EIALF 필드:"),
            ("field", " 1  총 문장수      = 2       8  Mnemonic     = MRL"),
            ("field", " 2  문장 번호      = 1       9  Alert ID     = 9025"),
            ("field", " 3  시퀀스 ID      = 0      10  Instance     = 81"),
            ("field", " 4  Time (UTC)     = 105414.14   11  Revision = 40"),
            ("field", " 5  Category       = B      12  Escalation   = 3"),
            ("field", " 6  Priority       = W      13  Title/설명   = GYRO SIG Change"),
            ("field", " 7  State          = V"),
            ("note", "파싱: (Mnemonic, Alert ID, Instance) = (MRL, 9025, 81) 을 키로\n"
                     "1번 문장(상태·제목) + 2번 문장(설명) 을 합쳐 → ALF 테이블 1행."),

            ("h1", "  ALC — 활성 알람 목록 (30초 주기, 유실 검증)  "),
            ("code", f"UdPbC<NUL>{b}s:EI0001,n:100*hh{b}"
                     "$EIALC,01,01,00,3,MRL,9025,81,40,MRL,3015,16,96,MRL,3062,28,98*hh"),
            ("body", "$EIALC 필드:"),
            ("field", " 1 총 문장수=01   2 문장 번호=01   3 시퀀스 ID=00   4 엔트리 수=3"),
            ("field", " 5~ 엔트리(4필드 묶음): Mnemonic, Alert ID, Instance, Revision"),
            ("field", "      (MRL,9025,81,40)  (MRL,3015,16,96)  (MRL,3062,28,98)"),
            ("note", "각 4필드 묶음 하나가 ALC 테이블 1행. 매 주기 목록 전체 교체.\n"
                     "ALF 를 놓쳐도 여기 있으면 그 알람이 아직 살아있음을 알 수 있습니다."),

            ("h1", "  ACN — 응답 명령 (ACK / Silence 버튼)  "),
            ("body", "선택한 알람의 (Time, Mnemonic, Alert ID, Instance) 를 그대로 미러링:"),
            ("code", f"UdPbC<NUL>{b}s:CA0001,d:EI0001,n:1,x:Nav,z:Nav*7E{b}"
                     "$CAACN,105414.14,MRL,9025,81,A,C*36"),
            ("field", "명령  A=확인(Acknowledge)  S=소음정지  Q=재전송요청  O=책임전가"),
            ("field", "마지막 C = 명령 플래그(필수)"),

            ("h1", "  헷갈리기 쉬운 점  "),
            ("bullet", "•  같은 '0' — ALF Instance 0 = 그룹 헤더 / ACN Instance 0 = 전체 대상"),
            ("bullet", "•  Category A 는 원격 ACK 가 규격상 불가 (이 툴은 경고 후 허용)"),
        ]

    # --- 설정 -------------------------------------------------------------
    def _build_settings(self) -> None:
        f = ttk.LabelFrame(self, text="ACN 설정 (소스/대상)")
        f.pack(fill="x", padx=8, pady=(6, 4))
        self._cfg: dict[str, ttk.Entry] = {}
        specs = [
            ("source_id", "소스 s:", 10), ("dest_id", "대상 d:", 10),
            ("acn_ip", "ACN 그룹 IP", 14), ("acn_port", "포트", 7),
            ("tag_extra", "추가 태그", 14),
        ]
        for i, (key, label, width) in enumerate(specs):
            ttk.Label(f, text=label).grid(row=0, column=i * 2, padx=(6, 2), pady=4, sticky="e")
            e = ttk.Entry(f, width=width)
            e.insert(0, str(getattr(self._settings, key)))
            e.grid(row=0, column=i * 2 + 1, padx=(0, 6), pady=4)
            self._cfg[key] = e
        ttk.Button(f, text="저장", command=self._save_settings).grid(
            row=0, column=len(specs) * 2, padx=6)

    def _current_settings(self) -> BamSettings:
        s = BamSettings()
        for key, entry in self._cfg.items():
            setattr(s, key, entry.get().strip())
        try:
            s.acn_port = int(s.acn_port)
        except ValueError:
            s.acn_port = 0
        return s

    def _save_settings(self) -> None:
        self._settings = self._current_settings()
        try:
            save_bam_settings(self._settings)
            messagebox.showinfo("저장", "ACN 설정을 저장했습니다.")
        except OSError as exc:
            messagebox.showerror("저장 실패", str(exc))

    # --- 테이블 -----------------------------------------------------------
    def _build_tables(self) -> None:
        paned = ttk.PanedWindow(self, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=8, pady=4)

        left = ttk.LabelFrame(paned, text="ALC · 활성 알람 목록 (30초 주기)")
        self.alc = self._make_tree(left, ALC_COLS, ALC_HEAD, "ALC")
        paned.add(left, weight=1)

        right = ttk.LabelFrame(paned, text="ALF · 알람 상세/상태")
        self.alf = self._make_tree(right, ALF_COLS, ALF_HEAD, "ALF")
        paned.add(right, weight=2)

    def _make_tree(self, parent, cols, head, kind) -> ttk.Treeview:
        wrap = ttk.Frame(parent)
        wrap.pack(fill="both", expand=True, padx=4, pady=4)
        tree = ttk.Treeview(wrap, columns=cols, show="headings", height=10)
        for c in cols:
            tree.heading(c, text=head[c])
            anchor = "w" if c in COL_LEFT else "center"
            tree.column(c, width=COL_W.get(c, 72), anchor=anchor,
                        stretch=(c in COL_LEFT))
        tree.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(wrap, orient="vertical", command=tree.yview)
        sb.pack(side="left", fill="y")
        tree.configure(yscrollcommand=sb.set)
        tree.bind("<<TreeviewSelect>>", lambda _e, k=kind: self._on_select(k))
        return tree

    # --- 상세줄 -----------------------------------------------------------
    def _build_detail(self) -> None:
        f = ttk.Frame(self)
        f.pack(fill="x", padx=8, pady=(2, 0))
        ttk.Label(f, text="상세:").pack(side="left")
        self.lbl_detail = ttk.Label(f, text="(선택 없음)", foreground="gray",
                                    anchor="w", wraplength=900, justify="left")
        self.lbl_detail.pack(side="left", fill="x", expand=True)

    # --- 액션 바 ----------------------------------------------------------
    def _build_actions(self) -> None:
        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=8, pady=4)
        self.lbl_target = ttk.Label(bar, text="대상: (선택 없음)", foreground="gray")
        self.lbl_target.pack(side="left")
        ttk.Button(bar, text="🔇 Silence", command=lambda: self._send_acn(bam.CMD_SILENCE)).pack(side="right", padx=3)
        ttk.Button(bar, text="✅ ACK", command=lambda: self._send_acn(bam.CMD_ACK)).pack(side="right", padx=3)

    def _build_log(self) -> None:
        ttk.Label(self, text="ACN 송신 로그").pack(anchor="w", padx=8)
        self._log = LogView(self, height=6)
        self._log.pack(fill="both", expand=False, padx=8, pady=(0, 8))

    # --- 선택 -------------------------------------------------------------
    def _on_select(self, kind: str) -> None:
        tree = self.alc if kind == "ALC" else self.alf
        sel = tree.selection()
        if not sel:
            return
        vals = tree.item(sel[0], "values")
        if kind == "ALC":
            mnem, aid, inst = vals[0], vals[1], vals[2]
        else:
            mnem, aid, inst = vals[3], vals[4], vals[5]
        self._selected = (mnem, aid, inst)
        alert = self._store.get(self._selected)
        cat = f", cat {alert.category}" if alert and alert.category else ""
        src = "ALF" if alert else "ALC(상세없음)"
        self.lbl_target.config(
            text=f"대상: {mnem} / {aid} / {inst}  [{src}{cat}]", foreground="black")
        if alert:
            detail = alert.title
            if alert.description:
                detail += f" — {alert.description}"
            self.lbl_detail.config(text=detail or "(내용 없음)", foreground="black")
        else:
            self.lbl_detail.config(text="(ALF 상세 없음 · ALC에만 존재)", foreground="gray")

    # --- ACN 송신 ---------------------------------------------------------
    def _send_acn(self, command: str) -> None:
        if not self._selected:
            messagebox.showinfo("알림", "먼저 ALC 또는 ALF에서 알람을 선택하세요.")
            return
        mnem, aid, inst = self._selected
        alert = self._store.get(self._selected)
        alert_time = alert.time if alert else ""
        category = alert.category if alert else ""

        warns = bam.acn_warnings(category, inst, command)
        if warns:
            msg = "\n".join("• " + w for w in warns) + "\n\n그래도 전송할까요?"
            if not messagebox.askyesno("규격 경고", msg):
                return

        settings = self._current_settings()
        self._seq += 1
        data = bam.build_acn(mnem, aid, inst, alert_time, command, settings, self._seq)

        try:
            sender = create_sender(MulticastGroup(
                "acn", settings.acn_ip, settings.acn_port,
                settings.acn_iface, settings.acn_ttl))
            sender.sendto(data, (settings.acn_ip, settings.acn_port))
            sender.close()
        except OSError as exc:
            self._seq -= 1
            messagebox.showerror("송신 실패", str(exc))
            return

        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        cmd_name = {"A": "ACK", "S": "Silence"}.get(command, command)
        self._log.append(
            f"[{ts}] {cmd_name} → {settings.acn_ip}:{settings.acn_port}  {data!r}")

    # --- 수신 큐 폴링 + 테이블 갱신 ---------------------------------------
    def _drain(self) -> None:
        for _ in range(500):
            try:
                msg = self._queue.get_nowait()
            except queue.Empty:
                break
            dg = nmea.parse_datagram(msg.text)
            if dg and dg.formatter in ("ALF", "ALC"):
                if self._store.feed_datagram(dg):
                    self._dirty = True
        if self._dirty:
            self._refresh_tables()
            self._dirty = False
        self.after(POLL_MS, self._drain)

    def _refresh_tables(self) -> None:
        # ALC
        self.alc.delete(*self.alc.get_children())
        for e in self._store.alc_entries:
            self.alc.insert("", "end", values=(e.mnemonic, e.alert_id, e.instance, e.revision))
        # ALF (ALC와 동일한 기본 행 스타일)
        self.alf.delete(*self.alf.get_children())
        for a in self._store.list_alerts():
            state_txt = f"{a.state} {STATE_SHORT.get(a.state, '')}".strip()
            self.alf.insert("", "end", values=(
                state_txt, a.priority, a.category,
                a.mnemonic, a.alert_id, a.instance, a.time, a.title))
