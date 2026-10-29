"""Parchea LOA Logs.exe para que la ventana del meter mande cada actualización al servidor del móvil.

LOA Logs (Tauri) lleva su interfaz web comprimida con Brotli dentro del .exe. Este script
busca el trozo de JavaScript que recibe "encounter-update", le añade un reenvío a
ws://127.0.0.1:8765/feed, lo vuelve a comprimir en el mismo hueco y ajusta su tamaño.
No toca nada del juego ni de nineveh.

Uso (con LOA Logs cerrado):  python parchear_loalogs.py [--comprobar]
Si LOA Logs se actualiza, vigilar_parche.py lo vuelve a aplicar solo. Copia del original: "LOA Logs.exe.orig".
"""
import re
import shutil
import struct
import sys
import time
from pathlib import Path

import brotli

from ruta_loalogs import carpeta_loalogs
EXE = carpeta_loalogs() / "LOA Logs.exe"
MARCA = "/*meter-movil*/"
VERSION = "/*mm-v4*/"  # súbela si cambia REENVIO: los parches viejos se rehacen desde el original
# Punto de enganche: el listener de mensajes de WebView2 para "encounter-update".
ENGANCHE = re.compile(r'(\w+)=>\{\1\.data\?\.event==="encounter-update"&&(\w+)\(\1\.data\)\}')
# Segundo enganche (opcional): los grupos llegan por el evento "party-update".
ENGANCHE_GRUPOS = re.compile(r'(\w+)=(\w+)=>(\w+)\("party-update",\2\)')

# Manda los datos en bruto del combate (lo justo que usa el meter de LOA Logs); los cálculos
# los hace la página del móvil con la misma lógica que LOA Logs.
REENVIO = MARCA + VERSION + r"""globalThis.__mm||(globalThis.__mm=(()=>{let w=null,last=0;
const open=()=>{try{w=new WebSocket("ws://127.0.0.1:8765/feed");w.onclose=()=>{w=null;setTimeout(open,3000)};w.onerror=()=>{try{w.close()}catch(e){}}}catch(e){w=null;setTimeout(open,3000)}};open();
const DS=["damageDealt","hyperAwakeningDamage","damageTaken","buffedBySupport","buffedByIdentity","debuffedBySupport","buffedByHat","critDamage","backAttackDamage","frontAttackDamage","shieldsGiven","deaths","deathTime","rdpsDamageReceived","rdpsDamageReceivedSupport","rdpsDamageGiven","stagger","unbuffedDamage","unbuffedDps","dps","incapacitations"],
SK=["id","special","isHyperAwakening","totalDamage","hits","casts","rdpsContributed"],
pick=(o,ks)=>{const r={};if(o)for(const k of ks)if(o[k]!=null)r[k]=o[k];return r},
ent=x=>({name:x.name,entityType:x.entityType,class:x.class,classId:x.classId,gearScore:x.gearScore,isDead:x.isDead,
damageStats:pick(x.damageStats,DS),skillStats:x.skillStats||{},skills:Object.values(x.skills||{}).map(q=>pick(q,SK))}),
pack=e=>{const es=[],d=e.encounterDamageStats||{},b=e.currentBoss;
for(const x of Object.values(e.entities||{}))if(String(x.entityType).toUpperCase()==="PLAYER"&&(x.damageStats||{}).damageDealt>0)es.push(ent(x));
return{type:"raw",live:true,duration:e.duration,fightStart:e.fightStart,lastCombatPacket:e.lastCombatPacket,localPlayer:e.localPlayer,
currentBossName:e.currentBossName,difficulty:e.difficulty,cleared:!!e.cleared,
currentBoss:b?{name:b.name,currentHp:b.currentHp,maxHp:b.maxHp,currentShield:b.currentShield,hpBars:b.hpBars}:null,
partyInfo:globalThis.__mmP??(d.misc||{}).partyInfo??null,
encounterDamageStats:{totalDamageDealt:d.totalDamageDealt,topDamageDealt:d.topDamageDealt,misc:{rdpsValid:(d.misc||{}).rdpsValid}},entities:es}};
return p=>{try{const n=Date.now();if(!w||w.readyState!==1||n-last<400)return;last=n;w.send(JSON.stringify(pack(p)))}catch(e){}}})());
"""


def secciones(b):
    pe = struct.unpack_from("<I", b, 0x3C)[0]
    n = struct.unpack_from("<H", b, pe + 6)[0]
    opt = struct.unpack_from("<H", b, pe + 20)[0]
    base = struct.unpack_from("<Q", b, pe + 24 + 24)[0]
    out = []
    for i in range(n):
        o = pe + 24 + opt + 40 * i
        vs, va, rs, ro = struct.unpack_from("<IIII", b, o + 8)
        out.append((va, rs, ro))
    return base, out


def off2va(base, secs, off):
    for va, rs, ro in secs:
        if ro <= off < ro + rs:
            return base + va + off - ro


def va2off(base, secs, v):
    r = v - base
    for va, rs, ro in secs:
        if va <= r < va + rs:
            return ro + r - va


def buscar(b):
    """Devuelve (ruta, pos_tabla, pos_blob, tamaño, js) del trozo con el enganche."""
    base, secs = secciones(b)
    for m in re.finditer(rb"/_app/immutable/chunks/[\w.-]+\.js", b):
        va = off2va(base, secs, m.start())
        if va is None:
            continue
        k = b.find(struct.pack("<QQ", va, len(m.group())))
        if k < 0:
            continue
        vptr, vlen = struct.unpack_from("<QQ", b, k + 16)
        voff = va2off(base, secs, vptr)
        if voff is None or vlen > 8 << 20:
            continue
        try:
            js = brotli.decompress(b[voff:voff + vlen]).decode("utf-8")
        except Exception:
            continue
        if "encounter-update" in js and (ENGANCHE.search(js) or MARCA in js):
            return m.group().decode(), k, voff, vlen, js
    return None


class ErrorParche(Exception):
    pass


def parchear(exe=None, comprobar=False, log=print):
    """Aplica el parche. Devuelve "ya", "comprobado", "parcheado" o "parcheado_en_uso"
    (el .exe estaba abierto: se activa la próxima vez que se abra LOA Logs)."""
    exe = Path(exe or EXE)
    b = bytearray(exe.read_bytes())
    r = buscar(bytes(b))
    if not r:
        raise ErrorParche("No encuentro el trozo de 'encounter-update'. ¿Ha cambiado LOA Logs? Hay que revisar el parche.")
    ruta, k, voff, vlen, js = r
    desde_orig = False
    if MARCA in js:
        if VERSION in js:
            log(f"Ya está parcheado ({ruta}).")
            return "ya"
        # parche de una versión anterior: se rehace a partir de la copia original
        log("Tiene un parche antiguo; lo rehago desde LOA Logs.exe.orig.")
        b, r = desde_original(exe, b, k, voff, vlen)
        ruta, k, voff, vlen, js = r
        desde_orig = True
    log(f"Encontrado {ruta}: {vlen} bytes comprimidos, {len(js)} de JavaScript.")
    m = ENGANCHE.search(js)
    ev, cb = m.group(1), m.group(2)
    nuevo = (REENVIO + js[:m.start()] +
             f'{ev}=>{{{ev}.data?.event==="encounter-update"&&({cb}({ev}.data),globalThis.__mm?.({ev}.data.payload))}}' +
             js[m.end():])
    g = ENGANCHE_GRUPOS.search(nuevo)
    if g:
        n, h, lis = g.group(1), g.group(2), g.group(3)
        nuevo = (nuevo[:g.start()] +
                 f'{n}={h}=>{lis}("party-update",q=>{{try{{globalThis.__mmP=q.payload}}catch(e){{}}return {h}(q)}})' +
                 nuevo[g.end():])
    else:
        log("Aviso: no encuentro el evento de grupos; el directo saldrá sin separar por grupos.")
    comp = brotli.compress(nuevo.encode("utf-8"), quality=11)
    log(f"Comprimido nuevo: {len(comp)} bytes (hueco: {vlen}).")
    if len(comp) > vlen:
        raise ErrorParche("No cabe en el hueco original; no toco nada.")
    if brotli.decompress(comp).decode("utf-8") != nuevo:
        raise ErrorParche("La comprobación de la compresión ha fallado; no toco nada.")
    if comprobar:
        log("Comprobación correcta (no se ha escrito nada).")
        return "comprobado"
    b[voff:voff + vlen] = comp + b"\0" * (vlen - len(comp))
    struct.pack_into("<Q", b, k + 24, len(comp))
    r2 = buscar(bytes(b))
    if not r2 or MARCA not in r2[4]:
        raise ErrorParche("La verificación del .exe parcheado ha fallado; no toco nada.")
    # copia del último original sin parchear (se renueva en cada actualización)
    if not desde_orig:
        copia = exe.with_name("LOA Logs.exe.orig")
        shutil.copy2(exe, copia)
        log(f"Copia de seguridad: {copia}")
    tmp = exe.with_name("LOA Logs.exe.nuevo")
    tmp.write_bytes(b)
    limpiar_viejos(exe)
    try:
        tmp.replace(exe)
        log("LOA Logs parcheado.")
        return "parcheado"
    except PermissionError:
        # Está abierto: Windows deja renombrar un .exe en uso, así que lo apartamos
        # y ponemos el parcheado en su sitio. Se activa al volver a abrir LOA Logs.
        viejo = exe.with_name(f"LOA Logs.exe.viejo-{int(time.time())}")
        exe.rename(viejo)
        tmp.replace(exe)
        log("LOA Logs parcheado (estaba abierto: se activa al reiniciarlo).")
        return "parcheado_en_uso"


def desde_original(exe, actual, k, voff, vlen):
    """Carga LOA Logs.exe.orig y comprueba que es la misma versión que el .exe parcheado
    (idéntico salvo el trozo parcheado y su tamaño)."""
    orig = exe.with_name("LOA Logs.exe.orig")
    if not orig.exists():
        raise ErrorParche("Hay un parche antiguo pero no está LOA Logs.exe.orig; reinstala LOA Logs y vuelve a parchear.")
    o = bytearray(orig.read_bytes())
    r = buscar(bytes(o))
    if not r or MARCA in r[4] or len(o) != len(actual) or r[1:3] != (k, voff):
        raise ErrorParche("LOA Logs.exe.orig no corresponde a esta versión; reinstala LOA Logs y vuelve a parchear.")
    hueco = r[3]  # tamaño original del trozo (el parche viejo lo había cambiado)
    a = bytearray(actual)
    a[voff:voff + hueco] = o[voff:voff + hueco]
    a[k + 24:k + 32] = o[k + 24:k + 32]
    if a != o:
        raise ErrorParche("LOA Logs.exe.orig no coincide con esta versión; reinstala LOA Logs y vuelve a parchear.")
    return o, r


def limpiar_viejos(exe=None):
    """Borra los .exe apartados de parches anteriores que ya no estén en uso."""
    exe = Path(exe or EXE)
    for v in exe.parent.glob("LOA Logs.exe.viejo-*"):
        try:
            v.unlink()
        except OSError:
            pass


def main():
    try:
        estado = parchear(comprobar="--comprobar" in sys.argv)
    except ErrorParche as e:
        sys.exit(str(e))
    if estado == "parcheado":
        print("Ábrelo de nuevo.")


if __name__ == "__main__":
    main()
