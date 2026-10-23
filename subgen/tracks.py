"""Менеджер дорожек: список потоков файла и правка названия, языка, флага «по умолчанию», удаление аудио/субтитров."""
import re

from . import core
from .i18n import t

TYPES = {k: t("type." + k) for k in ("video", "audio", "subtitle", "attachment", "data")}
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
            raise ValueError(t("err.lang_code", i=i, lang=e["language"]))
    by_index = {s["index"]: s for s in info["streams"]}
    for i, e in edits.items():
        if e.get("delete") and by_index[i]["codec_type"] not in DELETABLE:
            raise ValueError(t("err.cant_delete", i=i, type=TYPES.get(by_index[i]["codec_type"])))
    keep = [s for s in info["streams"] if s["codec_type"] != "data" and not edits.get(s["index"], {}).get("delete")]
    if not any(s["codec_type"] == "video" for s in keep) and any(s["codec_type"] == "video" for s in info["streams"]):
        raise ValueError(t("err.last_video"))
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
