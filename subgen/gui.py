"""Окно Subgen: вкладки «Генерация», «Дорожки», «Модели»."""
import ctypes, os, queue, sys, threading, time
from tkinter import filedialog, messagebox

for _n in ("stdout", "stderr"):  # под pythonw потоков нет, а huggingface/ctranslate2 в них пишут
    if getattr(sys, _n) is None:
        setattr(sys, _n, open(os.devnull, "w", encoding="utf-8"))

import customtkinter as ctk
from tkinterdnd2 import DND_FILES, TkinterDnD

from . import core, i18n, models, tracks
from .i18n import t

ICON = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "subgen.ico")
OK, ERR, WARN, BUSY, MUTED = "#22c55e", "#ef4444", "#f59e0b", "#60a5fa", "gray60"
VIDEO_TYPES = [(t("filetype.video"), " ".join("*" + e for e in sorted(core.VIDEO_EXT)))]
TAB_GEN, TAB_TRACKS, TAB_MODELS = t("tab.gen"), t("tab.tracks"), t("tab.models")
AUTO = t("lang.auto")
DONE = ("done", "done_notr", "error")  # конечные состояния серии
BY_NAME = {v[2]: k for k, v in models.LANGS.items()}  # "Japanese" -> "ja"


def fmt(sec):
    return f"{int(sec) // 60}:{int(sec) % 60:02}"


class Item:
    def __init__(self, path):
        self.path, self.state, self.label = path, "wait", None


class App(ctk.CTk, TkinterDnD.DnDWrapper):
    def __init__(self, paths):
        super().__init__()
        self.TkdndVersion = TkinterDnD._require(self)
        self.title(t("app.title"))
        self.geometry("900x740")
        self.minsize(760, 600)
        self.after(300, self.set_icon)  # customtkinter сам ставит свою иконку через 200 мс
        self.q, self.items, self.known = queue.Queue(), [], set()
        self.job, self.stop, self.warn, self.p0 = None, threading.Event(), False, None
        core.on_log = lambda *a: self.q.put(("log", " ".join(map(str, a))))
        self.report_callback_exception = lambda *e: self.log_text(t("log.window_crash", error=repr(e[1])))

        self.tabs = ctk.CTkTabview(self, corner_radius=12, anchor="nw")
        self.tabs.pack(fill="both", expand=True, padx=14, pady=(6, 14))
        for name in (TAB_GEN, TAB_TRACKS, TAB_MODELS):
            self.tabs.add(name)
        self.tabs._segmented_button.configure(font=ctk.CTkFont(size=14, weight="bold"))
        self.build_gen(self.tabs.tab(TAB_GEN))
        self.build_tracks(self.tabs.tab(TAB_TRACKS))
        self.build_models(self.tabs.tab(TAB_MODELS))
        self.show_cfg()

        self.drop_target_register(DND_FILES)
        self.dnd_bind("<<Drop>>", lambda e: self.on_drop(self.tk.splitlist(e.data)))
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(100, self.poll)
        if not core.FFMPEG:
            self.log_text("!! " + core.NO_FFMPEG)
        if paths:
            self.add(paths)
            self.after(500, self.start)

    def set_icon(self):
        try:
            self.iconbitmap(ICON)
        except Exception:
            pass

    def on_drop(self, paths):
        if self.tabs.get() == TAB_TRACKS:
            vids = core.collect(paths)
            if vids:
                self.open_tracks(vids[0])
        else:
            self.tabs.set(TAB_GEN)
            self.add(paths)

    def busy(self):
        if self.job:
            messagebox.showinfo("Subgen", t("msg.busy"))
        return bool(self.job)

    def run_job(self, target, *args):
        self.job, self.job_target = threading.Thread(target=target, args=args, daemon=True), target
        self.job.start()
        self.refresh_buttons()

    # ================= Генерация =================
    def build_gen(self, tab):
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(3, weight=1)
        drop = ctk.CTkFrame(tab, height=84, corner_radius=12, border_width=2, border_color="gray35", fg_color=("gray90", "gray14"))
        drop.grid(row=0, column=0, padx=6, pady=(6, 8), sticky="ew")
        drop.grid_propagate(False)
        ctk.CTkLabel(drop, text=t("gen.drop"), font=ctk.CTkFont(size=18)).place(relx=.5, rely=.38, anchor="center")
        ctk.CTkLabel(drop, text=t("gen.drop_hint"),
                     text_color=MUTED).place(relx=.5, rely=.72, anchor="center")

        bar = ctk.CTkFrame(tab, fg_color="transparent")
        bar.grid(row=1, column=0, padx=6, pady=2, sticky="ew")
        bar.columnconfigure(2, weight=1)
        ctk.CTkButton(bar, text=t("gen.add_files"), width=130, command=self.pick_files).grid(row=0, column=0, padx=(0, 8))
        ctk.CTkButton(bar, text=t("gen.add_folder"), width=130, command=self.pick_folder).grid(row=0, column=1)
        self.btn_stop = ctk.CTkButton(bar, text=t("gen.stop"), width=90, fg_color="gray30", hover_color="#991b1b",
                                      state="disabled", command=self.on_stop)
        self.btn_stop.grid(row=0, column=3, padx=8)
        self.btn_start = ctk.CTkButton(bar, text=t("gen.start"), width=110, fg_color="#16a34a", hover_color="#15803d", command=self.start)
        self.btn_start.grid(row=0, column=4)

        opt = ctk.CTkFrame(tab, fg_color="transparent")
        opt.grid(row=2, column=0, padx=6, pady=(10, 2), sticky="ew")
        opt.columnconfigure(4, weight=1)
        names = sorted(BY_NAME)
        self.var_src = ctk.StringVar(value=AUTO)
        self.var_tgt = ctk.StringVar(value=models.LANGS[models.load_settings()["target"]][2])
        ctk.CTkLabel(opt, text=t("gen.source")).grid(row=0, column=0, padx=(0, 6), sticky="w")
        ctk.CTkOptionMenu(opt, values=[AUTO] + names, variable=self.var_src, width=170, dynamic_resizing=False,
                          command=lambda _: self.show_cfg()).grid(row=0, column=1, padx=(0, 18), sticky="w")
        ctk.CTkLabel(opt, text=t("gen.target")).grid(row=0, column=2, padx=(0, 6), sticky="w")
        ctk.CTkOptionMenu(opt, values=names, variable=self.var_tgt, width=150, dynamic_resizing=False,
                          command=lambda v: (models.save_settings(target=BY_NAME[v]), self.show_cfg())).grid(
            row=0, column=3, sticky="w")
        self.use_embedded = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(opt, text=t("gen.embedded"),
                        variable=self.use_embedded).grid(row=1, column=0, columnspan=4, pady=(8, 0), sticky="w")
        self.lbl_cfg = ctk.CTkLabel(opt, text="", text_color=MUTED, anchor="e", justify="right")
        self.lbl_cfg.grid(row=0, column=4, rowspan=2, padx=(12, 0), sticky="e")

        self.list = ctk.CTkScrollableFrame(tab, label_text=t("gen.queue"), label_anchor="w")
        self.list.grid(row=3, column=0, padx=6, pady=8, sticky="nsew")
        self.list.columnconfigure(0, weight=1)

        pr = ctk.CTkFrame(tab, fg_color="transparent")
        pr.grid(row=4, column=0, padx=6, pady=2, sticky="ew")
        pr.columnconfigure(0, weight=1)
        self.lbl_stage = ctk.CTkLabel(pr, text=t("gen.stage", name="—"), anchor="w")
        self.lbl_stage.grid(row=0, column=0, sticky="ew")
        self.bar_stage = ctk.CTkProgressBar(pr)
        self.bar_stage.set(0)
        self.bar_stage.grid(row=1, column=0, pady=(2, 8), sticky="ew")
        self.lbl_all = ctk.CTkLabel(pr, text=t("gen.episode", n=0, total=0), anchor="w")
        self.lbl_all.grid(row=2, column=0, sticky="ew")
        self.bar_all = ctk.CTkProgressBar(pr)
        self.bar_all.set(0)
        self.bar_all.grid(row=3, column=0, pady=(2, 0), sticky="ew")

        self.btn_log = ctk.CTkButton(tab, text=t("gen.log") + " ▾", anchor="w", width=90, fg_color="transparent",
                                     text_color=("gray20", "gray80"), hover_color=("gray80", "gray25"), command=self.toggle_log)
        self.btn_log.grid(row=5, column=0, padx=2, pady=(8, 0), sticky="w")
        self.log = ctk.CTkTextbox(tab, height=140, state="disabled", wrap="word")
        self.log._textbox.tag_config("warn", foreground=WARN)
        self.log.grid(row=6, column=0, padx=6, pady=(2, 4), sticky="ew")

    def langs(self):
        return BY_NAME.get(self.var_src.get(), "auto"), BY_NAME[self.var_tgt.get()]

    def show_cfg(self):
        s, (src, tgt) = models.load_settings(), self.langs()
        for key, rb in self.rb_tr.items():  # OPUS-MT умеет только en→ru — для других пар недоступен
            rb.configure(state="normal" if models.supports(key, src, tgt) else "disabled")
        warn = (t("gen.en_only") if s["whisper"].endswith(".en") and src not in ("auto", "en") else
                t("gen.unsupported") if not models.supports(s["translator"], src, tgt) else "")
        self.lbl_cfg.configure(text=f"Whisper: {s['whisper']}\n" + t("gen.translation", name=models.TRANSLATORS[s["translator"]]["title"])
                               + (f"\n{warn}" if warn else ""), text_color=WARN if warn else MUTED)

    def pick_files(self):
        self.add(filedialog.askopenfilenames(title=t("dlg.pick_files"), filetypes=VIDEO_TYPES))

    def pick_folder(self):
        d = filedialog.askdirectory(title=t("dlg.pick_folder"))
        if d:
            self.add([d])

    def add(self, paths):
        for v in core.collect(paths):
            if os.path.normcase(v) in self.known:
                continue
            self.known.add(os.path.normcase(v))
            it = Item(v)
            row = ctk.CTkFrame(self.list, fg_color="transparent")
            row.grid(row=len(self.items), column=0, sticky="ew")
            row.columnconfigure(0, weight=1)
            ctk.CTkLabel(row, text=os.path.basename(v), anchor="w").grid(row=0, column=0, sticky="ew", padx=4)
            it.label = ctk.CTkLabel(row, text=t("state.wait"), width=170, anchor="e", text_color=MUTED)
            it.label.grid(row=0, column=1, padx=4)
            self.items.append(it)
        self.refresh_total()

    def set_state(self, it, state):  # state: wait | done | done_notr | error или этап из core.on_stage
        it.state = state
        color = {"done": OK, "done_notr": WARN, "error": ERR, "wait": MUTED}.get(state, BUSY)
        it.label.configure(text=self.state_text(state), text_color=color)

    @staticmethod
    def state_text(state):
        return t(("state." if state in DONE + ("wait",) else "stage.") + state)

    def refresh_total(self):
        n = sum(1 for i in self.items if i.state in DONE)
        self.bar_all.set(n / len(self.items) if self.items else 0)

    def start(self):
        if not self.items or self.busy():
            return
        for it in self.items:
            if it.state == "error":
                self.set_state(it, "wait")
        if not any(i.state == "wait" for i in self.items):
            return
        self.stop.clear()
        self.run_job(self.work, self.use_embedded.get(), *self.langs())

    def on_stop(self):
        self.stop.set()
        self.btn_stop.configure(state="disabled", fg_color="gray30")
        self.log_text(t("log.stopping"))

    def on_close(self):
        if self.job:
            messagebox.showinfo(t("msg.busy_title"), t("msg.close_busy"))
        else:
            self.destroy()

    def work(self, use_embedded, source, target):  # фоновый поток: только очередь сообщений, виджетов не трогает
        ok = bad = 0
        try:
            while not self.stop.is_set():
                it = next((i for i in self.items if i.state == "wait"), None)
                if not it:
                    break
                n, total = self.items.index(it) + 1, len(self.items)
                self.q.put(("episode", n, total))
                self.warn = False
                core.on_stage = lambda s, it=it: self.q.put(("state", it, s))
                core.on_progress = lambda d, total: self.q.put(("progress", d, total))
                core.on_untranslated = lambda: setattr(self, "warn", True)
                core.on_log("\n" + t("log.episode", n=n, total=total, name=os.path.basename(it.path)))
                try:
                    core.on_log(t("log.done", path=core.process(it.path, use_embedded, source=source, target=target)))
                    self.q.put(("state", it, "done_notr" if self.warn else "done"))
                    ok += 1
                except Exception as e:
                    core.on_log(t("log.error", error=e))
                    self.q.put(("state", it, "error"))
                    bad += 1
        except Exception as e:
            core.on_log(t("log.crash", error=repr(e)))
        core.on_log("\n" + t("log.summary", ok=ok, bad=bad))
        self.q.put(("end",))

    def set_stage(self, name):  # новый этап: полоса «бегает», пока нет первых данных о ходе
        self.p0, self.stage = None, name
        self.lbl_stage.configure(text=t("gen.stage", name=name))
        self.bar_stage.configure(mode="indeterminate")
        self.bar_stage.start()

    def progress(self, done, total):
        if not total:
            return
        now = time.time()
        if self.p0 is None:
            self.p0 = (now, done)
            self.bar_stage.stop()
            self.bar_stage.configure(mode="determinate")
        self.bar_stage.set(done / total)
        t0, d0 = self.p0
        eta = t("gen.eta", time=fmt((now - t0) / (done - d0) * (total - done))) if done > d0 else ""
        self.lbl_stage.configure(text=t("gen.stage_pct", name=self.stage, pct=done * 100 // total) + eta)

    def log_text(self, text):
        self.log.configure(state="normal")
        self.log._textbox.insert("end", text + "\n", "warn" if "!!" in text else ())
        self.log._textbox.see("end")
        self.log.configure(state="disabled")

    def toggle_log(self):
        if self.log.winfo_ismapped():
            self.log.grid_remove()
            self.btn_log.configure(text=t("gen.log") + " ▸")
        else:
            self.log.grid()
            self.btn_log.configure(text=t("gen.log") + " ▾")

    # ================= Дорожки =================
    COLS = [("#", 36), (t("col.type"), 120), (t("col.codec"), 80), (t("col.lang"), 64), (t("col.title"), 0),
            (t("col.default"), 84), (t("col.delete"), 70)]

    def build_tracks(self, tab):
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(2, weight=1)
        top = ctk.CTkFrame(tab, fg_color="transparent")
        top.grid(row=0, column=0, padx=6, pady=(6, 8), sticky="ew")
        top.columnconfigure(1, weight=1)
        ctk.CTkButton(top, text=t("trk.open"), width=140, command=self.pick_tracks).grid(row=0, column=0)
        self.lbl_file = ctk.CTkLabel(top, text=t("trk.hint"), anchor="w", text_color=MUTED)
        self.lbl_file.grid(row=0, column=1, padx=12, sticky="ew")

        self.trk = ctk.CTkScrollableFrame(tab, fg_color="transparent")
        self.trk.grid(row=2, column=0, padx=0, pady=4, sticky="nsew")
        for c, (_, w) in enumerate(self.COLS):
            self.trk.columnconfigure(c, weight=1 if not w else 0, minsize=w)
        self.trk_header()

        bot = ctk.CTkFrame(tab, fg_color="transparent")
        bot.grid(row=3, column=0, padx=6, pady=(4, 4), sticky="ew")
        bot.columnconfigure(0, weight=1)
        self.lbl_trk = ctk.CTkLabel(bot, text=t("trk.note"),
                                    anchor="w", text_color=MUTED, wraplength=560, justify="left")
        self.lbl_trk.grid(row=0, column=0, sticky="ew")
        self.btn_reload = ctk.CTkButton(bot, text=t("trk.reset"), width=100, fg_color="gray30", hover_color="gray25",
                                        command=lambda: self.trk_path and self.open_tracks(self.trk_path))
        self.btn_reload.grid(row=0, column=1, padx=8)
        self.btn_apply = ctk.CTkButton(bot, text=t("trk.apply"), width=120, command=self.apply_tracks)
        self.btn_apply.grid(row=0, column=2)
        self.trk_path, self.trk_info, self.trk_rows = None, None, []

    def trk_header(self):  # шапка в той же сетке, что и строки, — колонки всегда совпадают
        ctk.CTkFrame(self.trk, fg_color=("gray85", "gray20"), corner_radius=8, height=34).grid(
            row=0, column=0, columnspan=len(self.COLS), sticky="nsew", pady=(0, 4))
        for c, (name, _) in enumerate(self.COLS):
            ctk.CTkLabel(self.trk, text=name, font=ctk.CTkFont(weight="bold"), anchor="w", fg_color=("gray85", "gray20"), corner_radius=0).grid(
                row=0, column=c, padx=6, pady=(4, 8), sticky="w")

    def pick_tracks(self):
        p = filedialog.askopenfilename(title=t("dlg.pick_video"), filetypes=VIDEO_TYPES)
        if p:
            self.open_tracks(os.path.abspath(p))

    def open_tracks(self, path, note=None):
        try:
            info, rows = tracks.streams(path)
        except Exception as e:
            messagebox.showerror("Subgen", t("trk.read_error", error=e))
            return
        self.trk_path, self.trk_info = path, info
        self.lbl_file.configure(text=path, text_color=("gray10", "gray90"))
        for w in self.trk.winfo_children():
            w.destroy()
        self.trk_header()
        self.trk_rows = []
        for r, row in enumerate(rows, 1):
            kind = tracks.TYPES.get(row["type"], row["type"]) + ("  · Subgen" if row["ours"] else "")
            ctk.CTkLabel(self.trk, text=str(row["index"]), anchor="w").grid(row=r, column=0, padx=6, pady=3, sticky="w")
            ctk.CTkLabel(self.trk, text=kind, anchor="w").grid(row=r, column=1, padx=6, sticky="w")
            ctk.CTkLabel(self.trk, text=row["codec"], anchor="w", text_color=MUTED).grid(row=r, column=2, padx=6, sticky="w")
            editable = row["type"] in ("video", "audio", "subtitle")
            lang = ctk.CTkEntry(self.trk, width=56)
            lang.insert(0, row["language"])
            title = ctk.CTkEntry(self.trk)
            title.insert(0, row["title"])
            default = ctk.BooleanVar(value=row["default"])
            delete = ctk.BooleanVar(value=False)
            cb_def = ctk.CTkCheckBox(self.trk, text="", width=24, variable=default)
            cb_del = ctk.CTkCheckBox(self.trk, text="", width=24, variable=delete, fg_color=ERR, hover_color="#991b1b")
            for w, c in ((lang, 3), (title, 4), (cb_def, 5), (cb_del, 6)):
                w.grid(row=r, column=c, padx=6, sticky="ew" if c == 4 else "w")
                if not editable:
                    w.configure(state="disabled")
            if row["type"] not in tracks.DELETABLE:
                cb_del.grid_remove()
            self.trk_rows.append((row, lang, title, default, delete))
        self.lbl_trk.configure(text=note or t("trk.count", n=len(rows)),
                               text_color=OK if note else MUTED)

    def apply_tracks(self):
        if not self.trk_path or self.busy():
            return
        edits = {}
        for row, lang, title, default, delete in self.trk_rows:
            e = {}
            if lang.get().strip().lower() != row["language"]:
                e["language"] = lang.get().strip().lower()
            if title.get().strip() != row["title"]:
                e["title"] = title.get().strip()
            if default.get() != row["default"]:
                e["default"] = default.get()
            if delete.get():
                e["delete"] = True
            if e:
                edits[row["index"]] = e
        if not edits:
            self.lbl_trk.configure(text=t("trk.no_changes"), text_color=MUTED)
            return
        gone = [str(i) for i, e in edits.items() if e.get("delete")]
        if gone and not messagebox.askyesno("Subgen", t("trk.confirm_delete", list=", ".join(gone))):
            return
        self.lbl_trk.configure(text=t("trk.applying"), text_color=BUSY)
        self.run_job(self.tracks_work, self.trk_path, self.trk_info, edits)

    def tracks_work(self, path, info, edits):
        try:
            out = tracks.apply(path, info, edits)
            core.on_log(t("log.tracks_done", path=out))
            self.q.put(("tracks", out, None))
        except Exception as e:
            core.on_log(t("log.tracks_error", error=e))
            self.q.put(("tracks", path, str(e)))

    # ================= Модели =================
    def build_models(self, tab):
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(0, weight=1)
        box = ctk.CTkScrollableFrame(tab, fg_color="transparent")
        box.grid(row=0, column=0, padx=0, pady=(4, 4), sticky="nsew")
        box.columnconfigure(1, weight=1)
        s = models.load_settings()
        self.var_whisper = ctk.StringVar(value=s["whisper"])
        self.var_tr = ctk.StringVar(value=s["translator"])
        self.model_rows, self.rb_tr = [], {}
        r = 0
        for kind, head, hint, var, items in (
                ("whisper", t("mdl.whisper_head"), t("mdl.whisper_hint"), self.var_whisper,
                 [(k, k, v[2]) for k, v in models.WHISPER.items()]),
                ("translate", t("mdl.tr_head"), t("mdl.tr_hint"), self.var_tr,
                 [(k, v["title"], v["note"]) for k, v in models.TRANSLATORS.items()])):
            ctk.CTkLabel(box, text=head, font=ctk.CTkFont(size=16, weight="bold"), anchor="w").grid(
                row=r, column=0, columnspan=5, padx=8, pady=(10 if r else 2, 0), sticky="w")
            ctk.CTkLabel(box, text=hint, text_color=MUTED, anchor="w", justify="left", wraplength=780).grid(
                row=r + 1, column=0, columnspan=5, padx=8, pady=(0, 6), sticky="w")
            r += 2
            for key, name, note in items:
                rb = ctk.CTkRadioButton(box, text=name, value=key, variable=var, width=170,
                                        command=lambda k=kind, v=var: self.choose(k, v.get()))
                rb.grid(row=r, column=0, padx=8, pady=1, sticky="w")
                if kind == "translate":
                    self.rb_tr[key] = rb
                ctk.CTkLabel(box, text=note, anchor="w", text_color=MUTED).grid(row=r, column=1, padx=6, sticky="w")
                size = models.size(kind, key)
                ctk.CTkLabel(box, text=models.fmt_size(size) if size else "—", width=70, anchor="e").grid(row=r, column=2, padx=6)
                st = ctk.CTkLabel(box, text="", width=100, anchor="w")
                st.grid(row=r, column=3, padx=6)
                btn = ctk.CTkButton(box, text="", width=96, height=26, command=lambda k=kind, key=key: self.model_action(k, key))
                btn.grid(row=r, column=4, padx=8, pady=1)
                if key == "google":
                    btn.grid_remove()
                self.model_rows.append((kind, key, st, btn))
                r += 1
        bot = ctk.CTkFrame(tab, fg_color="transparent")
        bot.grid(row=1, column=0, padx=8, pady=(2, 6), sticky="ew")
        bot.columnconfigure(0, weight=1)
        self.lbl_dl = ctk.CTkLabel(bot, text=t("mdl.where", path=os.path.join(models.DATA, "models")), anchor="w",
                                   text_color=MUTED)
        self.lbl_dl.grid(row=0, column=0, sticky="ew")
        ui = ctk.CTkFrame(bot, fg_color="transparent")
        ui.grid(row=0, column=1, sticky="e")
        langs = {models.LANGS[c][3]: c for c in i18n.available()}  # самоназвания: «Русский», «Deutsch», «日本語»
        ctk.CTkLabel(ui, text=t("ui.lang")).grid(row=0, column=0, padx=(12, 6))
        ctk.CTkOptionMenu(ui, values=sorted(langs, key=str.casefold), width=150, dynamic_resizing=False,
                          variable=ctk.StringVar(value=models.LANGS[i18n.LANG][3]),
                          command=lambda v: (models.save_settings(ui_lang=langs[v]), self.lbl_dl.configure(
                              text=f"{t('ui.lang')} {v} — {t('ui.restart')}", text_color=WARN))).grid(row=0, column=1)
        self.bar_dl = ctk.CTkProgressBar(bot)
        self.bar_dl.set(0)
        self.bar_dl.grid(row=1, column=0, columnspan=2, pady=(2, 0), sticky="ew")
        self.bar_dl.grid_remove()
        self.refresh_models()

    def choose(self, kind, key):
        models.save_settings(**{"whisper" if kind == "whisper" else "translator": key})
        self.show_cfg()
        if not models.local_path(kind, key):
            self.lbl_dl.configure(text=t("mdl.not_yet", key=key), text_color=MUTED)

    def refresh_models(self):
        for kind, key, st, btn in self.model_rows:
            have = bool(models.local_path(kind, key))
            if key == "google":
                st.configure(text=t("mdl.online"), text_color=MUTED)
                continue
            st.configure(text=t("mdl.have") if have else t("mdl.missing"), text_color=OK if have else MUTED)
            btn.configure(text=t("mdl.delete") if have else t("mdl.download"), fg_color="gray30" if have else ("#3b8ed0", "#1f6aa5"),
                          hover_color="#991b1b" if have else ("#36719f", "#144870"),
                          state="disabled" if self.job else "normal")

    def model_action(self, kind, key):
        if self.busy():
            return
        if models.local_path(kind, key):
            if not messagebox.askyesno("Subgen", t("mdl.confirm_delete", key=key)):
                return
            core.unload()
            try:
                models.delete(kind, key)
                self.lbl_dl.configure(text=t("mdl.deleted", key=key), text_color=MUTED)
            except Exception as e:
                messagebox.showerror("Subgen", t("mdl.delete_error", key=key, error=e))
            self.refresh_models()
        else:
            self.lbl_dl.configure(text=t("mdl.downloading", key=key), text_color=BUSY)
            self.run_job(self.download_work, kind, key)

    def download_work(self, kind, key):
        try:
            models.download(kind, key, lambda d, t: self.q.put(("dl", key, d, t)))
            core.on_log(t("mdl.downloaded", key=key))
            self.q.put(("dl_end", key, None))
        except Exception as e:
            core.on_log(t("mdl.dl_error_log", key=key, error=e))
            self.q.put(("dl_end", key, str(e)))

    # ================= сообщения из потоков =================
    def poll(self):
        try:
            while True:
                self.handle(*self.q.get_nowait())
        except queue.Empty:
            pass
        self.after(100, self.poll)

    def job_done(self):
        self.job = None
        self.refresh_buttons()

    def refresh_buttons(self):
        running = bool(self.job)
        self.btn_start.configure(state="disabled" if running else "normal")
        self.btn_apply.configure(state="disabled" if running else "normal")
        processing = running and self.job_target == self.work
        self.btn_stop.configure(state="normal" if processing else "disabled", fg_color="#b91c1c" if processing else "gray30")
        self.refresh_models()

    def handle(self, kind, *a):
        if kind == "log":
            self.log_text(a[0])
        elif kind == "episode":
            self.lbl_all.configure(text=t("gen.episode", n=a[0], total=a[1]))
            self.set_stage("—")
        elif kind == "state":
            self.set_state(a[0], a[1])
            if a[1] in DONE:
                self.refresh_total()
                self.bar_stage.stop()
                self.bar_stage.configure(mode="determinate")
                self.bar_stage.set(0 if a[1] == "error" else 1)
                self.lbl_stage.configure(text=t("gen.stage", name=self.state_text(a[1])))
            else:
                self.set_stage(self.state_text(a[1]))
        elif kind == "progress":
            self.progress(*a)
        elif kind == "end":
            self.job_done()
            self.refresh_total()
        elif kind == "tracks":
            self.job_done()
            out, err = a
            if err:
                self.lbl_trk.configure(text=t("trk.error", error=err), text_color=ERR)
            else:
                self.open_tracks(out, t("trk.applied"))
        elif kind == "dl":
            key, done, total = a
            self.bar_dl.grid()
            self.bar_dl.set(done / total if total else 0)
            self.lbl_dl.configure(text=t("mdl.progress", key=key, done=models.fmt_size(done), total=models.fmt_size(total)),
                                  text_color=BUSY)
        elif kind == "dl_end":
            self.job_done()
            key, err = a
            self.lbl_dl.configure(text=t("mdl.dl_error", key=key, error=err) if err else t("mdl.downloaded", key=key),
                                  text_color=ERR if err else OK)


def main():
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Subgen.GUI")
    except Exception:
        pass
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    use_font()
    App(sys.argv[1:]).mainloop()


def use_font():
    """Шрифт под письменность языка интерфейса (японский, арабский, хинди...) — до создания виджетов."""
    if i18n.font():
        ctk.ThemeManager.theme["CTkFont"]["family"] = i18n.font()


if __name__ == "__main__":
    main()
