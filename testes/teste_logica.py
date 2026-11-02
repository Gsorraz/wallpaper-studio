"""Testes de LÓGICA do Wallpaper Studio (sem abrir janela, sem GUI, sem mouse).

Importa main.py sem executar main(). Configuração isolada: APPDATA aponta para pasta temporária.
Uso: python teste_logica.py  -> imprime ok/FALHA e sai com código 0 (tudo ok) ou 1 (falha).
"""
import os
import sys
import tempfile
import time
import json
import math
from pathlib import Path

PROJ = Path(r"F:\Backups\Pythonprojeto\Wallpaper\wallpaper_studio")
TMP_APPDATA = tempfile.mkdtemp(prefix="wsteste_")
os.environ["APPDATA"] = TMP_APPDATA          # isolamento: nunca toca no config real
sys.path.insert(0, str(PROJ))

import main as M  # noqa: E402  (não chama main(): só define funções e classes)
from PySide6.QtCore import QRectF  # noqa: E402

OK = 0
FALHAS = []


def chk(cond, desc):
    global OK
    if cond:
        OK += 1
    else:
        FALHAS.append(desc)
        print(f"FALHA: {desc}")


def perto(a, b, tol=1e-6):
    return abs(a - b) <= tol


def pts_perto(pts, esperado, tol=1e-6):
    return len(pts) == len(esperado) and all(
        perto(p[0], e[0], tol) and perto(p[1], e[1], tol) for p, e in zip(pts, esperado))


# ── WallCfg ─────────────────────────────────────────────────────────────────
c = M.WallCfg()
chk(c.mode == "fill" and c.scale == 100.0 and c.bg == "#000000", "WallCfg: padrões")

c2 = c.copy()
c2.scale = 50
chk(c.scale == 100.0 and c2.scale == 50, "WallCfg.copy é independente do original")

chk(c.key() == M.WallCfg().key(), "WallCfg.key é estável para mesmo conteúdo")
chk(c.key() != c2.key(), "WallCfg.key muda quando um campo muda")

c3 = M.WallCfg(scale=300, rotation=45, persp_h=20, flip_h=True, offset_x=5)
c3.reset_adjust()
chk((c3.scale, c3.offset_x, c3.offset_y, c3.rotation, c3.persp_h, c3.persp_v,
     c3.flip_h, c3.flip_v) == (100.0, 0.0, 0.0, 0.0, 0.0, 0.0, False, False),
    "WallCfg.reset_adjust zera ajustes finos")
chk(c3.mode == "fill", "WallCfg.reset_adjust não mexe no modo")

d = M.WallCfg.from_dict({"mode": "fit", "campo_inexistente": 1, "scale": 80})
chk(d.mode == "fit" and d.scale == 80 and not hasattr(d, "campo_inexistente"),
    "WallCfg.from_dict ignora chaves desconhecidas")
chk(M.WallCfg.from_dict(None).mode == "fill", "WallCfg.from_dict(None) usa padrões")

# ── Config JSON round-trip (ida e volta, como o app salva) ─────────────────
rt = M.WallCfg.from_dict(json.loads(json.dumps(M.WallCfg(mode="tile", bg="#112233").__dict__)))
chk(rt.mode == "tile" and rt.bg == "#112233", "WallCfg: ida e volta por JSON preserva dados")

# ── FIT_MODES ───────────────────────────────────────────────────────────────
chave = [m[0] for m in M.FIT_MODES]
chk(len(chave) == len(set(chave)) == 5, "FIT_MODES: 5 modos com chaves únicas")
chk(set(chave) == {"fill", "fit", "stretch", "tile", "center"}, "FIT_MODES: chaves esperadas")
chk(M.WallCfg().mode in chave, "FIT_MODES: modo padrão existe na lista")

# ── virtual_bbox ────────────────────────────────────────────────────────────
def mon(i, x, y, w, h):
    return M.Monitor(index=i, device=f"\\\\.\\DISPLAY{i}", name=f"M{i}", x=x, y=y, w=w, h=h)

chk(M.virtual_bbox([]) == (0, 0, 1920, 1080), "virtual_bbox vazio: fallback 1920x1080")
chk(M.virtual_bbox([mon(1, 0, 0, 1920, 1080)]) == (0, 0, 1920, 1080), "virtual_bbox: 1 monitor")
duas = [mon(1, 0, 0, 1920, 1080), mon(2, 1920, 0, 2560, 1440)]
chk(M.virtual_bbox(duas) == (0, 0, 4480, 1440), "virtual_bbox: lado a lado")
esq = [mon(1, -1920, 0, 1920, 1080), mon(2, 0, 0, 1920, 1080)]
chk(M.virtual_bbox(esq) == (-1920, 0, 3840, 1080), "virtual_bbox: monitor à esquerda (x negativo)")
cima = [mon(1, 0, -1080, 1920, 1080), mon(2, 0, 0, 1920, 1080)]
chk(M.virtual_bbox(cima) == (0, -1080, 1920, 2160), "virtual_bbox: monitor acima (y negativo)")

# ── square_to_quad (homografia) ────────────────────────────────────────────
q_id = [(0, 0), (1, 0), (1, 1), (0, 1)]
T = M.square_to_quad(q_id)
chk(perto(T.m11(), 1) and perto(T.m22(), 1) and perto(T.dx(), 0) and perto(T.dy(), 0),
    "square_to_quad: quadrado unitário dá identidade")

q = [(10, 20), (110, 30), (120, 140), (5, 130)]
T = M.square_to_quad(q)
ok_cantos = True
for (u, v), (ex, ey) in zip([(0, 0), (1, 0), (1, 1), (0, 1)], q):
    px, py = T.map(u, v)
    ok_cantos &= perto(px, ex, 1e-6) and perto(py, ey, 1e-6)
chk(ok_cantos, "square_to_quad: cantos do quadrado mapeiam para o quadrilátero")

trap = [(0, 0), (100, 0), (80, 100), (20, 100)]  # trapézio (paralelogramo não)
T = M.square_to_quad(trap)
ok_t = all(perto(T.map(u, v)[0], ex) and perto(T.map(u, v)[1], ey)
           for (u, v), (ex, ey) in zip([(0, 0), (1, 0), (1, 1), (0, 1)], trap))
chk(ok_t, "square_to_quad: trapézio mapeia os 4 cantos")

# ── keystone_quad ──────────────────────────────────────────────────────────
R = QRectF(0, 0, 200, 100)
base = [(0, 0), (200, 0), (200, 100), (0, 100)]
chk(pts_perto(M.keystone_quad(R, 0, 0, 0), base), "keystone_quad: sem perspectiva = retângulo")

pts = M.keystone_quad(R, 0, 0, 90)
chk(pts_perto(pts, [(150, -50), (150, 150), (50, 150), (50, -50)]),
    "keystone_quad: rotação de 90° gira em torno do centro (100,50)")

# perspectiva horizontal +50 (k=0.6 -> s_r=0.7): lado direito encolhe
chk(pts_perto(M.keystone_quad(R, 50, 0, 0), [(0, 0), (200, 15), (200, 85), (0, 100)]),
    "keystone_quad: perspectiva horizontal +50 encolhe lado direito (15/85)")
# perspectiva horizontal -50: lado esquerdo encolhe
chk(pts_perto(M.keystone_quad(R, -50, 0, 0), [(0, 15), (200, 0), (200, 100), (0, 85)]),
    "keystone_quad: perspectiva horizontal -50 encolhe lado esquerdo (15/85)")

# ── Arquivo de imagem inexistente (não deve crashar) ───────────────────────
store = M.ImageStore()
img, size = store.preview(str(Path(TMP_APPDATA) / "nao_existe.png"))
chk(img is None and size == (0, 0), "ImageStore.preview: arquivo inexistente -> (None,(0,0))")
chk(store.preview("") == (None, (0, 0)), "ImageStore.preview: caminho vazio -> (None,(0,0))")
chk(store.full(str(Path(TMP_APPDATA) / "nao_existe.png")) is None,
    "ImageStore.full: arquivo inexistente -> None")
chk(store.thumb(str(Path(TMP_APPDATA) / "nao_existe.png")) is None,
    "ImageStore.thumb: arquivo inexistente -> None")

# ── Isolamento: DATA_DIR aponta para a pasta temporária ────────────────────
chk(str(M.DATA_DIR).startswith(TMP_APPDATA), "isolamento: DATA_DIR fica na pasta temporária")
chk(M.CONFIG_FILE.name == "config.json", "CONFIG_FILE: nome esperado")

print(f"lógica: {OK} ok, {len(FALHAS)} falha(s)")
sys.exit(0 if not FALHAS else 1)
