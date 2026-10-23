"""Перевод интерфейса: t("ключ", **поля) из subgen/locales/<код>.json; чего нет — берётся из en.json."""
import ctypes, json, locale, os

DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "locales")
SETTINGS = os.path.join(os.environ["LOCALAPPDATA"], "Subgen", "settings.json")
# шрифт под письменность (остальным хватает шрифта customtkinter); Tk сам подставляет недостающие глифы
FONTS = {"ja": "Yu Gothic UI", "ko": "Malgun Gothic", "zh": "Microsoft YaHei UI", "th": "Leelawadee UI",
         "hi": "Nirmala UI", "bn": "Nirmala UI", "ta": "Nirmala UI",
         "ar": "Segoe UI", "fa": "Segoe UI", "ur": "Segoe UI", "he": "Segoe UI", "ka": "Segoe UI", "hy": "Segoe UI"}


def available():
    return sorted(f[:-5] for f in os.listdir(DIR) if f.endswith(".json"))


def load(code):
    try:
        with open(os.path.join(DIR, code + ".json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def system_lang():
    """Язык интерфейса Windows, если для него есть перевод, иначе английский."""
    try:
        code = (locale.windows_locale.get(ctypes.windll.kernel32.GetUserDefaultUILanguage()) or "").split("_")[0]
    except Exception:
        code = ""
    code = {"nb": "no", "nn": "no", "fil": "tl"}.get(code, code)
    return code if code in available() else "en"


def current():
    try:
        with open(SETTINGS, encoding="utf-8") as f:
            code = json.load(f).get("ui_lang")
    except (OSError, ValueError, AttributeError):
        code = None
    return code if code in available() else system_lang()


LANG = current()
_en, _cur = load("en"), load(LANG)


def t(key, /, **kw):  # / — поле {key} в строках не путается с аргументом
    s = _cur.get(key) or _en.get(key) or key
    return s.format(**kw) if kw else s


def font():
    return FONTS.get(LANG)
