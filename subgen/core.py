"""Subgen: английские субтитры (Whisper или вшитые) + русский перевод, вшиваются в MKV."""
import glob, json, os, re, shutil, subprocess, sys, time

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("HF_HUB_VERBOSITY", "error")
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")

# CUDA без toolkit: DLL из pip-пакетов nvidia-cublas-cu12 / nvidia-cudnn-cu12, до импорта ctranslate2
for _d in glob.glob(os.path.join(sys.prefix, "Lib", "site-packages", "nvidia", "*", "bin")):
    os.add_dll_directory(_d)
    os.environ["PATH"] = _d + os.pathsep + os.environ["PATH"]

import numpy as np

from . import models

VIDEO_EXT = {".mkv", ".mp4", ".avi", ".webm", ".m4v", ".mov"}
TEXT_SUBS = {"subrip", "ass", "ssa", "webvtt", "mov_text", "text"}
TAG = "SUBGEN"  # тег дорожек, созданных программой: только их программа заменяет
EN_TITLE, RU_TITLE = "English (Whisper)", "Русский"

# Хуки для GUI; в консоли — print
on_log = print
on_stage = lambda name: None          # "загрузка модели" | "распознавание" | "перевод" | "вшивание"
on_progress = lambda done, total: None


def find_tool(name):
    exe = shutil.which(name)
    if exe:
        return exe
    la = os.environ["LOCALAPPDATA"]
    hits = sorted(glob.glob(os.path.join(la, "Microsoft", "WinGet", "Packages", "Gyan.FFmpeg*", "*", "bin", name + ".exe")))
    hits += glob.glob(os.path.join(la, "Microsoft", "WinGet", "Links", name + ".exe"))
    return hits[-1] if hits else None


FFMPEG, FFPROBE = find_tool("ffmpeg"), find_tool("ffprobe")
NO_FFMPEG = "Не найден ffmpeg. Запустите install.cmd или: winget install --id Gyan.FFmpeg -e"


def run(args):
    if not FFMPEG or not FFPROBE:
        raise RuntimeError(NO_FFMPEG)
    r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       creationflags=subprocess.CREATE_NO_WINDOW)
    if r.returncode:
        raise RuntimeError(r.stderr.strip()[-1500:])
    return r.stdout


def probe(path):
    return json.loads(run([FFPROBE, "-v", "error", "-show_streams", "-show_format", "-of", "json", path]))


def tag(s, name):
    return next((v for k, v in s.get("tags", {}).items() if k.lower() == name.lower()), "")


def lang(s):
    return tag(s, "language").lower()


def title(s):
    return tag(s, "title")


def is_ours(s):
    return s["codec_type"] == "subtitle" and tag(s, TAG) == "1"


def disp(s, default):
    """Флаги дорожки для -disposition: прежние (forced, attached_pic...) сохраняются, меняется только default."""
    f = [k for k, v in s.get("disposition", {}).items() if v and k != "default"] + (["default"] if default else [])
    return "+".join(f) or "0"


def ts(t):
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02}:{ms // 60000 % 60:02}:{ms // 1000 % 60:02},{ms % 1000:03}"


def write_srt(path, cues):
    with open(path, "w", encoding="utf-8") as f:
        for i, (a, b, text) in enumerate(cues, 1):
            f.write(f"{i}\n{a} --> {b}\n{text}\n\n")


def read_srt(path):
    cues = []
    for block in re.split(r"\n\s*\n", open(path, encoding="utf-8-sig").read().strip()):
        lines = block.strip().splitlines()
        i = next((k for k, l in enumerate(lines) if "-->" in l), None)
        if i is None:
            continue
        a, b = [x.strip() for x in lines[i].split("-->")]
        text = " ".join(lines[i + 1:]).strip()
        if text:
            cues.append((a, b, text))
    return cues


def ensure_model(kind, key):
    path = models.local_path(kind, key)
    if path:
        return path
    on_stage("загрузка модели")
    on_log(f"Скачиваю модель {key} (~{models.fmt_size(models.size(kind, key))}), это делается один раз...")
    return models.download(kind, key, on_progress)


def cuda_ok():
    import ctranslate2
    try:
        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False


def gpu_error(e):
    return re.search(r"cuda|cublas|cudnn|dll|gpu|device", str(e), re.I)


_whisper = None  # (ключ, устройство, модель)


def whisper(video, info, key):
    global _whisper
    audios = [s for s in info["streams"] if s["codec_type"] == "audio"]
    if not audios:
        raise RuntimeError("в файле нет звуковой дорожки")
    audio = next((s for s in audios if lang(s) in ("eng", "en")), audios[0])
    path = ensure_model("whisper", key)
    on_stage("распознавание")
    on_log("Извлекаю звук...")
    # звук сразу в numpy через ffmpeg (декодер PyAV в faster-whisper несовместим с новыми av)
    raw = subprocess.run([FFMPEG, "-v", "error", "-i", video, "-map", f"0:{audio['index']}", "-ac", "1", "-ar", "16000",
                          "-f", "f32le", "-"], capture_output=True, check=True, creationflags=subprocess.CREATE_NO_WINDOW).stdout
    wav = np.frombuffer(raw, np.float32)
    from faster_whisper import WhisperModel
    for device, ctype in (("cuda", "float16"), ("cpu", "int8")):
        if device == "cuda" and not cuda_ok():
            continue
        try:
            if not _whisper or _whisper[:2] != (key, device):
                _whisper = None
                on_log(f"Загружаю модель Whisper {key} на {device.upper()}...")
                _whisper = (key, device, WhisperModel(path, device=device, compute_type=ctype))
            on_log(f"Распознавание речи: Whisper {key}, {device.upper()} ({ctype})")
            segments, si = _whisper[2].transcribe(wav, language="en", vad_filter=True)
            cues, total = [], max(1, round(si.duration))
            for seg in segments:
                cues.append((ts(seg.start), ts(seg.end), seg.text.strip()))
                on_progress(min(round(seg.end), total), total)
            on_progress(total, total)
            return [c for c in cues if c[2]]
        except Exception as e:
            # на CPU переходим только при проблемах с видеокартой, прочие ошибки показываем как есть
            if device == "cpu" or not gpu_error(e):
                raise
            on_log(f"\n!! Видеокарта (CUDA) не сработала: {e}\n!! Перехожу на процессор — это будет заметно медленнее.")
            _whisper = None


def google(lines):
    import json, urllib.parse, urllib.request
    # translate.googleapis.com (client=gtx) отвечает и там, где translate.google.com/m уводит на страницу-заглушку
    url = "https://translate.googleapis.com/translate_a/single?client=gtx&sl=en&tl=ru&dt=t"

    def call(text):
        for attempt in range(3):
            try:
                req = urllib.request.Request(url, data=urllib.parse.urlencode({"q": text}).encode(),
                                             headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=30) as r:
                    return "".join(seg[0] for seg in json.load(r)[0] if seg[0]).strip()
            except Exception:
                time.sleep(2 * (attempt + 1))
        return None

    out, i, dead = [], 0, 0
    while i < len(lines):
        chunk = [lines[i]]  # пачка строк до ~4000 символов в одном запросе
        while i + len(chunk) < len(lines) and sum(map(len, chunk)) + len(lines[i + len(chunk)]) < 4000:
            chunk.append(lines[i + len(chunk)])
        res = call("\n".join(chunk)) if dead < 3 else None  # 3 сбоя подряд — Google заблокирован, дальше не ждём
        dead = 0 if res else dead + 1
        parts = res.split("\n") if res else [None] * len(chunk)
        if res and len(parts) != len(chunk):  # пачка развалилась — переводим построчно
            parts = [call(l) for l in chunk]
        out += [(p or "").strip() or None for p in parts]  # None — строка не переведена
        i += len(chunk)
        on_progress(i, len(lines))
    return out


_translator = None  # (ключ, устройство, ctranslate2.Translator, sp_src, sp_tgt)


def offline(lines, key):
    global _translator
    import ctranslate2, sentencepiece as spm
    m = models.TRANSLATORS[key]
    path, kind = ensure_model("translate", key), m["kind"]
    on_stage("перевод")
    sp = lambda f: spm.SentencePieceProcessor(model_file=os.path.join(path, f))
    enc = {"marian": lambda s, t: s.encode(t, out_type=str) + ["</s>"],
           "nllb": lambda s, t: ["eng_Latn"] + s.encode(t, out_type=str) + ["</s>"],
           "madlad": lambda s, t: s.encode("<2ru> " + t, out_type=str) + ["</s>"]}[kind]
    prefix = [["rus_Cyrl"]] if kind == "nllb" else None
    for device, ctype in (("cuda", "int8_float16"), ("cpu", "int8")):
        if device == "cuda" and not cuda_ok():
            continue
        try:
            if not _translator or _translator[:2] != (key, device):
                _translator = None
                on_log(f"Загружаю переводчик {m['title']} на {device.upper()}...")
                files = ("source.spm", "target.spm") if kind == "marian" else (
                    ("sentencepiece.bpe.model",) * 2 if kind == "nllb" else ("spiece.model",) * 2)
                _translator = (key, device, ctranslate2.Translator(path, device=device, compute_type=ctype),
                               sp(files[0]), sp(files[1]))
            on_log(f"Перевод: {m['title']} (офлайн, {device.upper()})")
            _, _, tr, src, tgt = _translator
            out = []
            for i in range(0, len(lines), 32):
                batch = [enc(src, l) for l in lines[i:i + 32]]
                res = tr.translate_batch(batch, target_prefix=prefix and prefix * len(batch), beam_size=4,
                                         max_decoding_length=256, max_batch_size=32)
                toks = [r.hypotheses[0][1:] if prefix else r.hypotheses[0] for r in res]
                text = [tgt.decode(t).strip() for t in toks]
                if kind == "nllb":  # NLLB часто дописывает лишний " !" после вопроса: "Кто там? !"
                    text = [re.sub(r"([?.])\s+!+$", r"\1", t) for t in text]
                out += [t or None for t in text]
                on_progress(len(out), len(lines))
            return out
        except Exception as e:
            if device == "cpu" or not gpu_error(e):
                raise
            on_log(f"!! Видеокарта (CUDA) не сработала для перевода: {e}\n!! Перехожу на процессор.")
            _translator = None


def translate(lines, key):
    """Список русских строк или None, если перевести не удалось совсем."""
    if key == "google":
        on_stage("перевод")
        on_log("Перевод: Google Переводчик (онлайн)")
        out = google(lines)
    else:
        try:
            out = offline(lines, key)
        except Exception as e:
            on_log(f"!! Офлайн-переводчик {key} не сработал: {e}")
            return None
    failed = out.count(None)
    if failed == len(lines):
        return None
    if failed:
        on_log(f"Внимание: {failed} из {len(lines)} строк остались без перевода (оставлен английский текст).")
    return [t or l for t, l in zip(out, lines)]


def unload():
    """Освобождает модели (перед удалением файлов модели)."""
    global _whisper, _translator
    _whisper = _translator = None


def remux(video, info, keep, extra=(), opts=()):
    """Пересобирает файл в MKV: потоки keep из оригинала + по одному потоку из каждого файла extra.
    Сначала во временный файл, проверка ffprobe, затем оригинал — в Корзину. Возвращает путь к результату."""
    base = os.path.splitext(video)[0]
    target = base + ".mkv"
    if os.path.exists(target) and os.path.normcase(target) != os.path.normcase(video):
        raise RuntimeError(f"рядом уже есть файл {os.path.basename(target)}, не перезаписываю")
    tmp = base + ".tmp_subs.mkv"
    args = [FFMPEG, "-y", "-v", "error", "-i", video]
    for f in extra:
        args += ["-i", f]
    for s in keep:
        args += ["-map", f"0:{s['index']}"]
    for k in range(len(extra)):
        args += ["-map", str(k + 1)]
    args += ["-c", "copy"]
    for i, s in enumerate(keep):
        if s.get("codec_name") == "mov_text":  # MKV не умеет mov_text
            args += [f"-c:{i}", "srt"]
    args += list(opts) + [tmp]
    try:
        run(args)
        new = probe(tmp)
        d0, d1 = float(info["format"].get("duration", 0)), float(new["format"].get("duration", 0))
        if abs(d0 - d1) > max(2.0, d0 * 0.01):
            raise RuntimeError(f"длительность не совпала ({d0:.1f} с против {d1:.1f} с)")
        want = len(keep) + len(extra)
        if len(new["streams"]) != want:
            raise RuntimeError(f"ожидалось {want} потоков, получилось {len(new['streams'])}")
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    if len(video) < 250:
        from send2trash import send2trash
        send2trash(video)
    else:  # Корзина Windows молча удаляет файлы с путём длиннее 260 символов — не рискуем
        keep_as = base + ".original" + os.path.splitext(video)[1]
        os.replace(video, keep_as)
        on_log(f"Путь слишком длинный для Корзины, оригинал переименован: {os.path.basename(keep_as)}")
    os.replace(tmp, target)
    return target


def mux(video, info, en_srt, ru_srt, default_src=None, keep_old_ru=False):
    """Заменяет только дорожки с тегом SUBGEN; чужие дорожки остаются, но перестают быть «по умолчанию».
    en_srt=None — своя английская не добавляется (default_src — индекс исходной дорожки, которая станет основной);
    ru_srt=None и keep_old_ru — прежняя русская дорожка программы остаётся."""
    keep = [s for s in info["streams"] if s["codec_type"] != "data"
            and not (is_ours(s) and not (keep_old_ru and lang(s) == "rus"))]
    add = [(f, l, t) for f, l, t in ((en_srt, "eng", EN_TITLE), (ru_srt, "rus", RU_TITLE)) if f]
    opts = []
    for i, s in enumerate(keep):
        if s["codec_type"] == "subtitle":
            opts += [f"-disposition:{i}", disp(s, en_srt is None and s["index"] == default_src)]
    for k, (_, l, t) in enumerate(add):
        i = len(keep) + k
        opts += [f"-metadata:s:{i}", f"language={l}", f"-metadata:s:{i}", f"title={t}", f"-metadata:s:{i}", f"{TAG}=1",
                 f"-disposition:{i}", "default" if l == "eng" else "0"]
    return remux(video, info, keep, [f for f, _, _ in add], opts)


def process(video, use_embedded=False, whisper_key=None, translator=None):
    s = models.load_settings()
    whisper_key, translator = whisper_key or s["whisper"], translator or s["translator"]
    info = probe(video)
    base = os.path.splitext(video)[0]
    en_srt, ru_srt = base + ".en.srt", base + ".ru.srt"
    src = None
    if use_embedded:
        src = next((x for x in info["streams"] if x["codec_type"] == "subtitle" and not is_ours(x)
                    and x.get("codec_name") in TEXT_SUBS and lang(x) in ("eng", "en")), None)
        if src:
            on_log(f"Беру вшитые английские субтитры: дорожка #{src['index']} ({title(src) or src['codec_name']}).")
            run([FFMPEG, "-y", "-v", "error", "-i", video, "-map", f"0:{src['index']}", "-c:s", "srt", en_srt])
            cues = read_srt(en_srt)
        else:
            on_log("Вшитых английских текстовых субтитров нет — генерирую через Whisper.")
    if not src:
        cues = whisper(video, info, whisper_key)
    if not cues:
        raise RuntimeError("речь не найдена — субтитры пустые")
    write_srt(en_srt, cues)
    ru = translate([c[2] for c in cues], translator)
    if ru:
        write_srt(ru_srt, [(a, b, t) for (a, b, _), t in zip(cues, ru)])
    else:
        if os.path.exists(ru_srt):
            os.remove(ru_srt)  # старый файл с английским текстом не оставляем
        hint = ("Google Переводчик недоступен (вероятно, из-за VPN). Выключите VPN или выберите офлайн-переводчик\n"
                "!! на вкладке «Модели»" if translator == "google" else "офлайн-переводчик выдал ошибку (см. выше)")
        on_log(f"!! ПЕРЕВОД НЕ УДАЛСЯ: {hint}. Новая русская дорожка НЕ добавлена.\n"
               "!! Запустите обработку этого .mkv ещё раз — дорожки программы заменятся.")
    on_log(f"Субтитры сохранены: {os.path.basename(en_srt)}" + (f", {os.path.basename(ru_srt)}" if ru else ""))
    on_log("Вшиваю дорожки в MKV...")
    on_stage("вшивание")
    old_ru = not ru and any(is_ours(x) and lang(x) == "rus" for x in info["streams"])
    if old_ru:
        on_log("Прежняя русская дорожка программы оставлена.")
    return mux(video, info, None if src else en_srt, ru_srt if ru else None, src["index"] if src else None, old_ru)


def collect(paths):
    videos = []
    for p in paths:
        if os.path.isdir(p):
            videos += sorted(os.path.join(r, f) for r, _, fs in os.walk(p) for f in fs
                             if os.path.splitext(f)[1].lower() in VIDEO_EXT and ".tmp_subs." not in f and ".original." not in f)
        elif os.path.splitext(p)[1].lower() in VIDEO_EXT:
            videos.append(os.path.abspath(p))
        else:
            on_log(f"Пропускаю (не видео): {p}")
    return videos
