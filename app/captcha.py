import hmac
import io
import random
import secrets
import threading
import time

from flask import session
from PIL import Image, ImageDraw, ImageFont

CAPTCHA_LENGTH = 4
CAPTCHA_TTL_SECONDS = 5 * 60
CAPTCHA_MAX_ENTRIES = 2000
CAPTCHA_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

_lock = threading.Lock()
_challenges = {}


def generate_code():
    return "".join(secrets.choice(CAPTCHA_ALPHABET) for _ in range(CAPTCHA_LENGTH))


def _prune(now):
    expired = [token for token, (_, expires) in _challenges.items() if expires <= now]
    for token in expired:
        _challenges.pop(token, None)


def issue_challenge():
    code = generate_code()
    token = secrets.token_urlsafe(24)
    now = time.monotonic()
    with _lock:
        _prune(now)
        while len(_challenges) >= CAPTCHA_MAX_ENTRIES:
            _challenges.pop(next(iter(_challenges)))
        _challenges[token] = (code, now + CAPTCHA_TTL_SECONDS)
    session["_captcha_token"] = token
    return code


def verify_challenge(answer):
    token = session.pop("_captcha_token", None)
    if not token:
        return False
    with _lock:
        item = _challenges.pop(token, None)
    if item is None:
        return False
    code, expires = item
    if expires <= time.monotonic():
        return False
    return hmac.compare_digest(code.upper(), (answer or "").strip().upper())


def render_png(code):
    width, height = 132, 44
    background = tuple(random.randint(232, 250) for _ in range(3))
    image = Image.new("RGB", (width, height), background)
    draw = ImageDraw.Draw(image)

    for _ in range(140):
        draw.point(
            (random.randint(0, width - 1), random.randint(0, height - 1)),
            fill=tuple(random.randint(120, 210) for _ in range(3)),
        )
    for _ in range(4):
        draw.line(
            [
                (random.randint(0, width), random.randint(0, height)),
                (random.randint(0, width), random.randint(0, height)),
            ],
            fill=tuple(random.randint(90, 180) for _ in range(3)),
            width=1,
        )

    font = ImageFont.load_default(size=30)
    slot = width // (len(code) + 1)
    for index, char in enumerate(code):
        glyph = Image.new("RGBA", (44, height), (0, 0, 0, 0))
        glyph_draw = ImageDraw.Draw(glyph)
        color = tuple(random.randint(20, 90) for _ in range(3))
        glyph_draw.text((4, 0), char, font=font, fill=color + (255,))
        glyph = glyph.rotate(
            random.uniform(-24, 24), resample=Image.BICUBIC, expand=True
        )
        x = slot * (index + 1) - 10 + random.randint(-3, 3)
        y = (height - glyph.height) // 2 + random.randint(-3, 3)
        image.paste(glyph, (x, y), glyph)

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
