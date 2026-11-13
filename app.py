import os, subprocess, tempfile, threading, requests
from flask import Flask, request, abort

app = Flask(__name__)
SECRET = os.environ["RENDER_SECRET"]
TOKEN = os.environ["BOT_TOKEN"]
API = f"https://api.telegram.org/bot{TOKEN}"

ERR = '<b><tg-emoji emoji-id="5870657884844462243">❌</tg-emoji> Не получилось сделать</b>'


def job(d):
    chat, wid = d["chat_id"], d.get("wait_id")
    try:
        W, H, FPS = int(d["w"]), int(d["h"]), int(d["fps"])
        size = int(d["size"])
        bg = "0x" + d["bg"].lstrip("#")
        eh = max(2, int(H * size / 100) // 2 * 2)
        fmt = d["fmt"]

        with tempfile.TemporaryDirectory() as tmp:
            src = f"{tmp}/in.{d['kind']}"
            open(src, "wb").write(requests.get(d["url"], timeout=30).content)

            if d["kind"] == "tgs":
                from rlottie_python import LottieAnimation
                gif = f"{tmp}/in.gif"
                LottieAnimation.from_tgs(src).save_animation(gif)
                inp = ["-stream_loop", "-1", "-ignore_loop", "0", "-i", gif]
            elif d["kind"] == "webm":
                inp = ["-stream_loop", "-1", "-c:v", "libvpx-vp9", "-i", src]
            else:
                inp = ["-loop", "1", "-i", src]

            out = f"{tmp}/out.{fmt}"
            base = (f"[1:v]scale=-2:{eh}:flags=lanczos,format=rgba[e];"
                    f"[0:v][e]overlay=(W-w)/2:(H-h)/2:shortest=1")
            if fmt == "gif":
                fc = base + ",split[a][b];[a]palettegen[p];[b][p]paletteuse"
                codec = []
            else:
                fc = base + ",format=yuv420p"
                codec = ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
                         "-movflags", "+faststart"]

            cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c={bg}:s={W}x{H}:r={FPS}",
                   *inp, "-filter_complex", fc, "-t", "3", "-r", str(FPS), *codec, out]
            p = subprocess.run(cmd, capture_output=True, timeout=240)
            if p.returncode:
                raise RuntimeError(p.stderr.decode()[-800:])

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
    except Exception as e:
        print("JOB ERROR", repr(e), flush=True)
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
