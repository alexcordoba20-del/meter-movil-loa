"""Captura la ventana del meter de LOA Logs (PrintWindow, necesita admin) y recorta lo transparente."""
import ctypes, ctypes.wintypes as w, io
from PIL import Image

u = ctypes.windll.user32
g = ctypes.windll.gdi32
try:
    u.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
except Exception:
    pass


class BIH(ctypes.Structure):
    _fields_ = [("biSize", w.DWORD), ("biWidth", w.LONG), ("biHeight", w.LONG), ("biPlanes", w.WORD),
                ("biBitCount", w.WORD), ("biCompression", w.DWORD), ("biSizeImage", w.DWORD),
                ("a", w.LONG), ("b", w.LONG), ("c", w.DWORD), ("d", w.DWORD)]


def find_meter():
    """La ventana del meter (normal o mini). Nunca la de historial ('LOA Logs')."""
    for title in ("Meter | LOA Logs", "mini | LOA Logs"):
        h = u.FindWindowW("Tauri Window", title)
        if h and u.IsWindowVisible(h) and not u.IsIconic(h):
            return h, title
    return None, None


def grab(h):
    r = w.RECT()
    u.GetWindowRect(h, ctypes.byref(r))
    W, H = r.right - r.left, r.bottom - r.top
    if W <= 0 or H <= 0:
        return None
    hdc = u.GetWindowDC(h)
    mdc = g.CreateCompatibleDC(hdc)
    bmp = g.CreateCompatibleBitmap(hdc, W, H)
    old = g.SelectObject(mdc, bmp)
    try:
        if not u.PrintWindow(h, mdc, 2):  # PW_RENDERFULLCONTENT
            return None
        bi = BIH(40, W, -H, 1, 32, 0, 0, 0, 0, 0, 0)
        buf = ctypes.create_string_buffer(W * H * 4)
        g.GetDIBits(mdc, bmp, 0, H, buf, ctypes.byref(bi), 0)
        return Image.frombuffer("RGBA", (W, H), buf, "raw", "BGRA", 0, 1).copy()
    finally:
        g.SelectObject(mdc, old)
        g.DeleteObject(bmp)
        g.DeleteDC(mdc)
        u.ReleaseDC(h, hdc)


def crop(img):
    """Quita los bordes vacíos (transparentes o negros)."""
    a = img.getchannel("A")
    box = a.point(lambda v: 255 if v > 8 else 0).getbbox()
    if not box or box == (0, 0) + img.size:
        box = img.convert("L").point(lambda v: 255 if v > 12 else 0).getbbox()
    if box:
        img = img.crop(box)
    return img


def frame_jpeg(quality=80):
    apply_request()
    h, title = find_meter()
    if not h:
        return None, "el meter está oculto (Ctrl+↓ para mostrarlo)"
    img = grab(h)
    if img is None:
        return None, "PrintWindow falló (¿servidor sin administrador?)"
    img = crop(img)
    bg = Image.new("RGB", img.size, (14, 15, 19))
    bg.paste(img, mask=img.getchannel("A") if img.getchannel("A").getextrema()[0] < 255 else None)
    out = io.BytesIO()
    bg.save(out, "JPEG", quality=quality)
    return out.getvalue(), title


if __name__ == "__main__":
    import sys, time
    dest = sys.argv[1]
    for t in ("mini | LOA Logs", "LOA Logs"):
        h = u.FindWindowW("Tauri Window", t)
        img = grab(h) if h else None
        print(t, h, None if img is None else (img.size, img.getchannel("A").getextrema()))
        if img is not None:
            img.save(f"{dest}/pw_admin_{len(t)}.png")
    t0 = time.time(); j, info = frame_jpeg(); print("frame", info, len(j or b""), f"{(time.time()-t0)*1000:.0f} ms")
    if j: open(f"{dest}/frame.jpg", "wb").write(j)


# ---------------------------------------------------------------- modo móvil
# El servidor (admin) puede mover la ventana del meter: peticion.json la lee frame_jpeg.
import json as _json
from pathlib import Path as _Path

_HERE = _Path(__file__).parent
_REQ = _HERE / "peticion.json"
_ORIG = _HERE / "posicion_original.json"
_LOG = _HERE / "peticion_resultado.txt"


def _rect(h):
    r = w.RECT()
    u.GetWindowRect(h, ctypes.byref(r))
    return [r.left, r.top, r.right - r.left, r.bottom - r.top]


def _move(h, x, y, W, H):
    # SWP_NOZORDER | SWP_NOACTIVATE
    return u.SetWindowPos(h, 0, int(x), int(y), int(W), int(H), 0x0004 | 0x0010)


def apply_request():
    if not _REQ.exists():
        return
    try:
        req = _json.loads(_REQ.read_text(encoding="utf-8"))
    except Exception:
        req = {}
    _REQ.unlink(missing_ok=True)
    h, title = find_meter()
    if not h:
        _LOG.write_text("sin ventana", encoding="utf-8")
        return
    act = req.get("action")
    if act == "phone":
        if not _ORIG.exists():
            _ORIG.write_text(_json.dumps({"title": title, "rect": _rect(h)}), encoding="utf-8")
        W, H = req.get("w", 860), req.get("h", 420)
        x, y = req.get("x", -W - 200), req.get("y", 100)
        ok = _move(h, x, y, W, H)
    elif act == "restore" and _ORIG.exists():
        ok = _move(h, *_json.loads(_ORIG.read_text(encoding="utf-8"))["rect"])
        _ORIG.unlink(missing_ok=True)
    else:
        ok = None
    _LOG.write_text(f"{act} -> {ok} rect={_rect(h)}", encoding="utf-8")
