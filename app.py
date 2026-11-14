import os, io, glob, base64, subprocess, tempfile, threading, traceback, requests
from flask import Flask, request, abort
from PIL import Image, ImageOps, ImageDraw, ImageFont

app = Flask(__name__)
SECRET = os.environ["RENDER_SECRET"]
TOKEN = os.environ["BOT_TOKEN"]
API = f"https://api.telegram.org/bot{TOKEN}"

ERR = '<b><tg-emoji emoji-id="5870657884844462243">❌</tg-emoji> Не получилось сделать</b>'
ERR_REFUND = ('<b><tg-emoji emoji-id="5870657884844462243">❌</tg-emoji> '
              'Не получилось сделать. Звёзды вернулись на твой счёт ⭐</b>')
SECONDS = 3

# одна тяжёлая задача за раз: на бесплатном Render всего 512 МБ памяти
SEM = threading.Semaphore(1)

ENC = ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
       "-pix_fmt", "yuv420p", "-an", "-movflags", "+faststart"]

# ---------- Водяной знак ----------
# Логотип kiki (по умолчанию, ставится всем, кто не купил свой знак)
LOGO_B64 = "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"
_LOGO = None

FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
]


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def logo_image():
    global _LOGO
    if _LOGO is None:
        _LOGO = Image.open(io.BytesIO(base64.b64decode(LOGO_B64))).convert("RGBA")
    return _LOGO


def load_font(size):
    for p in FONT_PATHS:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def text_mark(text, H):
    """Текстовый знак: светлые буквы с лёгкой тенью"""
    fs = _clamp(round(H * 0.055), 20, 36)
    font = load_font(fs)
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    l, t, r, b = probe.textbbox((0, 0), text, font=font)
    w, h = r - l, b - t
    pad = 4
    img = Image.new("RGBA", (w + pad * 2, h + pad * 2), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.text((pad - l + 1, pad - t + 1), text, font=font, fill=(0, 0, 0, 120))
    d.text((pad - l, pad - t), text, font=font, fill=(240, 240, 240, 215))
    return img


def build_watermark(mode, text, W, H):
    """Возвращает (картинка RGBA, x, y) или None"""
    if mode == "none":
        return None
    if mode == "text" and text:
        mark = text_mark(text[:24], H)
    else:
        logo = logo_image()
        th = _clamp(round(H * 0.065), 28, 40)
        tw = round(logo.size[0] * th / logo.size[1])
        mark = logo.resize((tw, th), Image.LANCZOS)
    # не шире 40% кадра
    if mark.size[0] > W * 0.4:
        k = (W * 0.4) / mark.size[0]
        mark = mark.resize((max(1, round(mark.size[0] * k)), max(1, round(mark.size[1] * k))), Image.LANCZOS)
    margin = max(10, round(H * 0.04))
    return mark, W - mark.size[0] - margin, H - mark.size[1] - margin


# ---------- Источники ----------
def detect_kind(path):
    head = open(path, "rb").read(16)
    if head[:2] == b"\x1f\x8b":
        return "tgs"
    if head[:4] == b"\x1a\x45\xdf\xa3":
        return "webm"
    return "img"


def load_source(kind, path, tmp, eh):
    """Возвращает (кадров, fps источника, функция get(i) -> RGBA Image)"""
    if kind == "tgs":
        from rlottie_python import LottieAnimation
        anim = LottieAnimation.from_tgs(path)
        n = int(anim.lottie_animation_get_totalframe())
        fps = float(anim.lottie_animation_get_framerate() or 30)

        def get(i):
            try:
                im = anim.render_pillow_frame(frame_num=i, width=eh, height=eh)
            except TypeError:
                im = anim.render_pillow_frame(frame_num=i)
            return im.convert("RGBA")
        return n, fps, get

    if kind == "webm":
        files = []
        for extra in (["-c:v", "libvpx-vp9"], []):
            for old in glob.glob(f"{tmp}/s*.png"):
                os.remove(old)
            subprocess.run(
                ["ffmpeg", "-y", *extra, "-i", path, "-vf", "fps=30",
                 "-pix_fmt", "rgba", "-t", str(SECONDS), f"{tmp}/s%04d.png"],
                capture_output=True, timeout=120)
            files = sorted(glob.glob(f"{tmp}/s*.png"))
            if files:
                break
        if not files:
            raise RuntimeError("no frames decoded from webm")
        return len(files), 30.0, lambda i: Image.open(files[i]).convert("RGBA")

    im = Image.open(path).convert("RGBA")
    return 1, 1.0, lambda i: im


def fit(em, eh, W):
    w0, h0 = em.size
    scale = min(eh / h0, W / w0)
    nw, nh = max(2, round(w0 * scale)), max(2, round(h0 * scale))
    if (nw, nh) != em.size:
        em = em.resize((nw, nh), Image.LANCZOS)
    return em


def make_background(d, W, H, bgc):
    """Однотонный фон или фото пользователя (подгоняется под W x H с обрезкой краёв)"""
    base = Image.new("RGBA", (W, H), bgc)
    if d.get("bg_url"):
        try:
            raw = requests.get(d["bg_url"], timeout=30).content
            photo = ImageOps.exif_transpose(Image.open(io.BytesIO(raw))).convert("RGBA")
            photo = ImageOps.fit(photo, (W, H), Image.LANCZOS)
            return Image.alpha_composite(base, photo)
        except Exception:
            print("BG ERROR", traceback.format_exc(), flush=True)
    return base


def tg_delete(chat, msg_id):
    try:
        requests.post(f"{API}/deleteMessage", json={"chat_id": chat, "message_id": msg_id}, timeout=15)
    except Exception:
        pass


def refund(d):
    """Возврат звёзд, если пользователь платил, а ролик не получился"""
    charge, uid = d.get("charge"), d.get("uid")
    if not charge or not uid:
        return False
    try:
        r = requests.post(f"{API}/refundStarPayment",
                          json={"user_id": uid, "telegram_payment_charge_id": charge}, timeout=15)
        print("REFUND", r.text[:200], flush=True)
        return bool(r.json().get("ok"))
    except Exception:
        print("REFUND ERROR", traceback.format_exc(), flush=True)
        return False


def render_video(d, tmp):
    W, H, FPS = int(d["w"]), int(d["h"]), int(d["fps"])
    W -= W % 2
    H -= H % 2
    size = int(d["size"])
    fmt = d["fmt"]
    h = d["bg"].lstrip("#")
    bgc = tuple(int(h[i:i + 2], 16) for i in (0, 2, 4)) + (255,)
    eh = max(2, int(H * size / 100) // 2 * 2)

    src = f"{tmp}/in.bin"
    open(src, "wb").write(requests.get(d["url"], timeout=30).content)
    kind = detect_kind(src)
    count, sfps, get = load_source(kind, src, tmp, eh)

    bg_img = make_background(d, W, H, bgc)
    wm = build_watermark(d.get("wm_mode", "none"), (d.get("wm_text") or "").strip(), W, H)

    def compose(em):
        em = fit(em, eh, W)
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        layer.paste(em, ((W - em.size[0]) // 2, (H - em.size[1]) // 2))
        frame = Image.alpha_composite(bg_img, layer).convert("RGB")
        if wm:
            mark, x, y = wm
            frame.paste(mark, (x, y), mark)   # знак поверх всего
        return frame

    mid = compose(get(min(count // 2, count - 1)))
    print("DEBUG", "kind", kind, "frames", count, "bg_photo", bool(d.get("bg_url")),
          "wm", d.get("wm_mode"), "out", W, H, FPS, flush=True)

    th = mid.copy()
    th.thumbnail((320, 320))
    buf = io.BytesIO()
    th.save(buf, "JPEG", quality=85)
    thumb = buf.getvalue()

    out = f"{tmp}/out.mp4"
    if count == 1:
        mid.save(f"{tmp}/f.png")
        cmd = ["ffmpeg", "-y", "-loop", "1", "-framerate", str(FPS),
               "-i", f"{tmp}/f.png", "-t", str(SECONDS),
               *ENC, "-tune", "stillimage", "-r", str(FPS), out]
        p = subprocess.run(cmd, capture_output=True, timeout=240)
        if p.returncode:
            raise RuntimeError(p.stderr.decode(errors="ignore")[-800:])
    else:
        cmd = ["ffmpeg", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
               "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", *ENC, out]
        log = open(f"{tmp}/ff.log", "wb")
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=log)
        for i in range(FPS * SECONDS):
            idx = int((i / FPS) * sfps) % count
            proc.stdin.write(compose(get(idx)).tobytes())
        proc.stdin.close()
        proc.wait(timeout=240)
        log.close()
        if proc.returncode:
            raise RuntimeError(open(f"{tmp}/ff.log", "rb").read()[-800:].decode(errors="ignore"))

    chat = d["chat_id"]
    method = "sendAnimation" if fmt == "gif" else "sendVideo"
    field = "animation" if fmt == "gif" else "video"
    data = {"chat_id": chat, "width": W, "height": H, "duration": SECONDS}
    if fmt != "gif":
        data["supports_streaming"] = "true"
    with open(out, "rb") as f:
        r = requests.post(
            f"{API}/{method}", data=data,
            files={field: ("emoji.mp4", f, "video/mp4"),
                   "thumbnail": ("t.jpg", thumb, "image/jpeg")},
            timeout=120)
    if not r.json().get("ok"):
        raise RuntimeError("telegram: " + r.text[:300])


def job(d):
    chat, wid = d["chat_id"], d.get("wait_id")
    try:
        with SEM:
            with tempfile.TemporaryDirectory() as tmp:
                render_video(d, tmp)

        # чистим чат: «Делаю…» и (если включена автоочистка) исходный стикер
        if wid:
            tg_delete(chat, wid)
        if d.get("clean") and d.get("src_msg_id"):
            tg_delete(chat, d["src_msg_id"])
    except Exception:
        print("JOB ERROR", traceback.format_exc(), flush=True)
        refunded = refund(d)
        if wid:
            requests.post(f"{API}/editMessageText", json={
                "chat_id": chat, "message_id": wid, "parse_mode": "HTML",
                "text": ERR_REFUND if refunded else ERR})


@app.get("/")
def health():
    return "ok"


@app.post("/render")
def render():
    if request.headers.get("x-secret") != SECRET:
        abort(403)
    threading.Thread(target=job, args=(request.json,), daemon=True).start()
    return "accepted", 202
