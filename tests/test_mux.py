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


def ours(path):
    return [(core.lang(s), core.title(s), core.role(s)) for s in core.probe(path)["streams"] if core.is_ours(s)]


# 1. первый запуск: чужая дорожка остаётся (mov_text -> srt), наша дорожка оригинала — по умолчанию
out = core.mux(video, core.probe(video), srt("en.srt", "Hello"), srt("ru.srt", "Привет"), "en", "ru")
assert out.endswith(".mkv") and not os.path.exists(video)
r = rows(out)
assert r[2] == ("subtitle", "eng", "", False, False), r
assert r[3] == ("subtitle", "eng", "English (Whisper)", True, True), r
assert r[4] == ("subtitle", "rus", "Русский", False, True), r
assert ours(out) == [("eng", "English (Whisper)", "orig"), ("rus", "Русский", "trans")], ours(out)

# 2. повторный запуск с другой парой заменяет только свои дорожки (роль по тегу, не по языку)
out = core.mux(out, core.probe(out), srt("ja.srt", "こんにちは"), srt("de.srt", "Hallo"), "ja", "de")
assert len(rows(out)) == 5 and ours(out) == [("jpn", "Japanese (Whisper)", "orig"), ("ger", "Deutsch", "trans")], rows(out)

# 3. сбой перевода: прежний перевод программы на тот же язык сохраняется, на другой — нет
out = core.mux(out, core.probe(out), srt("ja.srt", "Third"), None, "ja", "de", keep_old_trans=True)
assert ours(out) == [("ger", "Deutsch", "trans"), ("jpn", "Japanese (Whisper)", "orig")], ours(out)
out = core.mux(out, core.probe(out), srt("ja.srt", "Fourth"), None, "ja", "fr", keep_old_trans=True)
assert ours(out) == [("jpn", "Japanese (Whisper)", "orig")], ours(out)

# 3b. файл старой версии (SUBGEN=1 без SUBGEN_ROLE): eng — оригинал, rus — перевод; обе заменяются
old = os.path.join(d, "old.mkv")
subprocess.run([core.FFMPEG, "-v", "error", "-i", out, "-i", srt("o1.srt", "Old en"), "-i", srt("o2.srt", "Старый"),
                "-map", "0:v", "-map", "0:a", "-map", "1", "-map", "2", "-c", "copy",
                "-metadata:s:s:0", "language=eng", "-metadata:s:s:0", "SUBGEN=1",
                "-metadata:s:s:1", "language=rus", "-metadata:s:s:1", "SUBGEN=1", old], check=True)
os.remove(out)
assert [x[2] for x in ours(old)] == ["orig", "trans"], ours(old)
out = core.mux(old, core.probe(old), srt("en.srt", "New"), None, "en", "ru", keep_old_trans=True)
assert ours(out) == [("rus", "", "trans"), ("eng", "English (Whisper)", "orig")], ours(out)

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
