"""Servidor del meter para el móvil (en directo + historial).

- En directo (datos): LOA Logs parcheado (parchear_loalogs.py) manda cada actualización a
  /feed y aquí se reenvía a los móviles como JSON.
- En directo (imagen): espejo de la ventana del meter (captura.py) enviado por WebSocket como JPEG,
  solo mientras algún móvil lo pide. Necesita ejecutarse como administrador (igual que LOA Logs).
- Historial: lee encounters.db en solo lectura.

Uso: python server.py [--port 8765] [--fps 6]
"""
import argparse
import asyncio
import gzip
import importlib
import json
import os
import socket
import sqlite3
import time
from http import HTTPStatus
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import websockets
from websockets.asyncio.server import serve
from websockets.datastructures import Headers
from websockets.http11 import Response

HERE = Path(__file__).parent
from ruta_loalogs import carpeta_loalogs
DB = carpeta_loalogs() / "encounters.db"
HTML = HERE / "index.html"
# Campos que usa el meter de LOA Logs (los mismos que manda el parche en directo).
DS = ["damageDealt", "hyperAwakeningDamage", "damageTaken", "buffedBySupport", "buffedByIdentity",
      "debuffedBySupport", "buffedByHat", "critDamage", "backAttackDamage", "frontAttackDamage",
      "shieldsGiven", "deaths", "deathTime", "rdpsDamageReceived", "rdpsDamageReceivedSupport",
      "rdpsDamageGiven", "stagger", "unbuffedDamage", "unbuffedDps", "dps", "incapacitations"]
SK = ["id", "special", "isHyperAwakening", "totalDamage", "hits", "casts", "rdpsContributed"]
SETTINGS = carpeta_loalogs() / "settings.json"

clients = set()
mirror_clients = set()  # móviles que están viendo la imagen (el resto solo quiere datos)
state = {"cdp": "arrancando", "frame": None, "enc": None, "encTs": 0}


# ---------------------------------------------------------------- historial (BD)
def db():
    c = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True, timeout=5)
    c.row_factory = sqlite3.Row
    return c


def unzip_json(v):
    if v is None:
        return {}
    if isinstance(v, bytes):
        if v[:2] == b"\x1f\x8b":
            v = gzip.decompress(v)
        v = v.decode("utf-8", "replace")
    try:
        return json.loads(v) or {}
    except ValueError:
        return {}


def latest_id():
    with db() as c:
        return c.execute("select max(id) from encounter_preview").fetchone()[0]


def encounter_list(limit=30):
    with db() as c:
        rows = c.execute(
            "select id, fight_start, current_boss, duration, difficulty, cleared, "
            "local_player, my_dps from encounter_preview order by id desc limit ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def pick(o, ks):
    return {k: o[k] for k in ks if isinstance(o, dict) and o.get(k) is not None}


def encounter(eid):
    """Combate guardado con la misma forma que los datos en directo (la página hace los cálculos)."""
    with db() as c:
        p = c.execute("select * from encounter_preview where id=?", (eid,)).fetchone()
        if not p:
            return None
        ents = c.execute(
            "select name, entity_type, class, class_id, gear_score, is_dead, damage_stats, skill_stats, "
            "skills, current_hp, max_hp, hp_bars from entity where encounter_id=?", (eid,)).fetchall()
        e = c.execute("select last_combat_packet, total_damage_dealt, top_damage_dealt, misc "
                      "from encounter where id=?", (eid,)).fetchone()
    misc = unzip_json(e["misc"])
    jugadores, jefe = [], None
    for x in ents:
        if x["entity_type"] == "PLAYER":
            ds = unzip_json(x["damage_stats"])
            if not ds.get("damageDealt"):
                continue
            skills = unzip_json(x["skills"])
            jugadores.append({
                "name": x["name"], "entityType": "PLAYER", "class": x["class"], "classId": x["class_id"],
                "gearScore": x["gear_score"], "isDead": bool(x["is_dead"]),
                "damageStats": pick(ds, DS), "skillStats": unzip_json(x["skill_stats"]),
                "skills": [pick(q, SK) for q in (skills.values() if isinstance(skills, dict) else skills)],
            })
        elif x["entity_type"] == "BOSS" and x["name"] == p["current_boss"]:
            jefe = {"name": x["name"], "currentHp": x["current_hp"], "maxHp": x["max_hp"], "hpBars": x["hp_bars"]}
    return {
        "type": "raw", "live": False, "id": eid, "duration": p["duration"], "fightStart": p["fight_start"],
        "lastCombatPacket": e["last_combat_packet"], "localPlayer": p["local_player"],
        "currentBossName": p["current_boss"], "difficulty": p["difficulty"], "cleared": bool(p["cleared"]),
        "currentBoss": jefe, "partyInfo": misc.get("partyInfo"),
        "encounterDamageStats": {"totalDamageDealt": e["total_damage_dealt"], "topDamageDealt": e["top_damage_dealt"],
                                 "misc": {"rdpsValid": misc.get("rdpsValid")}},
        "entities": jugadores,
    }


def ajustes():
    """Columnas activadas en el meter y en los logs de LOA Logs (para mostrar lo mismo)."""
    try:
        s = json.loads(SETTINGS.read_text(encoding="utf-8"))
        return {"meter": s.get("meter", {}), "logs": s.get("logs", {}), "general": s.get("general", {})}
    except Exception:
        return {}


# ---------------------------------------------------------------- en directo (espejo)
# LOA Logs se ejecuta como administrador y WebView2 no deja depurarlo, así que copiamos
# la imagen de su ventana (PrintWindow) y la mandamos al móvil. El servidor también
# tiene que ir como administrador.
import captura


async def broadcast(msg, to=None):
    data = msg if isinstance(msg, bytes) else json.dumps(msg)
    for ws in list(clients if to is None else to):
        try:
            await ws.send(data)
        except Exception:
            clients.discard(ws)


async def set_status(s):
    if state["cdp"] != s:
        state["cdp"] = s
        print("Espejo:", s)
        await broadcast({"type": "status", "cdp": s})


async def mirror_loop(fps):
    last = None
    while True:
        if not mirror_clients:
            await asyncio.sleep(0.5)
            continue
        try:
            mt = Path(captura.__file__).stat().st_mtime
            if mt != state.get("capMtime"):  # recarga captura.py si se edita, sin reiniciar
                if state.get("capMtime") is not None:
                    importlib.reload(captura)
                state["capMtime"] = mt
            jpg, info = await asyncio.to_thread(captura.frame_jpeg)
        except Exception as ex:
            jpg, info = None, f"error: {ex}"
        if jpg:
            await set_status("ok: " + info)
            if jpg != last:
                last = jpg
                state["frame"] = jpg
                await broadcast(jpg, mirror_clients)
        else:
            await set_status(info)
        await asyncio.sleep(1 / fps)


# ---------------------------------------------------------------- HTTP + WS móvil
def response(code, body, ctype="application/json; charset=utf-8"):
    if not isinstance(body, bytes):
        body = json.dumps(body).encode()
    h = Headers([("Content-Type", ctype), ("Cache-Control", "no-store"),
                 ("Content-Length", str(len(body))), ("Connection", "close")])
    return Response(code, HTTPStatus(code).phrase, h, body)


async def process_request(conn, req):
    u = urlparse(req.path)
    if u.path in ("/ws", "/feed"):
        return None
    q = parse_qs(u.query)
    try:
        if u.path in ("/", "/index.html"):
            return response(200, HTML.read_bytes(), "text/html; charset=utf-8")
        if u.path == "/api/settings":
            return response(200, await asyncio.to_thread(ajustes))
        if u.path == "/api/latest-id":
            return response(200, {"id": await asyncio.to_thread(latest_id)})
        if u.path == "/api/list":
            return response(200, await asyncio.to_thread(encounter_list, int(q.get("limit", [30])[0])))
        if u.path == "/api/meter":
            act = q.get("action", [""])[0]
            req = {"action": act}
            if act == "phone":
                req["w"] = max(300, min(2400, int(float(q["w"][0]))))
                req["h"] = max(200, min(1400, int(float(q["h"][0]))))
            elif act != "restore":
                return response(400, {"error": "accion"})
            (HERE / "peticion.json").write_text(json.dumps(req), encoding="utf-8")
            return response(200, {"ok": True})
        if u.path == "/api/encounter":
            eid = int(q["id"][0]) if "id" in q else await asyncio.to_thread(latest_id)
            data = await asyncio.to_thread(encounter, eid)
            return response(200 if data else 404, data or {"error": "no existe"})
        return response(404, {"error": "ruta"})
    except Exception as ex:
        return response(500, {"error": str(ex)})


def de_parche_viejo(m):
    """Convierte lo que manda un parche antiguo (v1-v3, ya calculado) a la forma en bruto."""
    secs = max(1.0, (m.get("duration") or 0) / 1000)
    ents = []
    for p in m.get("players") or []:
        d = p.get("damage") or 0
        ents.append({
            "name": p["name"], "entityType": "PLAYER", "class": p.get("cls"), "classId": 1,
            "gearScore": p.get("gs"), "isDead": bool(p.get("dead")),
            "damageStats": {"damageDealt": d, "buffedBySupport": d * (p.get("buffSup") or 0),
                            "debuffedBySupport": d * (p.get("brand") or 0), "buffedByIdentity": d * (p.get("iden") or 0),
                            "buffedByHat": d * (p.get("hat") or 0), "backAttackDamage": d * (p.get("back") or 0),
                            "frontAttackDamage": d * (p.get("front") or 0), "shieldsGiven": p.get("shields") or 0,
                            "deaths": p.get("deaths") or 0, "rdpsDamageReceived": p.get("rdpsRecv") or 0,
                            "rdpsDamageGiven": p.get("rdpsGiven") or 0},
            "skillStats": {"hits": 1000, "crits": round((p.get("crit") or 0) * 1000), "casts": p.get("casts")},
            "skills": [],
        })
    b = m.get("bossInfo") or None
    return {"type": "raw", "live": True, "duration": secs * 1000, "fightStart": m.get("start"),
            "lastCombatPacket": (m.get("start") or 0) + secs * 1000, "localPlayer": m.get("local"),
            "currentBossName": m.get("boss"), "difficulty": m.get("difficulty"), "cleared": m.get("cleared"),
            "currentBoss": {"name": b["name"], "currentHp": b["hp"], "maxHp": b["maxHp"], "hpBars": b.get("bars")} if b else None,
            "partyInfo": m.get("partyInfo"), "encounterDamageStats": {}, "entities": ents, "viejo": True}


async def feed_handler(ws):
    """Datos en directo que manda LOA Logs parcheado (ver parchear_loalogs.py). Solo desde este PC."""
    if ws.remote_address[0] not in ("127.0.0.1", "::1"):
        await ws.close(1008, "solo local")
        return
    print("LOA Logs conectado: datos en directo")
    try:
        async for raw in ws:
            try:
                m = json.loads(raw)
                if m.get("type") == "enc":
                    m = de_parche_viejo(m)
                elif m.get("type") != "raw":
                    continue
            except Exception:
                continue
            state["enc"], state["encTs"] = m, time.time()
            await broadcast(m)
    finally:
        print("LOA Logs desconectado")


async def ws_handler(ws):
    if ws.request.path.startswith("/feed"):
        return await feed_handler(ws)
    clients.add(ws)
    try:
        await ws.send(json.dumps({"type": "status", "cdp": state["cdp"]}))
        if state["enc"]:
            await ws.send(json.dumps(state["enc"]))
        async for raw in ws:  # el móvil dice si quiere imagen o datos
            try:
                want = json.loads(raw).get("want")
            except Exception:
                continue
            if want == "mirror":
                mirror_clients.add(ws)
                if state.get("frame"):
                    await ws.send(state["frame"])
            elif want == "data":
                mirror_clients.discard(ws)
    finally:
        clients.discard(ws)
        mirror_clients.discard(ws)


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("192.168.0.1", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


CODIGO = [HERE / "server.py", HERE / "ruta_loalogs.py"]


async def vigilar_actualizaciones():
    """Cada 10 min busca versión nueva en GitHub. Si cambia el código del servidor, sale con
    código 3 para que lanzar.py lo vuelva a abrir (index.html y captura.py se recargan solos)."""
    fechas = {p: p.stat().st_mtime for p in CODIGO if p.exists()}
    siguiente = time.time() + 600
    while True:
        await asyncio.sleep(15)
        if time.time() >= siguiente:
            siguiente = time.time() + 600
            try:
                import actualizar
                cambios = await asyncio.to_thread(actualizar.actualizar)
                if cambios:
                    print("Actualizado desde GitHub:", ", ".join(cambios))
            except Exception as e:
                print("No se pudo comprobar actualizaciones:", e)
        if any(p.exists() and p.stat().st_mtime != fechas.get(p) for p in CODIGO):
            print("El código del servidor ha cambiado: reiniciando...")
            os._exit(3)


async def main(port, fps):
    async with serve(ws_handler, "0.0.0.0", port, process_request=process_request,
                     ping_interval=20, max_size=2**23):
        print(f"Meter móvil en  http://{lan_ip()}:{port}   (Ctrl+C para cerrar)")
        asyncio.create_task(vigilar_actualizaciones())
        await mirror_loop(fps)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--fps", type=float, default=6)
    a = ap.parse_args()
    try:
        asyncio.run(main(a.port, a.fps))
    except KeyboardInterrupt:
        pass
