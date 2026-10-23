"""Окно Subgen: вкладки «Генерация», «Дорожки», «Модели»."""
import ctypes, os, queue, sys, threading, time
from tkinter import filedialog, messagebox

for _n in ("stdout", "stderr"):  # под pythonw потоков нет, а huggingface/ctranslate2 в них пишут
    if getattr(sys, _n) is None:
        setattr(sys, _n, open(os.devnull, "w", encoding="utf-8"))

import customtkinter as ctk
from tkinterdnd2 import DND_FILES, TkinterDnD

from . import core, models, tracks

ICON = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "subgen.ico")
OK, ERR, WARN, BUSY, MUTED = "#22c55e", "#ef4444", "#f59e0b", "#60a5fa", "gray60"
VIDEO_TYPES = [("Видео", " ".join("*" + e for e in sorted(core.VIDEO_EXT)))]
TAB_GEN, TAB_TRACKS, TAB_MODELS = "Генерация", "Дорожки", "Модели"


def fmt(sec):
    return f"{int(sec) // 60}:{int(sec) % 60:02}"


class Item:
    def __init__(self, path):
        self.path, self.state, self.label = path, "ожидает", None


class App(ctk.CTk, TkinterDnD.DnDWrapper):
    def __init__(self, paths):
        super().__init__()
        self.TkdndVersion = TkinterDnD._require(self)
        self.title("Subgen — субтитры EN + RU")
        self.geometry("900x740")
        self.minsize(760, 600)
        self.after(300, self.set_icon)  # customtkinter сам ставит свою иконку через 200 мс
        self.q, self.items, self.known = queue.Queue(), [], set()
        self.job, self.stop, self.warn, self.p0 = None, threading.Event(), False, None
        core.on_log = lambda *a: self.q.put(("log", " ".join(map(str, a))))
        self.report_callback_exception = lambda *e: self.log_text(f"!! Сбой окна: {e[1]!r}")

        self.tabs = ctk.CTkTabview(self, corner_radius=12, anchor="nw")
        self.tabs.pack(fill="both", expand=True, padx=14, pady=(6, 14))
        for t in (TAB_GEN, TAB_TRACKS, TAB_MODELS):
            self.tabs.add(t)
        self.tabs._segmented_button.configure(font=ctk.CTkFont(size=14, weight="bold"))
        self.build_gen(self.tabs.tab(TAB_GEN))
        self.build_tracks(self.tabs.tab(TAB_TRACKS))
        self.build_models(self.tabs.tab(TAB_MODELS))

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
            messagebox.showinfo("Subgen", "Дождитесь окончания текущей операции.")
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
        ctk.CTkLabel(drop, text="Перетащите серии или папку сюда", font=ctk.CTkFont(size=18)).place(relx=.5, rely=.38, anchor="center")
        ctk.CTkLabel(drop, text="MKV, MP4, AVI, WebM, MOV — результат всегда в MKV, оригинал уходит в Корзину",
                     text_color=MUTED).place(relx=.5, rely=.72, anchor="center")

        bar = ctk.CTkFrame(tab, fg_color="transparent")
        bar.grid(row=1, column=0, padx=6, pady=2, sticky="ew")
        bar.columnconfigure(2, weight=1)
        ctk.CTkButton(bar, text="Добавить файлы", width=130, command=self.pick_files).grid(row=0, column=0, padx=(0, 8))
        ctk.CTkButton(bar, text="Добавить папку", width=130, command=self.pick_folder).grid(row=0, column=1)
        self.btn_stop = ctk.CTkButton(bar, text="Стоп", width=90, fg_color="gray30", hover_color="#991b1b",
                                      state="disabled", command=self.on_stop)
        self.btn_stop.grid(row=0, column=3, padx=8)
        self.btn_start = ctk.CTkButton(bar, text="Старт", width=110, fg_color="#16a34a", hover_color="#15803d", command=self.start)
        self.btn_start.grid(row=0, column=4)

        opt = ctk.CTkFrame(tab, fg_color="transparent")
        opt.grid(row=2, column=0, padx=6, pady=(10, 2), sticky="ew")
        opt.columnconfigure(1, weight=1)
        self.use_embedded = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(opt, text="Использовать вшитые английские субтитры (без генерации)",
                        variable=self.use_embedded).grid(row=0, column=0, sticky="w")
        self.lbl_cfg = ctk.CTkLabel(opt, text="", text_color=MUTED, anchor="e")
        self.lbl_cfg.grid(row=0, column=1, sticky="e")
        self.show_cfg()

        self.list = ctk.CTkScrollableFrame(tab, label_text="Очередь", label_anchor="w")
        self.list.grid(row=3, column=0, padx=6, pady=8, sticky="nsew")
        self.list.columnconfigure(0, weight=1)

        pr = ctk.CTkFrame(tab, fg_color="transparent")
        pr.grid(row=4, column=0, padx=6, pady=2, sticky="ew")
        pr.columnconfigure(0, weight=1)
        self.lbl_stage = ctk.CTkLabel(pr, text="Этап: —", anchor="w")
        self.lbl_stage.grid(row=0, column=0, sticky="ew")
        self.bar_stage = ctk.CTkProgressBar(pr)
        self.bar_stage.set(0)
        self.bar_stage.grid(row=1, column=0, pady=(2, 8), sticky="ew")
        self.lbl_all = ctk.CTkLabel(pr, text="Серия 0 из 0", anchor="w")
        self.lbl_all.grid(row=2, column=0, sticky="ew")
        self.bar_all = ctk.CTkProgressBar(pr)
        self.bar_all.set(0)
        self.bar_all.grid(row=3, column=0, pady=(2, 0), sticky="ew")

        self.btn_log = ctk.CTkButton(tab, text="Журнал ▾", anchor="w", width=90, fg_color="transparent",
                                     text_color=("gray20", "gray80"), hover_color=("gray80", "gray25"), command=self.toggle_log)
        self.btn_log.grid(row=5, column=0, padx=2, pady=(8, 0), sticky="w")
        self.log = ctk.CTkTextbox(tab, height=140, state="disabled", wrap="word")
        self.log._textbox.tag_config("warn", foreground=WARN)
        self.log.grid(row=6, column=0, padx=6, pady=(2, 4), sticky="ew")

    def show_cfg(self):
        s = models.load_settings()
        self.lbl_cfg.configure(text=f"Whisper: {s['whisper']}  ·  перевод: {models.TRANSLATORS[s['translator']]['title']}")

    def pick_files(self):
        self.add(filedialog.askopenfilenames(title="Выберите серии", filetypes=VIDEO_TYPES))

    def pick_folder(self):
        d = filedialog.askdirectory(title="Выберите папку с сериями")
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
            it.label = ctk.CTkLabel(row, text=it.state, width=170, anchor="e", text_color=MUTED)
            it.label.grid(row=0, column=1, padx=4)
            self.items.append(it)
        self.refresh_total()

    def set_state(self, it, state):
        it.state = state
        color = OK if state.startswith("готово") else ERR if state == "ошибка" else MUTED if state == "ожидает" else BUSY
        it.label.configure(text=state, text_color=WARN if "только EN" in state else color)

    def refresh_total(self):
        n = sum(1 for i in self.items if i.state.startswith(("готово", "ошибка")))
        self.bar_all.set(n / len(self.items) if self.items else 0)

    def start(self):
        if not self.items or self.busy():
            return
        for it in self.items:
            if it.state == "ошибка":
                self.set_state(it, "ожидает")
        if not any(i.state == "ожидает" for i in self.items):
            return
        self.stop.clear()
        self.run_job(self.work, self.use_embedded.get())

    def on_stop(self):
        self.stop.set()
        self.btn_stop.configure(state="disabled", fg_color="gray30")
        self.log_text("Остановка после текущей серии...")

    def on_close(self):
        if self.job:
            messagebox.showinfo("Идёт работа", "Дождитесь окончания (для обработки — нажмите «Стоп»), "
                                "иначе файл или модель могут остаться недоделанными.")
        else:
            self.destroy()

    def work(self, use_embedded):  # фоновый поток: только очередь сообщений, виджетов не трогает
        ok = bad = 0
        try:
            while not self.stop.is_set():
                it = next((i for i in self.items if i.state == "ожидает"), None)
                if not it:
                    break
                n, total = self.items.index(it) + 1, len(self.items)
                self.q.put(("episode", n, total))
                self.warn = False
                core.on_stage = lambda s, it=it: self.q.put(("state", it, s))
                core.on_progress = lambda d, t: self.q.put(("progress", d, t))
                core.on_log(f"\n=== Серия {n} из {total}: {os.path.basename(it.path)} ===")
                try:
                    core.on_log(f"Готово: {core.process(it.path, use_embedded)}")
                    self.q.put(("state", it, "готово (только EN)" if self.warn else "готово"))
                    ok += 1
                except Exception as e:
                    core.on_log(f"ОШИБКА: {e}\nОригинал не тронут.")
                    self.q.put(("state", it, "ошибка"))
                    bad += 1
        except Exception as e:
            core.on_log(f"!! Сбой обработки: {e!r}")
        core.on_log(f"\n===== Итог: успешно {ok}, с ошибками {bad} =====")
        self.q.put(("end",))

    def set_stage(self, name):  # новый этап: полоса «бегает», пока нет первых данных о ходе
        self.p0, self.stage = None, name
        self.lbl_stage.configure(text=f"Этап: {name}")
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
        eta = f" · осталось ~{fmt((now - t0) / (done - d0) * (total - done))}" if done > d0 else ""
        self.lbl_stage.configure(text=f"Этап: {self.stage} — {done * 100 // total}%{eta}")

    def log_text(self, text):
        self.warn = self.warn or "ПЕРЕВОД НЕ УДАЛСЯ" in text
        self.log.configure(state="normal")
        warn = any(k in text for k in ("!!", "ОШИБКА", "Внимание"))
        self.log._textbox.insert("end", text + "\n", "warn" if warn else ())
        self.log._textbox.see("end")
        self.log.configure(state="disabled")

    def toggle_log(self):
        if self.log.winfo_ismapped():
            self.log.grid_remove()
            self.btn_log.configure(text="Журнал ▸")
        else:
            self.log.grid()
            self.btn_log.configure(text="Журнал ▾")

    # ================= Дорожки =================
    COLS = [("#", 36), ("Тип", 120), ("Кодек", 80), ("Язык", 64), ("Название", 0), ("По умолч.", 84), ("Удалить", 70)]

    def build_tracks(self, tab):
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(2, weight=1)
        top = ctk.CTkFrame(tab, fg_color="transparent")
        top.grid(row=0, column=0, padx=6, pady=(6, 8), sticky="ew")
        top.columnconfigure(1, weight=1)
        ctk.CTkButton(top, text="Открыть видео…", width=140, command=self.pick_tracks).grid(row=0, column=0)
        self.lbl_file = ctk.CTkLabel(top, text="Выберите видео или перетащите его в окно", anchor="w", text_color=MUTED)
        self.lbl_file.grid(row=0, column=1, padx=12, sticky="ew")

        self.trk = ctk.CTkScrollableFrame(tab, fg_color="transparent")
        self.trk.grid(row=2, column=0, padx=0, pady=4, sticky="nsew")
        for c, (_, w) in enumerate(self.COLS):
            self.trk.columnconfigure(c, weight=1 if not w else 0, minsize=w)
        self.trk_header()

        bot = ctk.CTkFrame(tab, fg_color="transparent")
        bot.grid(row=3, column=0, padx=6, pady=(4, 4), sticky="ew")
        bot.columnconfigure(0, weight=1)
        self.lbl_trk = ctk.CTkLabel(bot, text="Видеодорожки удалить нельзя. Изменения сохраняются в MKV, оригинал — в Корзину.",
                                    anchor="w", text_color=MUTED, wraplength=560, justify="left")
        self.lbl_trk.grid(row=0, column=0, sticky="ew")
        self.btn_reload = ctk.CTkButton(bot, text="Сбросить", width=100, fg_color="gray30", hover_color="gray25",
                                        command=lambda: self.trk_path and self.open_tracks(self.trk_path))
        self.btn_reload.grid(row=0, column=1, padx=8)
        self.btn_apply = ctk.CTkButton(bot, text="Применить", width=120, command=self.apply_tracks)
        self.btn_apply.grid(row=0, column=2)
        self.trk_path, self.trk_info, self.trk_rows = None, None, []

    def trk_header(self):  # шапка в той же сетке, что и строки, — колонки всегда совпадают
        ctk.CTkFrame(self.trk, fg_color=("gray85", "gray20"), corner_radius=8, height=34).grid(
            row=0, column=0, columnspan=len(self.COLS), sticky="nsew", pady=(0, 4))
        for c, (name, _) in enumerate(self.COLS):
            ctk.CTkLabel(self.trk, text=name, font=ctk.CTkFont(weight="bold"), anchor="w", fg_color=("gray85", "gray20"), corner_radius=0).grid(
                row=0, column=c, padx=6, pady=(4, 8), sticky="w")

    def pick_tracks(self):
        p = filedialog.askopenfilename(title="Выберите видео", filetypes=VIDEO_TYPES)
        if p:
            self.open_tracks(os.path.abspath(p))

    def open_tracks(self, path, note=None):
        try:
            info, rows = tracks.streams(path)
        except Exception as e:
            messagebox.showerror("Subgen", f"Не удалось прочитать файл:\n{e}")
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
        self.lbl_trk.configure(text=note or f"Потоков: {len(rows)}. Отредактируйте поля и нажмите «Применить».",
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
            self.lbl_trk.configure(text="Изменений нет.", text_color=MUTED)
            return
        gone = [str(i) for i, e in edits.items() if e.get("delete")]
        if gone and not messagebox.askyesno("Subgen", f"Удалить дорожки {', '.join(gone)}? Оригинал файла уйдёт в Корзину."):
            return
        self.lbl_trk.configure(text="Применяю изменения...", text_color=BUSY)
        self.run_job(self.tracks_work, self.trk_path, self.trk_info, edits)

    def tracks_work(self, path, info, edits):
        try:
            out = tracks.apply(path, info, edits)
            core.on_log(f"Дорожки изменены: {out} (оригинал — в Корзине)")
            self.q.put(("tracks", out, None))
        except Exception as e:
            core.on_log(f"ОШИБКА изменения дорожек: {e}")
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
        self.model_rows = []
        r = 0
        for kind, head, hint, var, items in (
                ("whisper", "Распознавание речи — Whisper",
                 "С видеокартой NVIDIA берите large-v3-turbo. Без неё — small или medium (на процессоре медленно). "
                 "Модели .en понимают только английский.", self.var_whisper,
                 [(k, k, v[2]) for k, v in models.WHISPER.items()]),
                ("translate", "Перевод на русский",
                 "Google — онлайн, не работает через некоторые VPN. Офлайн-модели работают без интернета.", self.var_tr,
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
        self.lbl_dl = ctk.CTkLabel(bot, text=f"Модели хранятся в {os.path.join(models.DATA, 'models')}", anchor="w", text_color=MUTED)
        self.lbl_dl.grid(row=0, column=0, sticky="ew")
        self.bar_dl = ctk.CTkProgressBar(bot)
        self.bar_dl.set(0)
        self.bar_dl.grid(row=1, column=0, pady=(2, 0), sticky="ew")
        self.bar_dl.grid_remove()
        self.refresh_models()

    def choose(self, kind, key):
        models.save_settings(**{"whisper" if kind == "whisper" else "translator": key})
        self.show_cfg()
        if not models.local_path(kind, key):
            self.lbl_dl.configure(text=f"{key} ещё не скачана — скачается автоматически при первом запуске "
                                       "или нажмите «Скачать».", text_color=MUTED)

    def refresh_models(self):
        for kind, key, st, btn in self.model_rows:
            have = bool(models.local_path(kind, key))
            if key == "google":
                st.configure(text="онлайн", text_color=MUTED)
                continue
            st.configure(text="скачана" if have else "не скачана", text_color=OK if have else MUTED)
            btn.configure(text="Удалить" if have else "Скачать", fg_color="gray30" if have else ("#3b8ed0", "#1f6aa5"),
                          hover_color="#991b1b" if have else ("#36719f", "#144870"),
                          state="disabled" if self.job else "normal")

    def model_action(self, kind, key):
        if self.busy():
            return
        if models.local_path(kind, key):
            if not messagebox.askyesno("Subgen", f"Удалить модель {key}? Её можно будет скачать снова."):
                return
            core.unload()
            try:
                models.delete(kind, key)
                self.lbl_dl.configure(text=f"Модель {key} удалена.", text_color=MUTED)
            except Exception as e:
                messagebox.showerror("Subgen", f"Не удалось удалить {key}:\n{e}")
            self.refresh_models()
        else:
            self.lbl_dl.configure(text=f"Скачиваю {key}...", text_color=BUSY)
            self.run_job(self.download_work, kind, key)

    def download_work(self, kind, key):
        try:
            models.download(kind, key, lambda d, t: self.q.put(("dl", key, d, t)))
            core.on_log(f"Модель {key} скачана.")
            self.q.put(("dl_end", key, None))
        except Exception as e:
            core.on_log(f"ОШИБКА загрузки модели {key}: {e}")
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
            self.lbl_all.configure(text=f"Серия {a[0]} из {a[1]}")
            self.set_stage("—")
        elif kind == "state":
            self.set_state(a[0], a[1])
            if a[1].startswith(("готово", "ошибка")):
                self.refresh_total()
                self.bar_stage.stop()
                self.bar_stage.configure(mode="determinate")
                self.bar_stage.set(1 if a[1].startswith("готово") else 0)
                self.lbl_stage.configure(text=f"Этап: {a[1]}")
            else:
                self.set_stage(a[1])
        elif kind == "progress":
            self.progress(*a)
        elif kind == "end":
            self.job_done()
            self.refresh_total()
        elif kind == "tracks":
            self.job_done()
            out, err = a
            if err:
                self.lbl_trk.configure(text=f"Ошибка: {err}", text_color=ERR)
            else:
                self.open_tracks(out, "Готово: изменения применены, оригинал — в Корзине. Список обновлён по новому файлу.")
        elif kind == "dl":
            key, done, total = a
            self.bar_dl.grid()
            self.bar_dl.set(done / total if total else 0)
            self.lbl_dl.configure(text=f"Скачиваю {key}: {models.fmt_size(done)} из {models.fmt_size(total)}", text_color=BUSY)
        elif kind == "dl_end":
            self.job_done()
            key, err = a
            self.lbl_dl.configure(text=f"Ошибка загрузки {key}: {err}" if err else f"Модель {key} скачана.",
                                  text_color=ERR if err else OK)


def main():
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Subgen.GUI")
    except Exception:
        pass
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    App(sys.argv[1:]).mainloop()


if __name__ == "__main__":
    main()
