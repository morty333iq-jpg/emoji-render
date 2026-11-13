import os, io, glob, subprocess, tempfile, threading, traceback, requests
from flask import Flask, request, abort
from PIL import Image, ImageOps

app = Flask(__name__)
SECRET = os.environ["RENDER_SECRET"]
TOKEN = os.environ["BOT_TOKEN"]
API = f"https://api.telegram.org/bot{TOKEN}"

ERR = '<b><tg-emoji emoji-id="5870657884844462243">❌</tg-emoji> Не получилось сделать</b>'
SECONDS = 3

ENC = ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
       "-pix_fmt", "yuv420p", "-an", "-movflags", "+faststart"]


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


def job(d):
    chat, wid = d["chat_id"], d.get("wait_id")
    try:
        W, H, FPS = int(d["w"]), int(d["h"]), int(d["fps"])
        W -= W % 2
        H -= H % 2
        size = int(d["size"])
        fmt = d["fmt"]
        h = d["bg"].lstrip("#")
        bgc = tuple(int(h[i:i + 2], 16) for i in (0, 2, 4)) + (255,)
        eh = max(2, int(H * size / 100) // 2 * 2)

        with tempfile.TemporaryDirectory() as tmp:
            src = f"{tmp}/in.bin"
            open(src, "wb").write(requests.get(d["url"], timeout=30).content)
            kind = detect_kind(src)
            count, sfps, get = load_source(kind, src, tmp, eh)

            bg_img = make_background(d, W, H, bgc)

            def compose(em):
                em = fit(em, eh, W)
                layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
                layer.paste(em, ((W - em.size[0]) // 2, (H - em.size[1]) // 2))
                return Image.alpha_composite(bg_img, layer).convert("RGB")

            mid = compose(get(min(count // 2, count - 1)))
            print("DEBUG", "kind", kind, "frames", count,
                  "bg_photo", bool(d.get("bg_url")), "out", W, H, FPS, flush=True)

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

        if wid:
            requests.post(f"{API}/deleteMessage", json={"chat_id": chat, "message_id": wid})
    except Exception:
        print("JOB ERROR", traceback.format_exc(), flush=True)
        if wid:
            requests.post(f"{API}/editMessageText", json={
                "chat_id": chat, "message_id": wid, "parse_mode": "HTML", "text": ERR})


@app.get("/")
def health():
    return "ok"


@app.post("/render")
def render():
    if request.headers.get("x-secret") != SECRET:
        abort(403)
    threading.Thread(target=job, args=(request.json,), daemon=True).start()
    return "accepted", 202
