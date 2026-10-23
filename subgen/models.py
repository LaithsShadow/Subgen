"""Каталог моделей Whisper и офлайн-переводчиков: где лежат, скачаны ли, загрузка с прогрессом, удаление."""
import fnmatch, glob, json, os, shutil, threading

# Обычная HTTP-загрузка пишет файл постепенно — по размеру папки виден прогресс (xet пишет файл целиком в конце)
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

DATA = os.path.join(os.environ["LOCALAPPDATA"], "Subgen")
WHISPER_DIR = os.path.join(DATA, "models", "whisper")        # формат кэша Hugging Face (models--org--name)
TRANSLATE_DIR = os.path.join(DATA, "models", "translate")    # по папке на модель
SETTINGS = os.path.join(DATA, "settings.json")
DEFAULTS = {"whisper": "large-v3-turbo", "translator": "google"}

MB = 1024 ** 2
WHISPER_FILES = ["config.json", "preprocessor_config.json", "model.bin", "tokenizer.json", "vocabulary.*"]
# ключ: (репозиторий, примерный размер, подпись)
WHISPER = {
    "tiny":           ("Systran/faster-whisper-tiny", 75 * MB, "самая быстрая, низкое качество"),
    "tiny.en":        ("Systran/faster-whisper-tiny.en", 75 * MB, "только английский"),
    "base":           ("Systran/faster-whisper-base", 145 * MB, "быстрая, слабое качество"),
    "base.en":        ("Systran/faster-whisper-base.en", 145 * MB, "только английский"),
    "small":          ("Systran/faster-whisper-small", 485 * MB, "для слабых ПК без видеокарты"),
    "small.en":       ("Systran/faster-whisper-small.en", 485 * MB, "только английский"),
    "medium":         ("Systran/faster-whisper-medium", 1530 * MB, "хорошее качество, медленнее"),
    "medium.en":      ("Systran/faster-whisper-medium.en", 1530 * MB, "только английский"),
    "large-v2":       ("Systran/faster-whisper-large-v2", 3090 * MB, "очень точная, медленная"),
    "large-v3":       ("Systran/faster-whisper-large-v3", 3090 * MB, "самая точная, медленная"),
    "large-v3-turbo": ("mobiuslabsgmbh/faster-whisper-large-v3-turbo", 1540 * MB, "рекомендуется: точная и быстрая"),
}
# kind: как кодировать текст для модели (см. core.Translator)
TRANSLATORS = {
    "google":    dict(title="Google Переводчик (онлайн)", size=0, note="по умолчанию, нужен интернет"),
    "opus-mt":   dict(title="OPUS-MT en→ru", size=80 * MB, kind="marian", note="маленькая и быстрая",
                      repo="manancode/opus-mt-en-ru-ctranslate2-android",
                      files=["config.json", "model.bin", "shared_vocabulary.json", "source.spm", "target.spm"]),
    "nllb-600m": dict(title="NLLB-200 600M", size=600 * MB, kind="nllb", note="хорошее качество",
                      repo="JustFrederik/nllb-200-distilled-600M-ct2-int8",
                      files=["config.json", "model.bin", "shared_vocabulary.txt", "sentencepiece.bpe.model"]),
    "nllb-1.3b": dict(title="NLLB-200 1.3B", size=1330 * MB, kind="nllb", note="лучший офлайн-вариант",
                      repo="JustFrederik/nllb-200-distilled-1.3B-ct2-int8",
                      files=["config.json", "model.bin", "shared_vocabulary.txt", "sentencepiece.bpe.model"]),
    "madlad-3b": dict(title="MADLAD-400 3B", size=2820 * MB, kind="madlad", note="крупная, нужна видеокарта",
                      repo="Nextcloud-AI/madlad400-3b-mt-ct2-int8",
                      files=["config.json", "model.bin", "shared_vocabulary.json", "spiece.model"]),
}


def load_settings():
    try:
        with open(SETTINGS, encoding="utf-8") as f:
            s = json.load(f)
    except (OSError, ValueError):
        s = {}
    s = {**DEFAULTS, **{k: v for k, v in s.items() if k in DEFAULTS}}
    if s["whisper"] not in WHISPER:
        s["whisper"] = DEFAULTS["whisper"]
    if s["translator"] not in TRANSLATORS:
        s["translator"] = DEFAULTS["translator"]
    return s


def save_settings(**changes):
    s = {**load_settings(), **changes}
    os.makedirs(DATA, exist_ok=True)
    with open(SETTINGS, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=2)
    return s


def _folder(kind, key):
    if kind == "whisper":
        return os.path.join(WHISPER_DIR, "models--" + WHISPER[key][0].replace("/", "--"))
    return os.path.join(TRANSLATE_DIR, key)


def local_path(kind, key):
    """Папка готовой модели или None, если не скачана."""
    if kind == "whisper":
        hits = glob.glob(os.path.join(_folder(kind, key), "snapshots", "*", "model.bin"))
        return os.path.dirname(hits[0]) if hits else None
    if key == "google":
        return "google"
    p = _folder(kind, key)
    return p if all(glob.glob(os.path.join(p, f)) for f in TRANSLATORS[key]["files"]) else None


def size(kind, key):
    return WHISPER[key][1] if kind == "whisper" else TRANSLATORS[key]["size"]


def fmt_size(n):
    return f"{n / 1024 ** 3:.1f} ГБ" if n >= 1024 ** 3 else f"{n / MB:.0f} МБ"


def _dir_size(path):
    return sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(path) for f in fs
               if os.path.exists(os.path.join(r, f)))


def download(kind, key, on_progress=lambda done, total: None):
    """Скачивает модель (докачивает прерванную), прогресс — по размеру папки. Возвращает путь к модели."""
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    from huggingface_hub import HfApi, snapshot_download
    repo, files = (WHISPER[key][0], WHISPER_FILES) if kind == "whisper" else (TRANSLATORS[key]["repo"], TRANSLATORS[key]["files"])
    folder = _folder(kind, key)
    try:
        info = HfApi().model_info(repo, files_metadata=True)
        total = sum(f.size or 0 for f in info.siblings if any(fnmatch.fnmatch(f.rfilename, p) for p in files))
    except Exception:
        total = size(kind, key)
    done = threading.Event()

    def poll():
        while not done.wait(0.5):
            on_progress(min(_dir_size(folder) if os.path.isdir(folder) else 0, total), total)

    threading.Thread(target=poll, daemon=True).start()
    try:
        if kind == "whisper":
            snapshot_download(repo, allow_patterns=files, cache_dir=WHISPER_DIR)
        else:
            snapshot_download(repo, allow_patterns=files, local_dir=folder)
    finally:
        done.set()
    on_progress(total, total)
    path = local_path(kind, key)
    if not path:
        raise RuntimeError(f"модель {key} скачалась не полностью")
    return path


def delete(kind, key):
    folder = _folder(kind, key)
    if os.path.isdir(folder):
        shutil.rmtree(folder)
