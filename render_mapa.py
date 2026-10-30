#!/usr/bin/env python3
"""Render superior (top-down) del mundo del servidor demo, sin dependencias.

Lee los archivos de region Anvil (.mca) del overworld, toma el bloque mas alto
de cada columna (via el heightmap MOTION_BLOCKING + las secciones) y produce
un PNG con colores por tipo de bloque y sombreado por altura.
Uso: python3 render_mapa.py <carpeta_region> <salida.png>
"""
import io
import struct
import sys
import zlib

# ---------------- NBT minimo ----------------
class Reader:
    def __init__(self, data):
        self.d = data
        self.i = 0

    def u8(self):
        v = self.d[self.i]; self.i += 1; return v

    def read(self, n):
        v = self.d[self.i:self.i + n]; self.i += n; return v

    def i8(self):
        return struct.unpack(">b", self.read(1))[0]

    def i16(self):
        return struct.unpack(">h", self.read(2))[0]

    def i32(self):
        return struct.unpack(">i", self.read(4))[0]

    def i64(self):
        return struct.unpack(">q", self.read(8))[0]

    def f32(self):
        return struct.unpack(">f", self.read(4))[0]

    def f64(self):
        return struct.unpack(">d", self.read(8))[0]

    def string(self):
        n = struct.unpack(">H", self.read(2))[0]
        return self.read(n).decode("utf8", "replace")

    def payload(self, tag):
        if tag == 1: return self.i8()
        if tag == 2: return self.i16()
        if tag == 3: return self.i32()
        if tag == 4: return self.i64()
        if tag == 5: return self.f32()
        if tag == 6: return self.f64()
        if tag == 7:
            n = self.i32(); return self.read(n)
        if tag == 8: return self.string()
        if tag == 9:
            t = self.u8(); n = self.i32()
            return [self.payload(t) for _ in range(n)]
        if tag == 10:
            out = {}
            while True:
                t = self.u8()
                if t == 0: break
                nombre = self.string()
                out[nombre] = self.payload(t)
            return out
        if tag == 11:
            n = self.i32(); return list(struct.unpack(">%di" % n, self.read(4 * n)))
        if tag == 12:
            n = self.i32(); return list(struct.unpack(">%dq" % n, self.read(8 * n)))
        raise ValueError(f"tag desconocido {tag}")


def parse_nbt(data):
    r = Reader(data)
    tag = r.u8()
    r.string()
    return r.payload(tag)


# ---------------- Colores ----------------
def color_de(nombre, y):
    n = nombre.replace("minecraft:", "")
    base = None
    if n == "water":
        base = (38, 84, 178)
    elif n in ("grass_block",):
        base = (106, 166, 74)
    elif n in ("oak_leaves", "birch_leaves", "spruce_leaves", "jungle_leaves", "acacia_leaves", "dark_oak_leaves", "azalea_leaves", "flowering_azalea_leaves", "mangrove_leaves", "cherry_leaves"):
        base = (58, 116, 44)
    elif n in ("sand", "red_sand"):
        base = (219, 204, 158) if n == "sand" else (190, 110, 60)
    elif n in ("stone", "andesite", "diorite", "granite", "cobblestone", "deepslate", "tuff", "calcite"):
        base = (128, 128, 128)
    elif n in ("dirt", "coarse_dirt", "rooted_dirt"):
        base = (134, 96, 67)
    elif n in ("oak_log", "birch_log", "spruce_log", "jungle_log", "acacia_log", "dark_oak_log", "oak_planks"):
        base = (120, 92, 54)
    elif n in ("snow", "snow_block", "powder_snow"):
        base = (240, 246, 246)
    elif n in ("ice", "packed_ice", "blue_ice", "frosted_ice"):
        base = (150, 190, 230)
    elif n in ("gravel",):
        base = (130, 124, 122)
    elif n in ("clay",):
        base = (158, 164, 176)
    elif n in ("lava",):
        base = (232, 110, 20)
    elif n in ("bedrock",):
        base = (70, 70, 70)
    elif n in ("short_grass", "tall_grass", "fern", "large_fern"):
        base = (116, 176, 84)
    elif "terracotta" in n:
        base = (152, 98, 74)
    elif n in ("soul_sand", "soul_soil"):
        base = (84, 66, 54)
    elif n in ("netherrack",):
        base = (112, 46, 40)
    elif n in ("end_stone",):
        base = (219, 224, 168)
    elif n in ("oak_sapling",) or "flower" in n or n in ("dandelion", "poppy"):
        base = (120, 180, 90)
    if base is None:
        h = abs(hash(n)) % 360
        base = (100 + h % 60, 110, 90)
    # sombreado suave por altura (mar ~62)
    f = 0.82 + max(-24, min(40, y - 62)) * 0.006
    return tuple(max(0, min(255, int(c * f))) for c in base)


AIR = {"minecraft:air", "minecraft:cave_air", "minecraft:void_air"}


def bloque_en(section, lx, ly, lz):
    bs = section.get("block_states")
    if not bs:
        return "minecraft:air"
    pal = bs.get("palette", [])
    if len(pal) == 1:
        return pal[0].get("Name", "minecraft:air")
    data = bs.get("data")
    if data is None:
        return pal[0].get("Name", "minecraft:air")
    bits = max(4, (len(pal) - 1).bit_length())
    idx = (ly * 16 + lz) * 16 + lx
    por = 64 // bits
    li = idx // por
    if li >= len(data):
        return "minecraft:air"
    off = (idx % por) * bits
    v = ((data[li] & 0xFFFFFFFFFFFFFFFF) >> off) & ((1 << bits) - 1)
    if v >= len(pal):
        return "minecraft:air"
    return pal[v].get("Name", "minecraft:air")


def chunk_columnas(nbt):
    """Devuelve dict {(lx,lz): (nombre_bloque, y)} del bloque superior."""
    hm = nbt.get("Heightmaps", {}).get("MOTION_BLOCKING")
    secciones = {}
    for s in nbt.get("sections", []):
        secciones[s.get("Y", 0)] = s
    out = {}
    if not hm or len(hm) < 37:
        return out
    for lz in range(16):
        for lx in range(16):
            i = lz * 16 + lx
            longv = hm[i // 7] & 0xFFFFFFFFFFFFFFFF
            h = (longv >> ((i % 7) * 9)) & 0x1FF
            y = h - 65  # min_y=-64: top_y = h + min_y - 1
            # buscar el bloque real cerca de esa altura
            nombre = None
            for yy in range(y, max(y - 6, -64), -1):
                sec = secciones.get(yy // 16)
                if sec is None:
                    continue
                nb = bloque_en(sec, lx, yy % 16, lz)
                if nb not in AIR:
                    nombre, y = nb, yy
                    break
            if nombre is None:
                nombre, y = "minecraft:stone", y
            out[(lx, lz)] = (nombre, y)
    return out


def leer_region(path):
    chunks = {}
    with open(path, "rb") as f:
        datos = f.read()
    for i in range(1024):
        off = struct.unpack(">I", b"\x00" + datos[i * 4:i * 4 + 3])[0]
        if off == 0:
            continue
        pos = off * 4096
        ln = struct.unpack(">I", datos[pos:pos + 4])[0]
        comp = datos[pos + 4]
        crudo = datos[pos + 5:pos + 4 + ln]
        try:
            if comp == 2:
                dec = zlib.decompress(crudo)
            elif comp == 1:
                dec = zlib.decompress(crudo, 47)
            else:
                dec = crudo
            chunks[(i % 32, i // 32)] = parse_nbt(dec)
        except Exception:
            continue
    return chunks


def escribir_png(path, w, h, pix):
    def chunk(tipo, data):
        c = struct.pack(">I", len(data)) + tipo + data
        c += struct.pack(">I", zlib.crc32(tipo + data) & 0xFFFFFFFF)
        return c

    filas = bytearray()
    for yy in range(h):
        filas.append(0)
        filas += pix[yy * w * 3:(yy + 1) * w * 3]
    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(bytes(filas), 6))
    png += chunk(b"IEND", b"")
    with open(path, "wb") as f:
        f.write(png)


def main():
    carpeta, salida = sys.argv[1], sys.argv[2]
    regiones = {}
    import os
    rmin = 10 ** 9
    for nombre in os.listdir(carpeta):
        if nombre.startswith("r.") and nombre.endswith(".mca"):
            partes = nombre[2:-4].split(".")
            rx, rz = int(partes[0]), int(partes[1])
            regiones[(rx, rz)] = os.path.join(carpeta, nombre)
            rmin = min(rmin, rx, rz)
    xs = [k[0] for k in regiones]; zs = [k[1] for k in regiones]
    x0, x1, z0, z1 = min(xs), max(xs), min(zs), max(zs)
    W = (x1 - x0 + 1) * 512
    H = (z1 - z0 + 1) * 512
    pix = bytearray(W * H * 3)
    alturas = [[62] * W for _ in range(H)]
    for (rx, rz), path in sorted(regiones.items()):
        chunks = leer_region(path)
        for (cx, cz), nbt in chunks.items():
            cols = chunk_columnas(nbt)
            bx = (rx - x0) * 512 + cx * 16
            bz = (rz - z0) * 512 + cz * 16
            for (lx, lz), (nombre, y) in cols.items():
                px, pz = bx + lx, bz + lz
                r, g, b = color_de(nombre, y)
                o = (pz * W + px) * 3
                pix[o:o + 3] = bytes((r, g, b))
                alturas[pz][px] = y
    # sombreado por relieve (luz desde el noroeste)
    for zz in range(1, H):
        fila = alturas[zz]; fila_n = alturas[zz - 1]
        for xx in range(1, W):
            d = fila_n[xx - 1] - fila[xx]
            if d:
                o = (zz * W + xx) * 3
                f = max(0.72, min(1.3, 1 + d * 0.06))
                for k in range(3):
                    pix[o + k] = max(0, min(255, int(pix[o + k] * f)))
    # recorte al contenido dibujado (columnas con altura real) + margen
    dibujado = [[False] * W for _ in range(H)]
    for (rx, rz), path in regiones.items():
        pass  # las alturas ya marcan el area generada via chunks plenos
    xs_d = [x for z in range(H) for x in range(W) if alturas[z][x] != 62 or pix[(z * W + x) * 3:(z * W + x) * 3 + 3] != b"\x00\x00\x00"]
    if xs_d:
        ys_d = [z for z in range(H) if any(alturas[z][x] != 62 or pix[(z * W + x) * 3:(z * W + x) * 3 + 3] != b"\x00\x00\x00" for x in range(W))]
        mx0, mx1 = max(0, min(xs_d) - 24), min(W - 1, max(xs_d) + 24)
        mz0, mz1 = max(0, min(ys_d) - 24), min(H - 1, max(ys_d) + 24)
        cw, ch = mx1 - mx0 + 1, mz1 - mz0 + 1
        escala = max(1, 640 // max(cw, ch))
        nw, nh = cw * escala, ch * escala
        nuevo = bytearray(nw * nh * 3)
        for zz in range(ch):
            for xx in range(cw):
                o = ((mz0 + zz) * W + (mx0 + xx)) * 3
                px = bytes(pix[o:o + 3])
                for dz in range(escala):
                    for dx in range(escala):
                        no = ((zz * escala + dz) * nw + (xx * escala + dx)) * 3
                        nuevo[no:no + 3] = px
        escribir_png(salida, nw, nh, nuevo)
        print(f"OK {salida} {nw}x{nh} (recorte {cw}x{ch} x{escala}) regiones={len(regiones)}")
        return
    escribir_png(salida, W, H, pix)
    print(f"OK {salida} {W}x{H} regiones={len(regiones)}")


if __name__ == "__main__":
    main()
