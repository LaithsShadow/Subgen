"""Каталог моделей Whisper и офлайн-переводчиков: где лежат, скачаны ли, загрузка с прогрессом, удаление."""
import fnmatch, glob, json, os, shutil, threading

# Обычная HTTP-загрузка пишет файл постепенно — по размеру папки виден прогресс (xet пишет файл целиком в конце)
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

DATA = os.path.join(os.environ["LOCALAPPDATA"], "Subgen")
WHISPER_DIR = os.path.join(DATA, "models", "whisper")        # формат кэша Hugging Face (models--org--name)
TRANSLATE_DIR = os.path.join(DATA, "models", "translate")    # по папке на модель
SETTINGS = os.path.join(DATA, "settings.json")
DEFAULTS = {"whisper": "large-v3-turbo", "translator": "google", "target": "ru"}

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

# Языки: код Whisper (ISO 639-1) -> (ISO 639-2/B для MKV, код FLORES-200 для NLLB, название, самоназвание)
LANGS = {
    "en": ("eng", "eng_Latn", "English", "English"),
    "ru": ("rus", "rus_Cyrl", "Russian", "Русский"),
    "uk": ("ukr", "ukr_Cyrl", "Ukrainian", "Українська"),
    "be": ("bel", "bel_Cyrl", "Belarusian", "Беларуская"),
    "de": ("ger", "deu_Latn", "German", "Deutsch"),
    "fr": ("fre", "fra_Latn", "French", "Français"),
    "es": ("spa", "spa_Latn", "Spanish", "Español"),
    "it": ("ita", "ita_Latn", "Italian", "Italiano"),
    "pt": ("por", "por_Latn", "Portuguese", "Português"),
    "nl": ("dut", "nld_Latn", "Dutch", "Nederlands"),
    "pl": ("pol", "pol_Latn", "Polish", "Polski"),
    "cs": ("cze", "ces_Latn", "Czech", "Čeština"),
    "sk": ("slo", "slk_Latn", "Slovak", "Slovenčina"),
    "sl": ("slv", "slv_Latn", "Slovenian", "Slovenščina"),
    "hr": ("hrv", "hrv_Latn", "Croatian", "Hrvatski"),
    "sr": ("srp", "srp_Cyrl", "Serbian", "Српски"),
    "bg": ("bul", "bul_Cyrl", "Bulgarian", "Български"),
    "ro": ("rum", "ron_Latn", "Romanian", "Română"),
    "hu": ("hun", "hun_Latn", "Hungarian", "Magyar"),
    "el": ("gre", "ell_Grek", "Greek", "Ελληνικά"),
    "tr": ("tur", "tur_Latn", "Turkish", "Türkçe"),
    "sv": ("swe", "swe_Latn", "Swedish", "Svenska"),
    "no": ("nor", "nob_Latn", "Norwegian", "Norsk"),
    "da": ("dan", "dan_Latn", "Danish", "Dansk"),
    "fi": ("fin", "fin_Latn", "Finnish", "Suomi"),
    "et": ("est", "est_Latn", "Estonian", "Eesti"),
    "lv": ("lav", "lvs_Latn", "Latvian", "Latviešu"),
    "lt": ("lit", "lit_Latn", "Lithuanian", "Lietuvių"),
    "ka": ("geo", "kat_Geor", "Georgian", "ქართული"),
    "hy": ("arm", "hye_Armn", "Armenian", "Հայերեն"),
    "az": ("aze", "azj_Latn", "Azerbaijani", "Azərbaycan"),
    "kk": ("kaz", "kaz_Cyrl", "Kazakh", "Қазақ"),
    "uz": ("uzb", "uzn_Latn", "Uzbek", "Oʻzbek"),
    "he": ("heb", "heb_Hebr", "Hebrew", "עברית"),
    "ar": ("ara", "arb_Arab", "Arabic", "العربية"),
    "fa": ("per", "pes_Arab", "Persian", "فارسی"),
    "hi": ("hin", "hin_Deva", "Hindi", "हिन्दी"),
    "bn": ("ben", "ben_Beng", "Bengali", "বাংলা"),
    "ur": ("urd", "urd_Arab", "Urdu", "اردو"),
    "ta": ("tam", "tam_Taml", "Tamil", "தமிழ்"),
    "th": ("tha", "tha_Thai", "Thai", "ไทย"),
    "vi": ("vie", "vie_Latn", "Vietnamese", "Tiếng Việt"),
    "id": ("ind", "ind_Latn", "Indonesian", "Bahasa Indonesia"),
    "ms": ("may", "zsm_Latn", "Malay", "Bahasa Melayu"),
    "tl": ("tgl", "tgl_Latn", "Tagalog", "Tagalog"),
    "ja": ("jpn", "jpn_Jpan", "Japanese", "日本語"),
    "ko": ("kor", "kor_Hang", "Korean", "한국어"),
    "zh": ("chi", "zho_Hans", "Chinese", "中文"),
}


def lang_from_tag(t):
    """Код языка по тегу дорожки: en, eng, ger/deu, fre/fra... или None."""
    t = (t or "").lower()
    return next((c for c, v in LANGS.items() if t in (c, v[0], v[1][:3])), {"fas": "fa", "msa": "ms"}.get(t))


def supports(translator, src, tgt):
    """Умеет ли переводчик src -> tgt (src="auto" — язык ещё не определён)."""
    kind = TRANSLATORS[translator].get("kind")
    if kind == "marian":
        return src in ("auto", "en") and tgt == "ru"
    if kind == "nllb":
        return src == "auto" or src in LANGS
    return True


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
    if s["target"] not in LANGS:
        s["target"] = DEFAULTS["target"]
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
