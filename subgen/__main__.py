"""Консольный режим: python -m subgen ВИДЕО|ПАПКА ... [--embedded] [--source auto|КОД] [--target КОД] [--model M] [--translator T]"""
import argparse, os, sys

from . import core, models


def main():
    p = argparse.ArgumentParser(prog="subgen", description="Субтитры на языке оригинала (Whisper) и перевод, вшиваются в MKV.")
    p.add_argument("paths", nargs="*", help="видеофайлы или папки")
    p.add_argument("--embedded", "--embedded-en", action="store_true",
                   help="использовать вшитые субтитры на языке оригинала (без генерации)")
    p.add_argument("--source", default="auto", choices=["auto", *models.LANGS],
                   help="язык оригинала (по умолчанию auto — определяет Whisper)")
    p.add_argument("--target", choices=list(models.LANGS), help="язык перевода (по умолчанию — из настроек)")
    p.add_argument("--model", choices=list(models.WHISPER), help="модель Whisper (по умолчанию — из настроек)")
    p.add_argument("--translator", choices=list(models.TRANSLATORS), help="переводчик (по умолчанию — из настроек)")
    a = p.parse_args()
    if not core.FFMPEG:
        sys.exit(core.NO_FFMPEG)
    last = [-1]

    def progress(done, total):  # одна строка процентов вместо tqdm
        pct = done * 100 // max(total, 1)
        if pct != last[0]:
            last[0] = pct
            print(f"\r  {pct}%", end="\n" if pct >= 100 else "", flush=True)

    core.on_progress = progress
    core.on_stage = lambda s: (last.__setitem__(0, -1), print(f"-- {s}"))
    videos = core.collect(a.paths)
    if not videos:
        print("Перетащите видеофайл или папку с сериями на ярлык Subgen или укажите их в командной строке.")
        return
    ok, bad = [], []
    for n, v in enumerate(videos, 1):
        print(f"\n=== Файл {n} из {len(videos)}: {os.path.basename(v)} ===")
        try:
            out = core.process(v, a.embedded, a.model, a.translator, a.source, a.target)
            print(f"Готово: {out}")
            ok.append(out)
        except Exception as e:
            print(f"ОШИБКА: {e}\nОригинал не тронут.")
            bad.append(v)
    print(f"\n===== Итог: успешно {len(ok)}, с ошибками {len(bad)} =====")
    for v in bad:
        print(f"  не удалось: {v}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
