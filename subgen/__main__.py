"""Консольный режим: python -m subgen ВИДЕО|ПАПКА ... [--embedded] [--source auto|КОД] [--target КОД] [--model M] [--translator T]"""
import argparse, os, sys

from . import core, models
from .i18n import t


def main():
    p = argparse.ArgumentParser(prog="subgen", description=t("cli.desc"))
    p.add_argument("paths", nargs="*", help=t("cli.paths"))
    p.add_argument("--embedded", "--embedded-en", action="store_true",
                   help=t("cli.embedded"))
    p.add_argument("--source", default="auto", choices=["auto", *models.LANGS],
                   help=t("cli.source"))
    p.add_argument("--target", choices=list(models.LANGS), help=t("cli.target"))
    p.add_argument("--model", choices=list(models.WHISPER), help=t("cli.model"))
    p.add_argument("--translator", choices=list(models.TRANSLATORS), help=t("cli.translator"))
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
    core.on_stage = lambda s: (last.__setitem__(0, -1), print(f"-- {t('stage.' + s)}"))
    videos = core.collect(a.paths)
    if not videos:
        print(t("cli.nothing"))
        return
    ok, bad = [], []
    for n, v in enumerate(videos, 1):
        print("\n" + t("cli.file", n=n, total=len(videos), name=os.path.basename(v)))
        try:
            out = core.process(v, a.embedded, a.model, a.translator, a.source, a.target)
            print(t("log.done", path=out))
            ok.append(out)
        except Exception as e:
            print(t("log.error", error=e))
            bad.append(v)
    print("\n" + t("log.summary", ok=len(ok), bad=len(bad)))
    for v in bad:
        print(t("cli.failed_item", path=v))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
