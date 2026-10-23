"""Машинный перевод интерфейса: subgen/locales/en.json -> <код>.json для языков из models.LANGS.

    python tools/gen_locales.py [--engine google|nllb-1.3b|...] [--only de,ja] [--force]
    python tools/gen_locales.py --check     # те же ключи, те же {поля}, нет пустых значений

en.json и ru.json пишутся вручную и не перезаписываются. Готовые файлы не трогаются без --force.
Строку, у которой после перевода потерялись {поля}, оставляет английской и сообщает об этом.
"""
import argparse, json, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from subgen import core, i18n, models

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

MANUAL = {"en", "ru"}
PH = re.compile(r"\{(\w+)\}")
LINE = re.compile(r"^([\s·!=]*)(.*?)([\s=]*)$")  # «!! », «=== », « · » — не переводим, приклеиваем обратно
# не переводятся: {поля}, названия, команды и знаки, которые офлайн-модели превращают в «⁇»
KEEP = re.compile(r"\{\w+\}|winget install --id Gyan\.FFmpeg -e|install\.cmd|ISO 639-2 \(eng, rus, jpn\)|"
                  r"MKV, MP4, AVI, WebM, MOV|large-v3-turbo|OPUS-MT|Whisper|Subgen|Google|NVIDIA|CUDA|ffmpeg|MKV|"
                  r"\.mkv|\.en\b|[—→…“”«»#~%]")


def check():
    en, bad = i18n.load("en"), []
    for code in i18n.available():
        loc = i18n.load(code)
        if set(loc) != set(en):
            bad.append(f"{code}: ключи отличаются: {sorted(set(en) ^ set(loc))}")
        for k, v in loc.items():
            if not str(v).strip() or "⁇" in v:  # «⁇» — символ, которого нет в словаре офлайн-модели
                bad.append(f"{code}: {k} пустой или с «⁇»")
            elif k in en and sorted(PH.findall(v)) != sorted(PH.findall(en[k])):
                bad.append(f"{code}: {k} — поля {PH.findall(v)} вместо {PH.findall(en[k])}")
    print("\n".join(bad) or f"OK: {len(i18n.available())} языков, {len(en)} строк")
    return not bad


def generate(code, engine, en):
    pieces = []  # (ключ, номер строки, начало, текст, конец)
    for k, v in en.items():
        for n, line in enumerate(v.split("\n")):
            lead, text, trail = LINE.match(line).groups()
            kept = KEEP.findall(text)  # {path} -> {0}: имена полей, команды и названия переводчик норовит перевести
            n_kept = iter(range(len(kept)))
            text = KEEP.sub(lambda m: "{%d}" % next(n_kept), text)
            pieces.append((k, n, lead, text, trail, kept))
    todo = [p for p in pieces if re.search(r"[^\W\d_]", re.sub(r"\{\d+\}", "", p[3]))]
    out = core.translate([p[3] for p in todo], engine, "en", code)
    if not out:
        raise RuntimeError(f"{code}: перевод не удался")
    done = dict(zip(map(id, todo), out))
    lines, lost = {}, []
    for p in pieces:
        k, n, lead, src, trail, kept = p
        text = done.get(id(p), src).strip()
        for end in ".:":  # «Stop» -> «Hört auf.»: лишняя точка или двоеточие у коротких подписей
            if text.endswith(end) and not text.endswith("..") and not src.endswith(end):
                text = text[:-1].rstrip()
        if sorted(re.findall(r"\{\s*(\d+)\s*\}", text)) != sorted(str(i) for i in range(len(kept))):
            text = None  # защищённый кусок потерялся или задвоился
        else:
            text = lead + re.sub(r"\{\s*(\d+)\s*\}", lambda m: kept[int(m[1])], text) + trail
        lines.setdefault(k, []).append(text)
    res = {}
    for k, v in en.items():
        res[k] = None if None in lines[k] else "\n".join(lines[k])
        if not res[k] or "⁇" in res[k] or sorted(PH.findall(res[k])) != sorted(PH.findall(v)):
            res[k] = v
            lost.append(k)
    if lost:
        print(f"  {code}: оставлено по-английски (потерялись поля или «⁇»): {', '.join(lost)}")
    return res


def main():
    a = argparse.ArgumentParser()
    a.add_argument("--engine", default="google", choices=list(models.TRANSLATORS))
    a.add_argument("--only", help="коды через запятую")
    a.add_argument("--force", action="store_true", help="перезаписать готовые файлы")
    a.add_argument("--check", action="store_true")
    a = a.parse_args()
    if a.check:
        sys.exit(0 if check() else 1)
    core.on_log = lambda *x: print(*x) if "!!" in " ".join(map(str, x)) else None
    en = i18n.load("en")
    for code in (a.only.split(",") if a.only else models.LANGS):
        path = os.path.join(i18n.DIR, code + ".json")
        if code in MANUAL or (os.path.exists(path) and not a.force):
            continue
        print(f"{code} ({models.LANGS[code][2]})...")
        res = {**generate(code, a.engine, en), "lang.name": models.LANGS[code][3]}  # самоназвание — для установщика
        with open(path, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=2)
            f.write("\n")
    check()


if __name__ == "__main__":
    main()
