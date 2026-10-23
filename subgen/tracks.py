"""Менеджер дорожек: список потоков файла и правка названия, языка, флага «по умолчанию», удаление аудио/субтитров."""
import re

from . import core

TYPES = {"video": "видео", "audio": "аудио", "subtitle": "субтитры", "attachment": "вложение", "data": "данные"}
DELETABLE = {"audio", "subtitle"}  # видео не удаляем никогда — значит, последнее видео всегда остаётся


def streams(video):
    info = core.probe(video)
    rows = [dict(index=s["index"], type=s["codec_type"], codec=s.get("codec_name", "?"), language=core.lang(s),
                 title=core.title(s), default=bool(s.get("disposition", {}).get("default")), ours=core.is_ours(s))
            for s in info["streams"]]
    return info, rows


def apply(video, info, edits):
    """edits: {индекс: {"title", "language", "default", "delete"}} — только изменённые поля. Возвращает новый путь."""
    for i, e in edits.items():
        if e.get("language") and not re.fullmatch(r"[a-z]{3}", e["language"]):
            raise ValueError(f"дорожка #{i}: язык — трёхбуквенный код ISO 639-2 (eng, rus, jpn), а не «{e['language']}»")
    by_index = {s["index"]: s for s in info["streams"]}
    for i, e in edits.items():
        if e.get("delete") and by_index[i]["codec_type"] not in DELETABLE:
            raise ValueError(f"дорожку #{i} ({TYPES.get(by_index[i]['codec_type'])}) удалять нельзя")
    keep = [s for s in info["streams"] if s["codec_type"] != "data" and not edits.get(s["index"], {}).get("delete")]
    if not any(s["codec_type"] == "video" for s in keep) and any(s["codec_type"] == "video" for s in info["streams"]):
        raise ValueError("нельзя удалить последнюю видеодорожку")
    opts = []
    for out, s in enumerate(keep):
        e = edits.get(s["index"], {})
        if "title" in e:
            opts += [f"-metadata:s:{out}", f"title={e['title']}"]
        if "language" in e:
            opts += [f"-metadata:s:{out}", f"language={e['language'] or 'und'}"]
        if "default" in e:
            opts += [f"-disposition:{out}", core.disp(s, e["default"])]
    return core.remux(video, info, keep, opts=opts)
