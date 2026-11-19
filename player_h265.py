#!/usr/bin/env python3
"""
Player H.265 (HEVC) para PC.
Toca .h265, .hevc, .265 (inclusive gravações de câmeras/DVRs, com áudio) e também
.mp4, .mkv, .mov, .ts, .avi, .webm etc.

Rodando pelo Python (sem instalar):
  1. Python 3.8+  2. VLC 64 bits (videolan.org)  3. pip install python-vlc
  python player_h265.py [arquivo]

Atalhos: Espaço = pausar/continuar | clique duplo ou F = tela cheia | Esc = sair da tela cheia
         Setas esq/dir = -/+ 5 s | Setas cima/baixo = volume | M = mudo | O = abrir arquivo
"""
import atexit
import bisect
import mmap
import os
import re
import struct
import sys
import tempfile
import time
import webbrowser
import tkinter as tk
from array import array
from tkinter import filedialog, messagebox


def _pasta_base():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def _preparar_vlc_embutido():
    """Se existir uma pasta 'vlc' ao lado do programa (instalador), usa o VLC embutido."""
    pasta = os.path.join(_pasta_base(), "vlc")
    dll = os.path.join(pasta, "libvlc.dll")
    if not os.path.isfile(dll):
        return
    os.environ["PYTHON_VLC_LIB_PATH"] = dll
    os.environ["PYTHON_VLC_MODULE_PATH"] = pasta
    os.environ["VLC_PLUGIN_PATH"] = os.path.join(pasta, "plugins")
    os.environ["PATH"] = pasta + os.pathsep + os.environ.get("PATH", "")
    try:
        os.add_dll_directory(pasta)
    except Exception:
        pass


_preparar_vlc_embutido()

if sys.platform.startswith("win"):
    try:                                    # evita interface borrada em telas de alta resolução
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

try:
    import vlc
except (Exception, SystemExit):
    _r = tk.Tk()
    _r.withdraw()
    if messagebox.askyesno(
        "VLC não encontrado",
        "O Player H.265 precisa do VLC (versão de 64 bits) instalado.\n\n"
        "Abrir a página de download do VLC agora?",
    ):
        webbrowser.open("https://www.videolan.org/vlc/")
    sys.exit(1)

# Formatos "crus" (sem container): são convertidos para MKV antes de tocar
RAW_EXTS = {".h265", ".hevc", ".265", ".bin"}
FILETYPES = [
    ("Vídeos", "*.h265 *.hevc *.265 *.mp4 *.mkv *.mov *.ts *.m2ts *.avi *.webm"),
    ("Todos os arquivos", "*.*"),
]

# ---- Preparação de arquivos .h265 de câmeras/DVRs ----
# Câmeras gravam o .h265 "cru", com blocos privados misturados ao vídeo (cabeçalho com o
# bit "forbidden" ligado), sem duração, sem velocidade e com o áudio (G.711 A-law, 8 kHz)
# dentro desses blocos privados (0xFA). O VLC não consegue tocar isso direito.
# Aqui convertemos para um .mkv padrão (vídeo + áudio + duração + índice para avançar/voltar)
# sem recodificar nada: só reorganizamos os mesmos dados.
VALID_NAL = set(range(0, 10)) | set(range(16, 22)) | set(range(32, 41))
SLICE_NAL = set(range(0, 10)) | set(range(16, 22))
PREFIX_NAL = {32, 33, 34, 35, 39}        # começam um novo quadro
AUDIO_RATE = 8000
TEMP_FILES = []


def _nal_valido(b0, b1):
    if b0 & 0x80:
        return False                      # bloco privado do fabricante
    if (b0 & 1) or (b1 >> 3):
        return False                      # camada diferente de 0
    if (b1 & 7) == 0:
        return False
    return ((b0 >> 1) & 0x3F) in VALID_NAL


def _tabela_alaw():
    tab = []
    for a in range(256):
        v = a ^ 0x55
        t = (v & 0x0F) << 4
        seg = (v & 0x70) >> 4
        if seg == 0:
            t += 8
        else:
            t += 0x108
            if seg > 1:
                t <<= seg - 1
        tab.append(t if v & 0x80 else -t)
    return tab


def _novo_temp(sufixo):
    fd, caminho = tempfile.mkstemp(suffix=sufixo, prefix="player_h265_")
    os.close(fd)
    TEMP_FILES.append(caminho)
    return caminho


# --- Matroska (EBML) ---
def _vint(n):
    return b"\x01" + n.to_bytes(7, "big")


def _el(eid, payload):
    return eid + _vint(len(payload)) + payload


def _uint(eid, v):
    return _el(eid, int(v).to_bytes(8, "big"))


def _txt(eid, s):
    return _el(eid, s.encode())


def _flt(eid, v):
    return _el(eid, struct.pack(">d", v))


# --- leitura do SPS (tamanho, perfil...) ---
def _rbsp(nal):
    out = bytearray()
    zeros = 0
    for b in nal:
        if zeros >= 2 and b == 3:
            zeros = 0
            continue
        out.append(b)
        zeros = zeros + 1 if b == 0 else 0
    return bytes(out)


class _Bits:
    def __init__(self, data):
        self.d = data
        self.p = 0

    def u(self, n):
        v = 0
        for _ in range(n):
            v = (v << 1) | ((self.d[self.p >> 3] >> (7 - (self.p & 7))) & 1)
            self.p += 1
        return v

    def ue(self):
        z = 0
        while self.u(1) == 0:
            z += 1
        return (1 << z) - 1 + (self.u(z) if z else 0)


def _info_sps(nal):
    r = _rbsp(nal)
    b = _Bits(r)
    b.p = 16                               # pula o cabeçalho do NAL
    b.u(4)
    max_sub = b.u(3)
    nested = b.u(1)
    ptl = r[3:15]                          # perfil, compatibilidade, restrições, nível
    b.p += 96
    sub_p, sub_l = [], []
    for _ in range(max_sub):
        sub_p.append(b.u(1))
        sub_l.append(b.u(1))
    if max_sub > 0:
        for _ in range(max_sub, 8):
            b.u(2)
    for i in range(max_sub):
        if sub_p[i]:
            b.p += 88
        if sub_l[i]:
            b.p += 8
    b.ue()
    chroma = b.ue()
    if chroma == 3:
        b.u(1)
    w, h = b.ue(), b.ue()
    cl = cr = ct = cb = 0
    if b.u(1):
        cl, cr, ct, cb = b.ue(), b.ue(), b.ue(), b.ue()
    bdl, bdc = b.ue() + 8, b.ue() + 8
    sw = 2 if chroma in (1, 2) else 1
    sh = 2 if chroma == 1 else 1
    return {"ptl": ptl, "layers": max_sub + 1, "nested": nested, "chroma": chroma,
            "w": w - (cl + cr) * sw, "h": h - (ct + cb) * sh, "bdl": bdl, "bdc": bdc}


def _hvcc(vps, sps, pps, i):
    p = i["ptl"]
    c = bytes([1, p[0]]) + p[1:5] + p[5:11] + bytes([p[11]])
    c += struct.pack(">H", 0xF000)
    c += bytes([0xFC, 0xFC | (i["chroma"] & 3), 0xF8 | (i["bdl"] - 8), 0xF8 | (i["bdc"] - 8)])
    c += struct.pack(">H", 0)
    c += bytes([(i["layers"] << 3) | (i["nested"] << 2) | 3, 3])
    for tipo, nal in ((32, vps), (33, sps), (34, pps)):
        c += bytes([0x80 | tipo]) + struct.pack(">HH", 1, len(nal)) + nal
    return c


def preparar_h265(origem, fps_manual=None):
    """Converte um .h265 cru (inclusive de câmeras) em .mkv. Retorna (mkv, fps, tem_audio)."""
    with open(origem, "rb") as f:
        mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
        try:
            return _converter(mm, fps_manual)
        finally:
            mm.close()


def _converter(mm, fps_manual):
    # 1) blocos de áudio: 00 00 01 FA <codec 2B> <tamanho 2B LE> <dados>
    audio = []                              # (inicio_do_bloco, ini_dados, fim_dados)
    i = 0
    while True:
        j = mm.find(b"\x00\x00\x01\xfa", i)
        if j < 0 or j + 8 > len(mm):
            break
        tam = struct.unpack("<H", mm[j + 6:j + 8])[0]
        fim = j + 8 + tam
        if tam == 0 or fim > len(mm):
            i = j + 4
            continue
        audio.append((j, j + 8, fim))
        i = fim
    audio_ini = [a[0] for a in audio]

    def dentro_de_audio(pos):
        k = bisect.bisect_right(audio_ini, pos) - 1
        return k >= 0 and pos < audio[k][2]

    # 2) vídeo: só NALs HEVC válidos, a partir do primeiro VPS, agrupados em quadros
    pos = [m.start() for m in re.finditer(rb"\x00\x00\x01", mm)]
    pos.append(len(mm))
    ultimo = len(pos) - 2
    quadros = []                            # cada quadro: {"nals": [(ini, fim)], "key": bool, "slice": bool}
    atual = None
    primeiro_vps = None
    ps = {}
    for n in range(len(pos) - 1):
        if dentro_de_audio(pos[n]):
            continue
        ini, fim = pos[n] + 3, pos[n + 1]
        while n != ultimo and fim > ini and mm[fim - 1] == 0:
            fim -= 1
        if fim - ini < 3 or not _nal_valido(mm[ini], mm[ini + 1]):
            continue
        tipo = (mm[ini] >> 1) & 0x3F
        if primeiro_vps is None:
            if tipo != 32:
                continue
            primeiro_vps = pos[n]
        if tipo in (32, 33, 34) and tipo not in ps:
            ps[tipo] = bytes(mm[ini:fim])
        if atual is None or (tipo in PREFIX_NAL and atual["slice"]) or \
                (tipo in SLICE_NAL and (mm[ini + 2] & 0x80) and atual["slice"]):
            atual = {"nals": [], "key": False, "slice": False}
            quadros.append(atual)
        atual["nals"].append((ini, fim))
        if tipo in SLICE_NAL:
            atual["slice"] = True
            if 16 <= tipo <= 21:
                atual["key"] = True
    quadros = [q for q in quadros if q["slice"]]
    if not quadros or len(ps) < 3:
        raise ValueError("Nenhum vídeo H.265 válido encontrado no arquivo.")

    # 3) áudio alinhado ao primeiro quadro (2 blocos antes do primeiro VPS) -> PCM 16 bits
    pcm = b""
    if audio:
        k = max(0, bisect.bisect_left(audio_ini, primeiro_vps) - 2)
        dados = b"".join(bytes(mm[a[1]:a[2]]) for a in audio[k:])
        if len(dados) >= AUDIO_RATE:
            tab = _tabela_alaw()
            arr = array("h", [tab[b] for b in dados])
            if sys.byteorder == "big":
                arr.byteswap()
            pcm = arr.tobytes()
    tem_audio = len(pcm) > 0

    # 4) velocidade: a duração do áudio dá o FPS real do vídeo
    if fps_manual:
        fps = float(fps_manual)
    elif tem_audio and 5 <= len(quadros) / (len(pcm) / 2 / AUDIO_RATE) <= 60:
        fps = len(quadros) / (len(pcm) / 2 / AUDIO_RATE)
    else:
        fps = 25.0

    info = _info_sps(ps[33])
    tms = lambda k: int(round(k * 1000.0 / fps))
    bloco_audio = 640                       # 320 amostras = 40 ms
    n_audio = (len(pcm) + bloco_audio - 1) // bloco_audio

    # 5) clusters (cada um começa num quadro-chave) -> arquivo temporário
    tmp = tempfile.TemporaryFile()
    cues = []
    off = 0
    prox_audio = 0

    def simples(trilha, rel, key, dados):
        return _el(b"\xA3", bytes([0x80 | trilha]) + struct.pack(">hB", rel, 0x80 if key else 0) + dados)

    def audio_ate(limite_ms, ct, blocos):
        nonlocal prox_audio
        while prox_audio < n_audio and prox_audio * 40 < limite_ms:
            ini = prox_audio * bloco_audio
            blocos.append(simples(2, prox_audio * 40 - ct, True, pcm[ini:ini + bloco_audio]))
            prox_audio += 1

    def fechar(ct, blocos):
        nonlocal off
        c = _el(b"\x1F\x43\xB6\x75", _uint(b"\xE7", ct) + b"".join(blocos))
        tmp.write(c)
        off += len(c)

    ct, blocos, ultimo_ct = 0, [], None
    for idx, q in enumerate(quadros):
        t = tms(idx)
        novo = ultimo_ct is None or (q["key"] and t - ultimo_ct >= 1000) or t - ultimo_ct >= 8000
        if novo:
            if blocos:
                audio_ate(t, ct, blocos)
                fechar(ct, blocos)
            ct, blocos, ultimo_ct = t, [], t
            if q["key"]:
                cues.append((t, off))
        dados = b"".join(struct.pack(">I", e - s) + bytes(mm[s:e]) for s, e in q["nals"])
        blocos.append(simples(1, t - ct, q["key"], dados))
    fim_video = tms(len(quadros))
    audio_ate(fim_video, ct, blocos)
    fechar(ct, blocos)
    while prox_audio < n_audio:             # sobra de áudio depois do último quadro
        ct, blocos = prox_audio * 40, []
        audio_ate(ct + 5000, ct, blocos)
        fechar(ct, blocos)
    duracao = max(fim_video, n_audio * 40)

    # 6) cabeçalho: SeekHead, Info, Tracks, Cues (tamanhos fixos) + clusters
    video = _el(b"\xAE",
                _uint(b"\xD7", 1) + _uint(b"\x73\xC5", 1) + _uint(b"\x83", 1) + _uint(b"\x9C", 0) +
                _txt(b"\x86", "V_MPEGH/ISO/HEVC") +
                _el(b"\x63\xA2", _hvcc(ps[32], ps[33], ps[34], info)) +
                _uint(b"\x23\xE3\x83", int(1e9 / fps)) +
                _el(b"\xE0", _uint(b"\xB0", info["w"]) + _uint(b"\xBA", info["h"])))
    trilhas = video
    if tem_audio:
        trilhas += _el(b"\xAE",
                       _uint(b"\xD7", 2) + _uint(b"\x73\xC5", 2) + _uint(b"\x83", 2) + _uint(b"\x9C", 0) +
                       _txt(b"\x86", "A_PCM/INT/LIT") +
                       _el(b"\xE1", _flt(b"\xB5", float(AUDIO_RATE)) + _uint(b"\x9F", 1) + _uint(b"\x62\x64", 16)))
    tracks = _el(b"\x16\x54\xAE\x6B", trilhas)
    infoel = _el(b"\x15\x49\xA9\x66",
                 _uint(b"\x2A\xD7\xB1", 1000000) + _flt(b"\x44\x89", float(duracao)) +
                 _txt(b"\x4D\x80", "player_h265") + _txt(b"\x57\x41", "player_h265"))

    def cues_el(base):
        return _el(b"\x1C\x53\xBB\x6B", b"".join(
            _el(b"\xBB", _uint(b"\xB3", t) + _el(b"\xB7", _uint(b"\xF7", 1) + _uint(b"\xF1", base + o)))
            for t, o in cues))

    def seek_el(pi, pt, pc):
        def e(eid, p):
            return _el(b"\x4D\xBB", _el(b"\x53\xAB", eid) + _uint(b"\x53\xAC", p))
        return _el(b"\x11\x4D\x9B\x74",
                   e(b"\x15\x49\xA9\x66", pi) + e(b"\x16\x54\xAE\x6B", pt) + e(b"\x1C\x53\xBB\x6B", pc))

    n_seek = len(seek_el(0, 0, 0))
    pos_info = n_seek
    pos_tracks = pos_info + len(infoel)
    pos_cues = pos_tracks + len(tracks)
    base = pos_cues + len(cues_el(0))
    corpo = seek_el(pos_info, pos_tracks, pos_cues) + infoel + tracks + cues_el(base)
    ebml = _el(b"\x1A\x45\xDF\xA3",
               _uint(b"\x42\x86", 1) + _uint(b"\x42\xF7", 1) + _uint(b"\x42\xF2", 4) +
               _uint(b"\x42\xF3", 8) + _txt(b"\x42\x82", "matroska") +
               _uint(b"\x42\x87", 4) + _uint(b"\x42\x85", 2))
    destino = _novo_temp(".mkv")
    with open(destino, "wb") as out:
        out.write(ebml)
        out.write(b"\x18\x53\x80\x67" + _vint(len(corpo) + off))
        out.write(corpo)
        tmp.seek(0)
        while True:
            pedaco = tmp.read(1 << 20)
            if not pedaco:
                break
            out.write(pedaco)
    tmp.close()
    return destino, fps, tem_audio


def _apagar_temporarios():
    for t in list(TEMP_FILES):
        try:
            os.remove(t)
            TEMP_FILES.remove(t)
        except OSError:
            pass


atexit.register(_apagar_temporarios)


# ---- Interface ----
BG = "#0d0f13"        # fundo da janela
BAR = "#13161c"       # barra de controles
HOVER = "#232833"     # fundo dos botões ao passar o mouse
TEXT = "#eef0f6"
ICON = "#c5cad8"
MUTED = "#8b93a7"
TRACK = "#2a303b"
ACCENT = "#7c5cff"
ACCENT_HOVER = "#9279ff"
FONTE = ("Segoe UI", 9)
ESCALA = 1.0


def px(n):
    return max(1, int(round(n * ESCALA)))


def fmt(ms):
    s = max(0, int(ms // 1000))
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


class Slider(tk.Canvas):
    """Barra deslizante moderna (progresso do vídeo e volume)."""

    def __init__(self, master, command=None, on_release=None, bg=BAR, **kw):
        super().__init__(master, height=px(24), bg=bg, highlightthickness=0, bd=0,
                         cursor="hand2", **kw)
        self.value = 0.0
        self.command = command
        self.on_release = on_release
        self.dragging = False
        self.hover = False
        self.bind("<Configure>", lambda e: self.draw())
        self.bind("<Enter>", lambda e: self._hover(True))
        self.bind("<Leave>", lambda e: self._hover(False))
        self.bind("<ButtonPress-1>", self._down)
        self.bind("<B1-Motion>", self._move)
        self.bind("<ButtonRelease-1>", self._up)

    def _hover(self, estado):
        self.hover = estado
        self.draw()

    def _limites(self):
        pad = px(8)
        return pad, max(pad + 1, self.winfo_width() - pad)

    def draw(self):
        self.delete("all")
        h = self.winfo_height()
        cy = h // 2
        x0, x1 = self._limites()
        x = x0 + (x1 - x0) * self.value
        larg = px(4)
        self.create_line(x0, cy, x1, cy, fill=TRACK, width=larg, capstyle="round")
        if x > x0:
            self.create_line(x0, cy, x, cy, fill=ACCENT, width=larg, capstyle="round")
        r = px(7) if (self.hover or self.dragging) else px(5)
        self.create_oval(x - r, cy - r, x + r, cy + r, fill="#ffffff", outline="")

    def _valor(self, e):
        x0, x1 = self._limites()
        return min(1.0, max(0.0, (e.x - x0) / float(x1 - x0)))

    def _down(self, e):
        self.dragging = True
        self.value = self._valor(e)
        self.draw()
        if self.command:
            self.command(self.value)

    def _move(self, e):
        if self.dragging:
            self.value = self._valor(e)
            self.draw()
            if self.command:
                self.command(self.value)

    def _up(self, e):
        if self.dragging:
            self.dragging = False
            self.value = self._valor(e)
            self.draw()
            if self.on_release:
                self.on_release(self.value)

    def set(self, v):
        if not self.dragging:
            self.value = min(1.0, max(0.0, v))
            self.draw()


class IconButton(tk.Canvas):
    """Botão redondo com ícone desenhado (sem imagens externas)."""

    def __init__(self, master, icon, command, size=36, bg=BAR, accent=False):
        s = px(size)
        super().__init__(master, width=s, height=s, bg=bg, highlightthickness=0, bd=0,
                         cursor="hand2")
        self.icon = icon
        self.command = command
        self.size = s
        self.base_bg = bg
        self.accent = accent
        self.hover = False
        self.bind("<Enter>", lambda e: self._hover(True))
        self.bind("<Leave>", lambda e: self._hover(False))
        self.bind("<ButtonRelease-1>", self._click)
        self.draw()

    def _hover(self, estado):
        self.hover = estado
        self.draw()

    def _click(self, e):
        if 0 <= e.x < self.size and 0 <= e.y < self.size and self.command:
            self.command()

    def set_icon(self, icon):
        if icon != self.icon:
            self.icon = icon
            self.draw()

    def draw(self):
        self.delete("all")
        s = self.size
        u = s / 36.0
        lw = max(1, int(round(2 * u)))

        def P(*v):
            return [n * u for n in v]

        if self.accent:
            self.create_oval(P(1, 1, 35, 35), fill=ACCENT_HOVER if self.hover else ACCENT, outline="")
            col = "#ffffff"
        else:
            if self.hover:
                self.create_oval(P(2, 2, 34, 34), fill=HOVER, outline="")
            col = TEXT if self.hover else ICON
        i = self.icon
        if i == "play":
            self.create_polygon(P(14, 10.5, 14, 25.5, 26.5, 18), fill=col, outline="")
        elif i == "pause":
            self.create_rectangle(P(12, 11, 16.5, 25), fill=col, outline="")
            self.create_rectangle(P(19.5, 11, 24, 25), fill=col, outline="")
        elif i == "stop":
            self.create_rectangle(P(11, 11, 25, 25), fill=col, outline="")
        elif i == "open":
            self.create_polygon(P(9, 12, 16, 12, 18.5, 15, 27, 15, 27, 25, 9, 25),
                                fill="", outline=col, width=lw, joinstyle="round")
        elif i in ("volume", "mute"):
            self.create_polygon(P(9, 15, 13.5, 15, 19, 10.5, 19, 25.5, 13.5, 21, 9, 21),
                                fill=col, outline="")
            if i == "volume":
                self.create_arc(P(14, 13, 25, 23), start=-50, extent=100, style="arc",
                                outline=col, width=lw)
                self.create_arc(P(11, 9, 30, 27), start=-50, extent=100, style="arc",
                                outline=col, width=lw)
            else:
                self.create_line(P(22, 14, 28, 22), fill=col, width=lw, capstyle="round")
                self.create_line(P(28, 14, 22, 22), fill=col, width=lw, capstyle="round")
        elif i == "full":
            for pts in ((10, 15, 10, 10, 15, 10), (21, 10, 26, 10, 26, 15),
                        (10, 21, 10, 26, 15, 26), (21, 26, 26, 26, 26, 21)):
                self.create_line(P(*pts), fill=col, width=lw)
        elif i == "exitfull":
            for pts in ((15, 10, 15, 15, 10, 15), (21, 10, 21, 15, 26, 15),
                        (15, 26, 15, 21, 10, 21), (26, 21, 21, 21, 21, 26)):
                self.create_line(P(*pts), fill=col, width=lw)
        elif i == "options":
            fundo = HOVER if self.hover else self.base_bg
            for y, kx in ((12, 21), (18, 14), (24, 19)):
                self.create_line(P(10, y, 26, y), fill=col, width=lw, capstyle="round")
                self.create_oval(P(kx - 2.6, y - 2.6, kx + 2.6, y + 2.6), fill=fundo,
                                 outline=col, width=lw)
        elif i == "play_big":
            self.create_polygon(P(14.5, 10.5, 14.5, 25.5, 26, 18), fill=col, outline="")


class Player(tk.Tk):
    def __init__(self, path=None):
        global ESCALA
        super().__init__()
        ESCALA = max(1.0, self.winfo_fpixels("1i") / 96.0)
        self.title("Player H.265")
        self.configure(bg=BG)
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w, h = min(px(1040), sw - 80), min(px(640), sh - 120)
        self.geometry(f"{w}x{h}+{(sw - w) // 2}+{max(0, (sh - h) // 3)}")
        self.minsize(min(px(640), w), min(px(400), h))
        self._icone()

        self.instance = vlc.Instance("--no-xlib", "--quiet", "--no-video-title-show")
        self.player = self.instance.media_player_new()
        try:                                # deixa o mouse/teclado para a nossa janela
            self.player.video_set_mouse_input(False)
            self.player.video_set_key_input(False)
        except Exception:
            pass

        self.fullscreen = False
        self.muted = False
        self.volume = 80
        self.bar_visible = True
        self.last_ptr = None
        self.last_move = time.time()
        self.click_job = None
        self.fps_var = tk.StringVar(value="Auto")
        self.rate_var = tk.DoubleVar(value=1.0)

        # Área do vídeo
        self.video = tk.Frame(self, bg="black")
        self.video.pack(fill="both", expand=True)
        self._montar_tela_vazia()

        # Barra de controles
        self.bar = tk.Frame(self, bg=BAR)
        self.bar.pack(fill="x", side="bottom")
        topo = tk.Frame(self.bar, bg=BAR)
        topo.pack(fill="x", padx=px(16), pady=(px(8), 0))
        self.lbl_cur = tk.Label(topo, text="00:00", bg=BAR, fg=MUTED, font=FONTE, width=7, anchor="e")
        self.lbl_cur.pack(side="left")
        self.seek = Slider(topo, command=self._seek_preview, on_release=self._seek_final)
        self.seek.pack(side="left", fill="x", expand=True, padx=px(6))
        self.lbl_tot = tk.Label(topo, text="00:00", bg=BAR, fg=MUTED, font=FONTE, width=7, anchor="w")
        self.lbl_tot.pack(side="left")

        base = tk.Frame(self.bar, bg=BAR)
        base.pack(fill="x", padx=px(12), pady=(px(2), px(10)))
        self.btn_open = IconButton(base, "open", self.open_file)
        self.btn_open.pack(side="left")
        self.btn_play = IconButton(base, "play", self.toggle, size=40, accent=True)
        self.btn_play.pack(side="left", padx=px(8))
        self.btn_stop = IconButton(base, "stop", self.stop)
        self.btn_stop.pack(side="left")
        self.btn_full = IconButton(base, "full", self.toggle_fullscreen)
        self.btn_full.pack(side="right")
        self.btn_opts = IconButton(base, "options", self._menu_opcoes)
        self.btn_opts.pack(side="right")
        self.vol_slider = Slider(base, command=self._set_volume, width=px(90))
        self.vol_slider.pack(side="right", padx=(0, px(4)))
        self.vol_slider.set(self.volume / 100.0)
        self.btn_vol = IconButton(base, "volume", self.toggle_mute)
        self.btn_vol.pack(side="right")
        self.lbl_nome = tk.Label(base, text="", bg=BAR, fg=MUTED, font=FONTE, anchor="w")
        self.lbl_nome.pack(side="left", fill="x", expand=True, padx=px(14))

        # Atalhos
        self.bind("<space>", lambda e: self.toggle())
        self.bind("<o>", lambda e: self.open_file())
        self.bind("<f>", lambda e: self.toggle_fullscreen())
        self.bind("<m>", lambda e: self.toggle_mute())
        self.bind("<Escape>", lambda e: self.toggle_fullscreen(False))
        self.bind("<Left>", lambda e: self.jump(-5000))
        self.bind("<Right>", lambda e: self.jump(5000))
        self.bind("<Up>", lambda e: self._mudar_volume(5))
        self.bind("<Down>", lambda e: self._mudar_volume(-5))
        self.video.bind("<Button-1>", self._clique_video)
        self.video.bind("<Double-Button-1>", self._duplo_clique_video)
        self.protocol("WM_DELETE_WINDOW", self._fechar)

        self.update_idletasks()
        self._anexar_janela()
        self._aplicar_volume()
        self.after(30, self._barra_escura)
        self.after(200, self._tick)
        self.focus_set()
        if path:
            self.after(250, lambda: self.play(path))

    # ---- aparência ----
    def _icone(self):
        for pasta in (getattr(sys, "_MEIPASS", ""), _pasta_base()):
            caminho = os.path.join(pasta, "icon.ico")
            if pasta and os.path.isfile(caminho):
                try:
                    self.iconbitmap(caminho)
                except Exception:
                    pass
                return

    def _barra_escura(self):
        if not sys.platform.startswith("win"):
            return
        try:
            import ctypes
            hwnd = ctypes.windll.user32.GetParent(self.winfo_id())
            ligado = ctypes.c_int(1)
            for atributo in (20, 19):
                if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                        hwnd, atributo, ctypes.byref(ligado), ctypes.sizeof(ligado)) == 0:
                    break
        except Exception:
            pass

    def _montar_tela_vazia(self):
        self.empty = tk.Frame(self.video, bg="black")
        self.big = IconButton(self.empty, "play_big", self.open_file, size=88, bg="black", accent=True)
        self.big.pack()
        self.empty_title = tk.Label(self.empty, text="Abrir um vídeo", bg="black", fg=TEXT,
                                    font=("Segoe UI Semibold", 14))
        self.empty_title.pack(pady=(px(16), px(2)))
        self.empty_sub = tk.Label(self.empty, text="Aceita H.265, HEVC, MP4, MKV e outros formatos",
                                  bg="black", fg=MUTED, font=FONTE)
        self.empty_sub.pack()
        self.empty.place(relx=0.5, rely=0.5, anchor="center")

    def _estado_vazio(self, titulo, sub):
        self.empty_title.config(text=titulo)
        self.empty_sub.config(text=sub)
        self.empty.place(relx=0.5, rely=0.5, anchor="center")
        self.update_idletasks()

    # ---- integração com a janela ----
    def _anexar_janela(self):
        wid = self.video.winfo_id()
        if sys.platform.startswith("win"):
            self.player.set_hwnd(wid)
        elif sys.platform == "darwin":
            self.player.set_nsobject(wid)
        else:
            self.player.set_xwindow(wid)

    # ---- ações ----
    def open_file(self):
        path = filedialog.askopenfilename(title="Escolher vídeo", filetypes=FILETYPES)
        if path:
            self.play(path)

    def play(self, path):
        if not os.path.isfile(path):
            messagebox.showerror("Arquivo não encontrado", path)
            return
        play_path = path
        if os.path.splitext(path)[1].lower() in RAW_EXTS:
            self.player.stop()
            _apagar_temporarios()
            self._estado_vazio("Preparando o vídeo...", "Isso leva alguns segundos")
            sel = self.fps_var.get()
            try:
                play_path, _fps, _audio = preparar_h265(path, None if sel == "Auto" else float(sel))
            except Exception as e:
                self._estado_vazio("Abrir um vídeo", "Aceita H.265, HEVC, MP4, MKV e outros formatos")
                messagebox.showerror("Não foi possível abrir o vídeo", str(e))
                return
        self.player.set_media(self.instance.media_new(play_path))
        self.empty.place_forget()
        self.player.play()
        self.player.set_rate(self.rate_var.get())
        self.after(400, self._aplicar_volume)
        self.btn_play.set_icon("pause")
        self.lbl_nome.config(text=os.path.basename(path))
        self.title(f"{os.path.basename(path)} - Player H.265")
        self.focus_set()

    def toggle(self):
        if self.player.get_media() is None:
            self.open_file()
            return
        estado = self.player.get_state()
        if estado == vlc.State.Ended:
            self.player.stop()
            self.player.play()
        elif estado == vlc.State.Stopped:
            self.player.play()
        else:
            self.player.pause()
        self.after(150, self._sync_botao)

    def stop(self):
        self.player.stop()
        self.seek.set(0)
        self.lbl_cur.config(text="00:00")
        self.lbl_tot.config(text="00:00")
        self.btn_play.set_icon("play")

    def _sync_botao(self):
        self.btn_play.set_icon("pause" if self.player.is_playing() else "play")

    def jump(self, delta_ms):
        if self.player.get_length() > 0:
            self.player.set_time(max(0, self.player.get_time() + delta_ms))

    def _seek_preview(self, v):
        length = self.player.get_length()
        if length > 0:
            self.lbl_cur.config(text=fmt(v * length))

    def _seek_final(self, v):
        if self.player.get_length() > 0:
            self.player.set_position(v)

    # ---- volume ----
    def _aplicar_volume(self):
        self.player.audio_set_volume(int(self.volume))
        self.player.audio_set_mute(bool(self.muted))

    def _set_volume(self, v):
        self.volume = int(v * 100)
        if self.muted and self.volume > 0:
            self.muted = False
        self._aplicar_volume()
        self._icone_volume()

    def _mudar_volume(self, delta):
        self.volume = min(100, max(0, self.volume + delta))
        self.vol_slider.set(self.volume / 100.0)
        if self.volume > 0:
            self.muted = False
        self._aplicar_volume()
        self._icone_volume()

    def toggle_mute(self):
        self.muted = not self.muted
        self._aplicar_volume()
        self._icone_volume()

    def _icone_volume(self):
        self.btn_vol.set_icon("mute" if (self.muted or self.volume == 0) else "volume")

    # ---- menu de opções ----
    def _menu_opcoes(self):
        m = tk.Menu(self, tearoff=0)
        vel = tk.Menu(m, tearoff=0)
        for v in (0.5, 0.75, 1.0, 1.25, 1.5, 2.0):
            vel.add_radiobutton(label="Normal" if v == 1.0 else f"{v:g}x", value=v,
                                variable=self.rate_var,
                                command=lambda: self.player.set_rate(self.rate_var.get()))
        m.add_cascade(label="Velocidade de reprodução", menu=vel)
        fps = tk.Menu(m, tearoff=0)
        for v in ("Auto", "12.5", "15", "25", "30"):
            fps.add_radiobutton(label="Automático" if v == "Auto" else v, value=v,
                                variable=self.fps_var)
        m.add_cascade(label="FPS de arquivos .h265 (vale ao abrir)", menu=fps)
        m.update_idletasks()
        x = self.btn_opts.winfo_rootx()
        y = self.btn_opts.winfo_rooty() - m.winfo_reqheight()
        try:
            m.tk_popup(x, max(0, y))
        finally:
            m.grab_release()

    # ---- tela cheia e cliques no vídeo ----
    def toggle_fullscreen(self, state=None):
        self.fullscreen = (not self.fullscreen) if state is None else state
        self.attributes("-fullscreen", self.fullscreen)
        self.btn_full.set_icon("exitfull" if self.fullscreen else "full")
        self._mostrar_barra()
        self.last_move = time.time()

    def _mostrar_barra(self):
        if not self.bar_visible:
            self.bar.pack(fill="x", side="bottom")
            self.bar_visible = True
        self.video.config(cursor="")

    def _esconder_barra(self):
        self.bar.pack_forget()
        self.bar_visible = False
        self.video.config(cursor="none")

    def _clique_video(self, _e):
        self.focus_set()
        if self.click_job is None:          # espera para ver se vira clique duplo
            self.click_job = self.after(250, self._clique_simples)

    def _clique_simples(self):
        self.click_job = None
        if self.player.get_media() is not None:
            self.toggle()

    def _duplo_clique_video(self, _e):
        if self.click_job is not None:
            self.after_cancel(self.click_job)
            self.click_job = None
        self.toggle_fullscreen()

    # ---- atualização periódica ----
    def _tick(self):
        try:
            length = self.player.get_length()
            if length > 0 and not self.seek.dragging:
                self.seek.set(self.player.get_position())
                self.lbl_cur.config(text=fmt(self.player.get_time()))
            if length > 0:
                self.lbl_tot.config(text=fmt(length))
            self._sync_botao()

            ptr = self.winfo_pointerxy()
            topo_barra = self.bar.winfo_rooty()
            sobre_barra = self.bar_visible and topo_barra <= ptr[1] <= topo_barra + self.bar.winfo_height()
            if ptr != self.last_ptr or sobre_barra:
                self.last_ptr = ptr
                self.last_move = time.time()
                if self.fullscreen and not self.bar_visible:
                    self._mostrar_barra()
            elif (self.fullscreen and self.bar_visible and self.player.is_playing()
                  and time.time() - self.last_move > 2.5):
                self._esconder_barra()
        finally:
            self.after(200, self._tick)

    def _fechar(self):
        try:
            self.player.stop()
            self.player.release()
        except Exception:
            pass
        self.destroy()


def main():
    app = Player(sys.argv[1] if len(sys.argv) > 1 else None)
    app.mainloop()


if __name__ == "__main__":
    main()
