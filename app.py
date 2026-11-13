import os, subprocess, tempfile, requests
from flask import Flask, request, send_file, abort

app = Flask(__name__)
SECRET = os.environ["RENDER_SECRET"]

@app.get("/")
def health():
    return "ok"

@app.post("/render")
def render():
    if request.headers.get("x-secret") != SECRET:
        abort(403)
    d = request.json
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
            codec = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                     "-movflags", "+faststart"]

        cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c={bg}:s={W}x{H}:r={FPS}",
               *inp, "-filter_complex", fc, "-t", "3", "-r", str(FPS), *codec, out]
        p = subprocess.run(cmd, capture_output=True)
        if p.returncode:
            print(p.stderr.decode()[-1500:], flush=True)
            return p.stderr.decode()[-500:], 500
        return send_file(out, mimetype="image/gif" if fmt == "gif" else "video/mp4")
