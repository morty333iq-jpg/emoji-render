import os, glob, subprocess, tempfile, threading, traceback, requests
from flask import Flask, request, abort
from PIL import Image

app = Flask(__name__)
SECRET = os.environ["RENDER_SECRET"]
TOKEN = os.environ["BOT_TOKEN"]
API = f"https://api.telegram.org/bot{TOKEN}"

ERR = '<b><tg-emoji emoji-id="5870657884844462243">❌</tg-emoji> Не получилось сделать</b>'
SECONDS = 3


def load_source(kind, path, tmp, eh):
    """Возвращает (кол-во кадров, fps источника, функция get(i) -> RGBA Image)"""
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
        subprocess.run(
            ["ffmpeg", "-y", "-c:v", "libvpx-vp9", "-i", path,
             "-vf", "fps=30", "-t", str(SECONDS), f"{tmp}/s%04d.png"],
            capture_output=True, timeout=120, check=True)
        files = sorted(glob.glob(f"{tmp}/s*.png"))
        if not files:
            raise RuntimeError("no frames decoded from webm")
        return len(files), 30.0, lambda i: Image.open(files[i]).convert("RGBA")

    im = Image.open(path).convert("RGBA")
    return 1, 1.0, lambda i: im


def job(d):
    chat, wid = d["chat_id"], d.get("wait_id")
    try:
        W, H, FPS = int(d["w"]), int(d["h"]), int(d["fps"])
        size = int(d["size"])
        fmt = d["fmt"]
        if fmt == "gif":
            FPS = min(FPS, 50)
        h = d["bg"].lstrip("#")
        bgc = tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
        eh = max(2, int(H * size / 100) // 2 * 2)

        with tempfile.TemporaryDirectory() as tmp:
            src = f"{tmp}/in.{d['kind']}"
            open(src, "wb").write(requests.get(d["url"], timeout=30).content)
            count, sfps, get = load_source(d["kind"], src, tmp, eh)

            out = f"{tmp}/out.{fmt}"
            base = ["ffmpeg", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
                    "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-"]
            if fmt == "gif":
                cmd = base + ["-vf", "split[a][b];[a]palettegen[p];[b][p]paletteuse", out]
            else:
                cmd = base + ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
                              "-pix_fmt", "yuv420p", "-movflags", "+faststart", out]

            log = open(f"{tmp}/ff.log", "wb")
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=log)

            bg_img = Image.new("RGB", (W, H), bgc)
            cache = {}
            for i in range(FPS * SECONDS):
                idx = int((i / FPS) * sfps) % count
                if idx in cache:
                    em = cache[idx]
                else:
                    em = get(idx)
                    w0, h0 = em.size
                    nw = max(2, round(w0 * eh / h0))
                    if (nw, eh) != em.size:
                        em = em.resize((nw, eh), Image.LANCZOS)
                    if count == 1:
                        cache[idx] = em
                frame = bg_img.copy()
                frame.paste(em, ((W - em.size[0]) // 2, (H - em.size[1]) // 2), em)
                proc.stdin.write(frame.tobytes())
            proc.stdin.close()
            proc.wait(timeout=240)
            log.close()
            if proc.returncode:
                raise RuntimeError(open(f"{tmp}/ff.log", "rb").read()[-800:].decode(errors="ignore"))

            method = "sendAnimation" if fmt == "gif" else "sendVideo"
            field = "animation" if fmt == "gif" else "video"
            data = {"chat_id": chat}
            if fmt == "mp4":
                data.update({"width": W, "height": H})
            with open(out, "rb") as f:
                r = requests.post(f"{API}/{method}", data=data,
                                  files={field: (f"emoji.{fmt}", f)}, timeout=120)
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
