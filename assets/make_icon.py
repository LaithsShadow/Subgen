"""Рисует иконку Subgen: тёмный скруглённый квадрат и две «строки субтитров». Запуск: python assets/make_icon.py"""
import os

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256]


def draw(px):
    s = px * 4  # рисуем крупно и уменьшаем — гладкие края
    small = px < 48
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    pad = 0 if small else s * 0.04
    r = s * (0.18 if small else 0.22)
    # фон: вертикальный градиент угольного цвета
    grad = Image.new("RGBA", (s, s))
    gd = ImageDraw.Draw(grad)
    for y in range(s):
        t = y / s
        gd.line([(0, y), (s, y)], fill=(int(36 - 14 * t), int(40 - 15 * t), int(48 - 17 * t), 255))
    mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(mask).rounded_rectangle([pad, pad, s - pad - 1, s - pad - 1], r, fill=255)
    img.paste(grad, (0, 0), mask)
    ov = Image.new("RGBA", (s, s), (0, 0, 0, 0))  # полупрозрачные детали — отдельным слоем, иначе альфа затрёт фон
    d = ImageDraw.Draw(ov)
    if not small:  # тонкая светлая кромка
        d.rounded_rectangle([pad, pad, s - pad - 1, s - pad - 1], r, outline=(255, 255, 255, 28), width=max(2, s // 128))
    # «кадр»: тонкая рамка экрана в верхней части
    if px >= 48:
        fx0, fy0, fx1, fy1 = s * 0.20, s * 0.20, s * 0.80, s * 0.52
        d.rounded_rectangle([fx0, fy0, fx1, fy1], s * 0.05, outline=(255, 255, 255, 40), width=max(2, s // 90))
        # треугольник «play»
        cx, cy, h = s * 0.5, (fy0 + fy1) / 2, s * 0.10
        d.polygon([(cx - h * 0.45, cy - h * 0.55), (cx - h * 0.45, cy + h * 0.55), (cx + h * 0.6, cy)], fill=(255, 255, 255, 70))
    img = Image.alpha_composite(img, ov)
    d = ImageDraw.Draw(img)
    # строки субтитров: светлая (EN) и акцентная (RU)
    bh = s * (0.15 if small else 0.085)
    y1 = s * (0.30 if small else 0.60)
    y2 = y1 + bh + s * (0.12 if small else 0.06)
    w1, w2 = (0.70, 0.50) if small else (0.62, 0.44)
    d.rounded_rectangle([s * (1 - w1) / 2, y1, s * (1 + w1) / 2, y1 + bh], bh / 2, fill=(236, 239, 244, 255))
    d.rounded_rectangle([s * (1 - w2) / 2, y2, s * (1 + w2) / 2, y2 + bh], bh / 2, fill=(77, 141, 255, 255))
    return img.resize((px, px), Image.LANCZOS)


if __name__ == "__main__":
    imgs = [draw(p) for p in SIZES]
    big = imgs[-1]
    big.save(os.path.join(HERE, "subgen.png"))
    big.save(os.path.join(HERE, "subgen.ico"), sizes=[(p, p) for p in SIZES], append_images=imgs[:-1])
    # превью всех размеров рядом — для проверки глазами
    sheet = Image.new("RGBA", (sum(SIZES) + 10 * len(SIZES) + 10, 276), (245, 245, 245, 255))
    x = 10
    for p, im in zip(SIZES, imgs):
        sheet.paste(im, (x, 266 - p), im)
        x += p + 10
    sheet.save(os.path.join(os.environ.get("TEMP", HERE), "subgen-icon-sheet.png"))
    print("ok")
