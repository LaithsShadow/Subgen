"""Быстрая проверка вшивания и менеджера дорожек без моделей: python tests/test_mux.py (нужен ffmpeg)."""
import os, shutil, subprocess, sys, tempfile, types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.modules["send2trash"] = types.SimpleNamespace(send2trash=os.remove)  # в тесте оригинал не отправляем в Корзину
from subgen import core, tracks

d = tempfile.mkdtemp(prefix="subgen-test-")
srt = lambda name, text: (open(os.path.join(d, name), "w", encoding="utf-8").write(
    f"1\n00:00:00,500 --> 00:00:02,000\n{text}\n\n"), os.path.join(d, name))[1]
video = os.path.join(d, "clip.mp4")
subprocess.run([core.FFMPEG, "-v", "error", "-f", "lavfi", "-i", "color=s=160x90:d=3", "-f", "lavfi", "-i", "sine=d=3",
                "-i", srt("old.srt", "WRONG"), "-map", "0", "-map", "1", "-map", "2", "-c:v", "libx264", "-c:a", "aac",
                "-c:s", "mov_text", "-metadata:s:s:0", "language=eng", "-disposition:s:0", "default", video], check=True)


def rows(path):
    return [(r["type"], r["language"], r["title"], r["default"], r["ours"]) for r in tracks.streams(path)[1]]


# 1. первый запуск: чужая дорожка остаётся (mov_text -> srt), наша английская — по умолчанию
out = core.mux(video, core.probe(video), srt("en.srt", "Hello"), srt("ru.srt", "Привет"))
assert out.endswith(".mkv") and not os.path.exists(video)
r = rows(out)
assert r[2] == ("subtitle", "eng", "", False, False), r
assert r[3] == ("subtitle", "eng", core.EN_TITLE, True, True), r
assert r[4] == ("subtitle", "rus", core.RU_TITLE, False, True), r

# 2. повторный запуск заменяет только свои дорожки
out = core.mux(out, core.probe(out), srt("en.srt", "Hello again"), srt("ru.srt", "Снова привет"))
assert len(rows(out)) == 5 and [x[4] for x in rows(out)].count(True) == 2, rows(out)

# 3. сбой перевода: прежняя русская дорожка программы сохраняется
out = core.mux(out, core.probe(out), srt("en.srt", "Third"), None, keep_old_ru=True)
assert sorted(x[2] for x in rows(out) if x[4]) == sorted([core.EN_TITLE, core.RU_TITLE]), rows(out)

# 4. менеджер дорожек: переименование, язык, default, удаление; видео удалить нельзя
info = core.probe(out)
out = tracks.apply(out, info, {2: {"title": "Old", "language": "jpn", "default": True}, 1: {"delete": True}})
r = rows(out)
assert [x[0] for x in r].count("audio") == 0 and r[1][:4] == ("subtitle", "jpn", "Old", True), r
for bad in ({0: {"delete": True}}, {1: {"language": "english"}}):
    try:
        tracks.apply(out, core.probe(out), bad)
        raise AssertionError(f"должно было отклониться: {bad}")
    except ValueError:
        pass
shutil.rmtree(d)
print("OK")
