#!/usr/bin/python3 -I
"""Configurador Redragon M917 PRO (receptor Compx 25a7:fa7c / cable 25a7:fa7b) para Linux.

Protocolo: ver docs/PROTOCOL.md del repositorio.
Solo usa los comandos 0x03 (conexión), 0x04 (batería), 0x07 (escribir) y 0x08 (leer).
"""
import os, sys, glob, time, fcntl, select, copy

MEM_SIZE = 0xC0
BACKUP_DIR = os.path.expanduser("~/.local/share/redragon-m917/copias")

# ---------------------------------------------------------------- protocolo
def _feat_set(n): return (3 << 30) | (n << 16) | (ord('H') << 8) | 0x06

def _pkt(cmd, args=b""):
    b = bytearray(17); b[0] = 0x08; b[1] = cmd; b[2:2 + len(args)] = args
    b[16] = (0x55 - sum(b[:16])) & 0xff
    return bytes(b)

def pair(v): return bytes([v & 0xff, (0x55 - v) & 0xff])

def block(*vals):
    """bytes + byte de control (0x55 - suma)."""
    return bytes(list(vals) + [(0x55 - sum(vals)) & 0xff])


class MouseError(Exception):
    pass


def find_nodes():
    wired, wireless = [], []
    for h in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        try:
            ue = open(h + "/device/uevent").read()
            desc = open(h + "/device/report_descriptor", "rb").read().hex()
        except OSError:
            continue
        # only the M917 (receiver FA7C / cable FA7B): other Compx mice may use a different memory map
        if not any(f"HID_ID=0003:000025A7:0000{pid}" in ue for pid in ("FA7B", "FA7C")):
            continue
        if "0602ff0902a1018508" not in desc:
            continue
        (wired if "0000FA7B" in ue else wireless).append("/dev/" + os.path.basename(h))
    return wired, wireless


class Mouse:
    def __init__(self):
        self.fd = None; self.node = None; self.cable = False

    def open(self):
        self.close()
        wired, wireless = find_nodes()
        self.cable = bool(wired)
        last = "No se encontró el receptor ni el cable del mouse."
        for node in wired + wireless:
            try:
                fd = os.open(node, os.O_RDWR | os.O_NONBLOCK)
            except OSError as e:
                last = f"Sin permiso para abrir {node}: {e}"; continue
            self.fd, self.node = fd, node
            try:
                st = self.query(0x03)
                if st[6]:
                    return
                last = "El mouse está apagado, dormido o en modo Bluetooth. Movelo o pasalo a 2.4 GHz."
            except MouseError as e:
                last = str(e)
            os.close(fd); self.fd = None
        raise MouseError(last)

    def close(self):
        if self.fd is not None:
            try: os.close(self.fd)
            except OSError: pass
        self.fd = None

    def query(self, cmd, args=b"", match=None, tries=4, timeout=0.5):
        if self.fd is None:
            raise MouseError("Mouse no conectado")
        for _ in range(tries):
            while select.select([self.fd], [], [], 0)[0]:
                try: os.read(self.fd, 64)
                except OSError: break
            try:
                fcntl.ioctl(self.fd, _feat_set(17), _pkt(cmd, args))
            except OSError as e:
                raise MouseError(f"Error al enviar al mouse: {e}")
            end = time.time() + timeout
            while time.time() < end:
                if select.select([self.fd], [], [], 0.03)[0]:
                    r = os.read(self.fd, 64)
                    if len(r) >= 17 and r[0] == 0x09 and r[1] == cmd and (match is None or match(r)):
                        return r
            time.sleep(0.05)
        raise MouseError(f"El mouse no respondió (comando 0x{cmd:02x}). ¿Está dormido? Movelo y reintentá.")

    def read(self, addr, n):
        out = bytearray()
        while n > 0:
            k = min(10, n)
            r = self.query(0x08, bytes([0, addr >> 8, addr & 0xff, k]),
                           match=lambda r, a=addr: r[3] == a >> 8 and r[4] == a & 0xff)
            out += r[6:6 + k]; addr += k; n -= k
        return bytes(out)

    def write(self, addr, data):
        data = bytes(data)
        while data:
            chunk, data = data[:10], data[10:]
            r = self.query(0x07, bytes([0, addr >> 8, addr & 0xff, len(chunk)]) + chunk,
                           match=lambda r, a=addr: r[3] == a >> 8 and r[4] == a & 0xff)
            if r[2] != 0:
                raise MouseError(f"El mouse rechazó la escritura en 0x{addr:02x} (estado {r[2]})")
            addr += len(chunk)
            time.sleep(0.01)

    def battery(self):
        r = self.query(0x04)
        if r[7] == 1 and r[6] == 1:
            return 100, True, True
        return r[6], bool(r[7]) or self.cable, False

    def dump(self):
        return self.read(0, MEM_SIZE)


# ---------------------------------------------------------------- modelo de datos
RATES = [(1, 1000), (2, 500), (4, 250), (8, 125)]
BUTTONS = [("Izquierdo", 0x60), ("Derecho", 0x64), ("Rueda (clic)", 0x68),
           ("Lateral atrás", 0x6C), ("Lateral adelante", 0x70), ("Botón DPI", 0x74)]
FUNCS = [("Clic izquierdo", (0x01, 0x01, 0x00)), ("Clic derecho", (0x01, 0x02, 0x00)),
         ("Clic medio", (0x01, 0x04, 0x00)), ("Atrás", (0x01, 0x08, 0x00)),
         ("Adelante", (0x01, 0x10, 0x00)), ("DPI en ciclo", (0x02, 0x01, 0x00)),
         ("DPI + (experimental)", (0x02, 0x02, 0x00)), ("DPI − (experimental)", (0x02, 0x03, 0x00)),
         ("Deshabilitado", (0x00, 0x00, 0x00))]
LED_TABLE = [0x10, 0x1E, 0x3C, 0x5A, 0x80, 0x96, 0xB4, 0xD2, 0xE6, 0xFF]   # niveles 1..10 (0x4C)


def dpi_decode(b):
    x, y, fl = b[0], b[1], b[2]
    n = ((fl >> 2) & 3) << 8 | x
    return (n + 1) * (100 if fl & 1 else 50)

def dpi_encode(dpi):
    n = max(0, min(519, dpi // 50 - 1))
    lo, hi = n & 0xff, n >> 8
    fl = ((hi << 2) << 4) | (hi << 2)
    return block(lo, lo, fl)


def decode(m):
    s = {}
    s["rate"] = m[0]
    s["levels"] = m[2]
    s["level"] = m[4]
    s["lod"] = m[0x0A]
    s["dpi"] = [dpi_decode(m[0x0C + 4 * i:0x10 + 4 * i]) for i in range(8)]
    s["color"] = [tuple(m[0x2C + 4 * i:0x2F + 4 * i]) for i in range(8)]
    s["ledmode"], s["ledA"], s["ledB"] = m[0x4C], m[0x4E], m[0x50]
    s["buttons"] = [tuple(m[a:a + 3]) for _, a in BUTTONS]
    s["debounce"], s["msync"], s["sleep"] = m[0xA9], m[0xAB], m[0xAD]
    s["angle"], s["ripple"], s["offmove"] = m[0xAF], m[0xB1], m[0xB3]
    return s


def changes(old, new):
    """Lista de (dirección, bytes, descripción) para pasar de old a new."""
    w = []
    def p(key, addr, label):
        if old[key] != new[key]:
            w.append((addr, pair(new[key]), label))
    p("rate", 0x00, "polling rate"); p("levels", 0x02, "cantidad de niveles DPI")
    p("level", 0x04, "nivel DPI activo"); p("lod", 0x0A, "LOD")
    for i in range(8):
        if old["dpi"][i] != new["dpi"][i]:
            w.append((0x0C + 4 * i, dpi_encode(new["dpi"][i]), f"DPI nivel {i+1}"))
        if old["color"][i] != new["color"][i]:
            w.append((0x2C + 4 * i, block(*new["color"][i]), f"color nivel {i+1}"))
    if (old["ledmode"], old["ledA"], old["ledB"]) != (new["ledmode"], new["ledA"], new["ledB"]):
        w.append((0x4C, pair(new["ledmode"]) + pair(new["ledA"]) + pair(new["ledB"]), "luz de la rueda"))
    for i, (_, a) in enumerate(BUTTONS):
        if old["buttons"][i] != new["buttons"][i]:
            w.append((a, block(*new["buttons"][i]), f"botón {BUTTONS[i][0]}"))
    p("debounce", 0xA9, "debounce"); p("msync", 0xAB, "motion sync"); p("sleep", 0xAD, "tiempo para dormir")
    p("angle", 0xAF, "angle snapping"); p("ripple", 0xB1, "ripple control"); p("offmove", 0xB3, "apagar luz al mover")
    return w


def save_backup(mem, tag="auto"):
    os.makedirs(BACKUP_DIR, exist_ok=True)
    fn = os.path.join(BACKUP_DIR, time.strftime(f"m917_%Y%m%d_%H%M%S_{tag}.bin"))
    open(fn, "wb").write(mem)
    return fn


# ---------------------------------------------------------------- interfaz
RES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "res")
RED = "#e01b24"

STYLE = f"""
QWidget {{ background: #141516; color: #e6e6e6; font-size: 10pt; }}
QLabel#title {{ font-size: 15pt; font-weight: bold; color: white; }}
QLabel#sub {{ color: #9a9a9a; }}
QLabel#help {{ color: #8f8f8f; font-size: 9pt; }}
QLabel#pending {{ color: #ff8a8f; }}
QFrame#card {{ background: #1d1f21; border: 1px solid #2c2f32; border-radius: 10px; }}
QFrame#card[active="true"] {{ border: 1px solid {RED}; }}
QFrame#card QLabel, QFrame#card QCheckBox, QWidget#row {{ background: transparent; }}
QFrame#head, QFrame#foot {{ background: #0e0f10; }}
QFrame#head {{ border-bottom: 1px solid #262829; }}
QFrame#foot {{ border-top: 1px solid #262829; }}
QFrame#head QLabel, QFrame#foot QLabel {{ background: transparent; }}
QListWidget {{ background: #101112; border: none; border-right: 1px solid #262829; outline: 0; padding-top: 8px; }}
QListWidget::item {{ padding: 12px 14px; border-left: 3px solid transparent; color: #bdbdbd; }}
QListWidget::item:selected {{ background: #1f2224; border-left: 3px solid {RED}; color: white; }}
QListWidget::item:hover {{ background: #1a1c1e; }}
QPushButton {{ background: #26292c; border: 1px solid #3a3d40; border-radius: 6px; padding: 7px 14px; }}
QPushButton:hover {{ border-color: {RED}; }}
QPushButton:checked {{ background: {RED}; border-color: {RED}; color: white; font-weight: bold; }}
QPushButton:disabled {{ color: #666; border-color: #2a2a2a; }}
QPushButton#apply {{ background: {RED}; border-color: {RED}; color: white; font-weight: bold; padding: 8px 22px; }}
QPushButton#apply:disabled {{ background: #3a2224; border-color: #3a2224; color: #8a6a6c; }}
QPushButton#chip {{ padding: 3px 7px; font-size: 8pt; border-radius: 10px; color: #bbb; }}
QPushButton#keybtn {{ text-align: left; padding: 6px 12px; min-width: 150px; }}
QSpinBox, QComboBox {{ background: #222528; border: 1px solid #3a3d40; border-radius: 5px; padding: 4px 6px; }}
QSlider::groove:horizontal {{ height: 4px; background: #34383b; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {RED}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: white; width: 14px; margin: -6px 0; border-radius: 7px; }}
QCheckBox::indicator {{ width: 34px; height: 18px; border-radius: 9px; background: #3a3d40; }}
QCheckBox::indicator:checked {{ background: {RED}; }}
QScrollArea {{ border: none; }}
QToolTip {{ background: #222; color: white; border: 1px solid {RED}; }}
"""

# posición de cada botón en res/mouse.png: (índice en BUTTONS, x del punto, y del punto, lado)
HOTSPOTS = [(0, 176, 40, "L"), (2, 233, 72, "L"), (4, 127, 145, "L"), (3, 129, 199, "L"),
            (1, 287, 40, "R"), (5, 233, 136, "R")]

ADV_HELP = {
    "lod": "Altura a la que el sensor deja de leer cuando levantás el mouse. 1 mm: el cursor no se "
           "mueve al levantarlo y reacomodarlo (ideal para juegos con sensibilidad baja). 2 mm: tolera "
           "mejor superficies irregulares o mousepads gruesos.",
    "debounce": "Tiempo que el mouse ignora el rebote del switch después de un clic. Más bajo = el clic "
                "registra un poquito antes, pero si es muy bajo puede aparecer doble clic fantasma. "
                "El fabricante recomienda 8 ms; si notás doble clic, subilo.",
    "msync": "Sincroniza las lecturas del sensor con el momento en que la PC pide datos. El movimiento "
             "queda más parejo y consistente, a cambio de un retraso mínimo (menos de 1 ms).",
    "sleep": "Tiempo sin moverlo antes de que el mouse se duerma para ahorrar batería. Se despierta "
             "al moverlo o hacer clic. Más corto = más batería; más largo = menos 'despertares'.",
    "angle": "Corrige el movimiento para que las líneas casi rectas salgan perfectamente rectas. "
             "Sirve para dibujar o en Office; en juegos conviene apagado porque altera tu movimiento real.",
    "ripple": "Suaviza el pequeño temblor del sensor a DPI altos. Da un cursor más estable pero agrega "
              "algo de retraso; en general conviene apagado salvo que uses DPI muy altos.",
    "offmove": "Apaga la luz de la rueda mientras movés el mouse y la prende cuando lo dejás quieto. "
               "Ahorra un poco de batería.",
    "rate": "Cuántas veces por segundo el mouse le informa su posición a la PC. 1000 Hz = 1 ms entre "
            "reportes, el más fluido. Menos Hz = algo más de batería. Queda guardado en el mouse.",
}


def gui():
    from PyQt6 import QtWidgets as W, QtGui as G, QtCore as C

    app = W.QApplication(sys.argv)
    app.setApplicationName("Redragon M917")
    app.setDesktopFileName("redragon-m917")
    app.setStyleSheet(STYLE)

    def pix(name):
        return G.QPixmap(os.path.join(RES, name))

    def help_label(text):
        l = W.QLabel(text); l.setObjectName("help"); l.setWordWrap(True); return l

    def card():
        f = W.QFrame(); f.setObjectName("card"); return f

    def func_name(code):
        return next((lab for lab, c in FUNCS if c == tuple(code)), "Otro (" + " ".join(f"{x:02X}" for x in code) + ")")

    # ---------- página de botones: foto del mouse con cada botón señalado
    class MouseCanvas(W.QWidget):
        clicked = C.pyqtSignal(int)

        def __init__(self):
            super().__init__()
            self.img = pix("mouse.png"); self.btns = {}
            self.setMinimumSize(self.img.width() + 2 * 230, self.img.height() + 40)
            for idx, x, y, side in HOTSPOTS:
                b = W.QPushButton(self); b.setObjectName("keybtn")
                b.setCursor(C.Qt.CursorShape.PointingHandCursor)
                b.clicked.connect(lambda _, i=idx: self.clicked.emit(i))
                self.btns[idx] = (b, x, y, side)

        def origin(self):
            return C.QPoint((self.width() - self.img.width()) // 2, (self.height() - self.img.height()) // 2)

        def set_text(self, idx, title, func, changed):
            b = self.btns[idx][0]
            b.setText(f"{title}\n{func}{'  •' if changed else ''}")
            b.setStyleSheet(f"border-color: {RED};" if changed else "")
            b.adjustSize(); self.place()

        def place(self):
            o = self.origin()
            bottom = {"L": -10 ** 6, "R": -10 ** 6}
            for idx, (b, x, y, side) in sorted(self.btns.items(), key=lambda kv: kv[1][2]):
                bx = o.x() - 30 - b.width() if side == "L" else o.x() + self.img.width() + 30
                by = max(o.y() + y - b.height() // 2, bottom[side] + 10)
                b.move(bx, by); bottom[side] = by + b.height()

        def resizeEvent(self, e):
            self.place()

        def paintEvent(self, e):
            p = G.QPainter(self); p.setRenderHint(G.QPainter.RenderHint.Antialiasing)
            grad = G.QRadialGradient(C.QPointF(self.width() / 2, self.height() / 2), self.width() / 2)
            grad.setColorAt(0, G.QColor("#26292b")); grad.setColorAt(1, G.QColor("#141516"))
            p.fillRect(self.rect(), grad)
            o = self.origin(); p.drawPixmap(o, self.img)
            pen = G.QPen(G.QColor(RED)); pen.setWidth(2); p.setPen(pen)
            for idx, (b, x, y, side) in self.btns.items():
                dot = C.QPointF(o.x() + x, o.y() + y)
                elbow_x = o.x() - 12 if side == "L" else o.x() + self.img.width() + 12
                end_x = b.x() + b.width() if side == "L" else b.x()
                ly = b.y() + b.height() / 2
                p.setBrush(C.Qt.BrushStyle.NoBrush)
                p.drawPolyline(G.QPolygonF([dot, C.QPointF(elbow_x, dot.y()), C.QPointF(end_x, ly)]))
                p.setBrush(G.QColor(RED)); p.drawEllipse(dot, 5, 5)

    import math
    LOG_MIN, LOG_MAX = math.log(50), math.log(26000)

    def slider_to_dpi(v):
        return max(50, min(26000, int(round(math.exp(LOG_MIN + (LOG_MAX - LOG_MIN) * v / 1000) / 50)) * 50))

    def dpi_to_slider(d):
        return int(round((math.log(max(50, d)) - LOG_MIN) / (LOG_MAX - LOG_MIN) * 1000))

    class DpiLadder(W.QWidget):
        """Escala logarítmica 50-26000 con un punto por nivel, del color de la rueda."""
        def __init__(self):
            super().__init__(); self.levels = []; self.active = 0; self.setFixedHeight(104)

        def set(self, levels, active):
            self.levels, self.active = levels, active; self.update()

        def paintEvent(self, e):
            p = G.QPainter(self); p.setRenderHint(G.QPainter.RenderHint.Antialiasing)
            r = self.rect().adjusted(40, 0, -40, 0); y = 62
            x_of = lambda d: r.left() + r.width() * dpi_to_slider(d) / 1000
            p.setPen(G.QPen(G.QColor("#34383b"), 6, cap=C.Qt.PenCapStyle.RoundCap)); p.drawLine(r.left(), y, r.right(), y)
            p.setPen(G.QColor("#6d7174")); f = p.font(); f.setPointSize(8); p.setFont(f)
            for d in (50, 400, 1600, 6400, 26000):
                x = x_of(d); p.drawLine(int(x), y + 8, int(x), y + 13)
                p.drawText(C.QRectF(x - 30, y + 14, 60, 16), C.Qt.AlignmentFlag.AlignCenter, str(d))
            f.setPointSize(9); f.setBold(True); p.setFont(f)
            for i, (d, col) in enumerate(self.levels):
                x = x_of(d); act = i == self.active; rad = 11 if act else 7
                if act:
                    p.setPen(C.Qt.PenStyle.NoPen); glow = G.QColor(*col); glow.setAlpha(70)
                    p.setBrush(glow); p.drawEllipse(C.QPointF(x, y), 18, 18)
                p.setPen(G.QPen(G.QColor("white" if act else "#1d1f21"), 2)); p.setBrush(G.QColor(*col))
                p.drawEllipse(C.QPointF(x, y), rad, rad)
                p.setPen(G.QColor("white" if act else "#b0b0b0"))
                ty = y - 58 if i % 2 == 0 else y - 38          # filas alternadas para que no se pisen
                p.drawText(C.QRectF(x - 45, ty, 90, 18), C.Qt.AlignmentFlag.AlignCenter, f"{i+1} · {d}")

    class WheelPreview(W.QWidget):
        """Dibujo de la rueda iluminada con el color del nivel activo y el brillo elegido."""
        def __init__(self):
            super().__init__(); self.color = (255, 0, 0); self.level = 10; self.on = True; self.setFixedSize(260, 330)

        def set(self, color, level, on):
            self.color, self.level, self.on = color, level, on; self.update()

        def paintEvent(self, e):
            p = G.QPainter(self); p.setRenderHint(G.QPainter.RenderHint.Antialiasing)
            cx, cy = self.width() / 2, self.height() / 2
            body = G.QPainterPath(); body.addRoundedRect(C.QRectF(cx - 110, 6, 220, 318), 100, 100)
            g = G.QLinearGradient(0, 0, 0, self.height()); g.setColorAt(0, G.QColor("#3b3e41")); g.setColorAt(1, G.QColor("#1b1c1e"))
            p.fillPath(body, g); p.setPen(G.QPen(G.QColor("#4a4d50"), 2)); p.drawPath(body)
            p.drawLine(C.QPointF(cx, 10), C.QPointF(cx, cy - 75)); p.drawLine(C.QPointF(cx, cy + 75), C.QPointF(cx, cy + 105))
            alpha = (40 + 21 * self.level) if self.on else 0
            col = G.QColor(*self.color)
            if self.on:
                glow = G.QRadialGradient(C.QPointF(cx, cy), 95); c1 = G.QColor(col); c1.setAlpha(int(alpha * 0.8))
                c2 = G.QColor(col); c2.setAlpha(0); glow.setColorAt(0, c1); glow.setColorAt(1, c2)
                p.setPen(C.Qt.PenStyle.NoPen); p.setBrush(glow); p.drawEllipse(C.QPointF(cx, cy), 95, 95)
            slot = C.QRectF(cx - 22, cy - 70, 44, 140)
            p.setPen(G.QPen(G.QColor("#0c0c0d"), 3)); p.setBrush(G.QColor("#111213")); p.drawRoundedRect(slot, 18, 18)
            wheel = slot.adjusted(7, 8, -7, -8)
            p.setPen(C.Qt.PenStyle.NoPen); p.setBrush(G.QColor("#232527")); p.drawRoundedRect(wheel, 12, 12)
            stripe = G.QColor(col) if self.on else G.QColor("#3a3d40")
            if self.on: stripe.setAlpha(alpha)
            p.setBrush(stripe)
            for i in range(8):
                y = wheel.top() + 10 + i * (wheel.height() - 20) / 7.0
                p.drawRoundedRect(C.QRectF(wheel.left() + 4, y - 3, wheel.width() - 8, 6), 3, 3)

    class Win(W.QWidget):
        def __init__(self):
            super().__init__()
            self.setWindowTitle("Redragon M917")
            self.setWindowIcon(G.QIcon.fromTheme("redragon-m917-config", G.QIcon(pix("mouse.png"))))
            self.mouse = Mouse(); self.mem = None; self.cur = None; self.loading = False
            self.btn_codes = [None] * 6; self.colors = [(0, 0, 0)] * 8
            root = W.QVBoxLayout(self); root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)

            # cabecera
            head = W.QFrame(); head.setObjectName("head")
            h = W.QHBoxLayout(head); h.setContentsMargins(18, 10, 18, 10)
            self.dot = W.QLabel("●"); self.dot.setStyleSheet("color:#666; font-size: 12pt")
            self.status = W.QLabel("Buscando mouse…"); self.status.setObjectName("sub")
            self.batico = W.QLabel(); self.bat = W.QLabel(""); self.bat.setStyleSheet("font-weight:bold; font-size: 11pt")
            h.addWidget(self.dot); h.addWidget(self.status, 1)
            h.addWidget(self.batico); h.addSpacing(4); h.addWidget(self.bat)
            root.addWidget(head)

            self.outer = W.QStackedWidget(); root.addWidget(self.outer, 1)
            wait = W.QWidget(); wl = W.QVBoxLayout(wait); wl.addStretch()
            wimg = W.QLabel(); wimg.setPixmap(pix("mouse.png").scaledToWidth(220, C.Qt.TransformationMode.SmoothTransformation))
            wimg.setAlignment(C.Qt.AlignmentFlag.AlignCenter); wl.addWidget(wimg)
            self.wait_text = W.QLabel("Buscando el mouse…"); self.wait_text.setObjectName("title")
            self.wait_text.setAlignment(C.Qt.AlignmentFlag.AlignCenter); wl.addWidget(self.wait_text)
            wsub = W.QLabel("Movelo para despertarlo. Tiene que estar en 2.4 GHz o con el cable puesto.\n"
                            "La app lo detecta sola, no hace falta tocar nada.")
            wsub.setObjectName("sub"); wsub.setAlignment(C.Qt.AlignmentFlag.AlignCenter); wl.addWidget(wsub); wl.addStretch()
            bodyw = W.QWidget(); body = W.QHBoxLayout(bodyw); body.setSpacing(0); body.setContentsMargins(0, 0, 0, 0)
            self.outer.addWidget(wait); self.outer.addWidget(bodyw)
            self.nav = W.QListWidget(); self.nav.setFixedWidth(190)
            self.pages = W.QStackedWidget()
            body.addWidget(self.nav); body.addWidget(self.pages, 1)
            for name, page in (("🖱  Botones", self.page_buttons()), ("🎯  DPI", self.page_dpi()),
                               ("💡  Luz de la rueda", self.page_light()), ("⚡  Rendimiento", self.page_perf()),
                               ("🗂  Copias", self.page_backup())):
                self.nav.addItem(name); self.pages.addWidget(page)
            self.nav.currentRowChanged.connect(self.pages.setCurrentIndex); self.nav.setCurrentRow(0)

            # barra inferior
            foot = W.QFrame(); foot.setObjectName("foot")
            fl = W.QHBoxLayout(foot); fl.setContentsMargins(18, 10, 18, 10)
            self.pending = W.QLabel(""); self.pending.setObjectName("pending"); self.pending.setWordWrap(True)
            self.revert_btn = W.QPushButton("Descartar"); self.revert_btn.clicked.connect(self.show_state)
            self.apply_btn = W.QPushButton("Aplicar al mouse"); self.apply_btn.setObjectName("apply")
            self.apply_btn.clicked.connect(self.apply)
            fl.addWidget(self.pending, 1); fl.addWidget(self.revert_btn); fl.addWidget(self.apply_btn)
            root.addWidget(foot)

            # monitoreo automático (conexión, cable, batería): cada 5 s y solo con la ventana visible
            self.timer = C.QTimer(self); self.timer.setInterval(5000); self.timer.timeout.connect(self.tick)
            # nivel de DPI activo: cada 1 s (lo cambia el botón del mouse); una sola consulta corta
            self.ltimer = C.QTimer(self); self.ltimer.setInterval(1000); self.ltimer.timeout.connect(self.poll_level)
            self.resize(1080, 720)
            C.QTimer.singleShot(30, self.tick)

        # ---------- páginas
        def page_title(self, v, title, sub):
            t = W.QLabel(title); t.setObjectName("title"); v.addWidget(t)
            if sub: s = W.QLabel(sub); s.setObjectName("sub"); s.setWordWrap(True); v.addWidget(s)
            v.addSpacing(8)

        def page_buttons(self):
            w = W.QWidget(); v = W.QVBoxLayout(w); v.setContentsMargins(24, 18, 24, 12)
            self.page_title(v, "Botones", "Hacé clic en un botón para elegir qué hace. El selector BT / OFF / 2.4 GHz "
                                          "y el botón de emparejar de abajo son de hardware.")
            self.canvas = MouseCanvas(); self.canvas.clicked.connect(self.choose_func)
            v.addWidget(self.canvas, 1)
            return w

        def page_dpi(self):
            w = W.QWidget(); v = W.QVBoxLayout(w); v.setContentsMargins(24, 18, 24, 12); v.setSpacing(10)
            self.page_title(v, "DPI", "El botón DPI recorre los niveles en orden; la rueda se prende con el color "
                                      "de cada nivel. Tocá «Usar ahora» para elegir el nivel activo.")
            self.ladder = DpiLadder(); v.addWidget(self.ladder)
            h = W.QHBoxLayout(); h.addWidget(W.QLabel("Niveles:"))
            self.lvl_minus = W.QPushButton("−"); self.lvl_plus = W.QPushButton("+")
            self.lvl_count = W.QLabel(); self.lvl_count.setStyleSheet("font-weight:bold; min-width: 18px; qproperty-alignment: AlignCenter;")
            for b in (self.lvl_minus, self.lvl_plus): b.setFixedWidth(36)
            self.lvl_minus.clicked.connect(lambda: self.set_levels(self.nlevels - 1))
            self.lvl_plus.clicked.connect(lambda: self.set_levels(self.nlevels + 1))
            h.addWidget(self.lvl_minus); h.addWidget(self.lvl_count); h.addWidget(self.lvl_plus); h.addStretch()
            v.addLayout(h)
            self.level_group = W.QButtonGroup(self); self.rows = []; self.nlevels = 1
            for i in range(8):
                c = card(); g = W.QHBoxLayout(c); g.setContentsMargins(12, 8, 14, 8); g.setSpacing(12)
                sw = W.QPushButton(); sw.setFixedSize(30, 30); sw.setToolTip("Color de la rueda en este nivel")
                sw.setCursor(C.Qt.CursorShape.PointingHandCursor)
                sw.clicked.connect(lambda _, i=i: self.pick_color(i))
                name = W.QLabel(f"Nivel {i+1}"); name.setFixedWidth(62); name.setStyleSheet("font-weight:bold")
                sp = W.QSpinBox(); sp.setRange(50, 26000); sp.setSingleStep(50); sp.setKeyboardTracking(False)
                sp.setFixedSize(108, 40); sp.setAlignment(C.Qt.AlignmentFlag.AlignRight | C.Qt.AlignmentFlag.AlignVCenter)
                sp.setStyleSheet("QSpinBox{font-size:15pt; font-weight:bold; padding:0 8px;}"
                                 "QSpinBox::up-button, QSpinBox::down-button{width:0; border:none;}")
                unit = W.QLabel("DPI"); unit.setObjectName("sub")
                sl = W.QSlider(C.Qt.Orientation.Horizontal); sl.setRange(0, 1000)
                sl.valueChanged.connect(lambda val, sp=sp: sp.setValue(slider_to_dpi(val)))
                sp.valueChanged.connect(lambda val, sl=sl: (sl.blockSignals(True), sl.setValue(dpi_to_slider(val)), sl.blockSignals(False)))
                sp.valueChanged.connect(self.edited)
                presets = W.QHBoxLayout(); presets.setSpacing(4)
                for d in (400, 800, 1600, 3200):
                    pb = W.QPushButton(str(d)); pb.setObjectName("chip"); pb.clicked.connect(lambda _, sp=sp, d=d: sp.setValue(d))
                    presets.addWidget(pb)
                use = W.QPushButton("Usar ahora"); use.setCheckable(True); use.setFixedWidth(104)
                self.level_group.addButton(use, i)
                g.addWidget(sw); g.addWidget(name); g.addWidget(sp); g.addWidget(unit); g.addWidget(sl, 1)
                g.addLayout(presets); g.addWidget(use)
                v.addWidget(c); self.rows.append((c, use, sw, sp))
            v.addStretch()
            self.level_group.idClicked.connect(self.edited)
            sc = W.QScrollArea(); sc.setWidget(w); sc.setWidgetResizable(True); return sc

        def set_levels(self, n, edit=True):
            self.nlevels = max(1, min(8, n)); self.lvl_count.setText(str(self.nlevels))
            self.lvl_minus.setEnabled(self.nlevels > 1); self.lvl_plus.setEnabled(self.nlevels < 8)
            for i, (c, use, sw, sp) in enumerate(self.rows): c.setVisible(i < self.nlevels)
            if self.level_group.checkedId() >= self.nlevels: self.level_group.button(self.nlevels - 1).setChecked(True)
            if edit: self.edited()

        def page_light(self):
            w = W.QWidget(); v = W.QVBoxLayout(w); v.setContentsMargins(24, 18, 24, 12)
            self.page_title(v, "Luz de la rueda", "Vista previa con el color del nivel de DPI activo (los colores se eligen en la pestaña DPI).")
            h = W.QHBoxLayout(); self.wheel = WheelPreview(); h.addWidget(self.wheel)
            c = card(); f = W.QFormLayout(c); f.setContentsMargins(18, 16, 18, 16); f.setVerticalSpacing(14)
            self.led_on = W.QCheckBox("  Luz encendida"); f.addRow(self.led_on)
            self.ledA = W.QSlider(C.Qt.Orientation.Horizontal); self.ledA.setRange(1, 10)
            self.ledAv = W.QLabel(); self.ledA.valueChanged.connect(lambda x: self.ledAv.setText(str(x)))
            ha = W.QHBoxLayout(); ha.addWidget(self.ledA); ha.addWidget(self.ledAv)
            f.addRow("Brillo (1-10):", ha)
            f.addRow(help_label("Más brillo = la rueda se ve mejor, pero gasta más batería. "
                                "Apagarla del todo es lo que más batería ahorra."))
            h.addWidget(c, 1); v.addLayout(h); v.addStretch()
            self.led_on.toggled.connect(self.edited); self.ledA.valueChanged.connect(self.edited)
            return w

        def adv_row(self, v, title, key, widget):
            c = card(); g = W.QGridLayout(c); g.setContentsMargins(16, 12, 16, 12)
            t = W.QLabel(title); t.setStyleSheet("font-weight:bold; font-size: 11pt")
            g.addWidget(t, 0, 0); g.addWidget(widget, 0, 1, C.Qt.AlignmentFlag.AlignRight)
            g.addWidget(help_label(ADV_HELP[key]), 1, 0, 1, 2); g.setColumnStretch(0, 1)
            v.addWidget(c)

        def page_perf(self):
            w = W.QWidget(); v = W.QVBoxLayout(w); v.setContentsMargins(24, 18, 24, 12); v.setSpacing(10)
            self.page_title(v, "Rendimiento", "Todo queda guardado dentro del mouse: sirve en cualquier PC.")
            rw = W.QWidget(); rw.setObjectName("row"); rh = W.QHBoxLayout(rw); rh.setContentsMargins(0, 0, 0, 0)
            self.rate_group = W.QButtonGroup(self)
            for code, hz in reversed(RATES):
                b = W.QPushButton(f"{hz} Hz"); b.setCheckable(True); b.setMinimumWidth(80)
                self.rate_group.addButton(b, code); rh.addWidget(b)
            self.rate_group.idClicked.connect(self.edited)
            self.adv_row(v, "Polling rate", "rate", rw)
            self.lod = W.QComboBox(); self.lod.addItem("1 mm", 1); self.lod.addItem("2 mm", 2)
            self.lod.currentIndexChanged.connect(self.edited)
            self.adv_row(v, "LOD (altura de despegue)", "lod", self.lod)
            self.debounce = W.QSpinBox(); self.debounce.setRange(0, 30); self.debounce.setSuffix(" ms")
            self.debounce.valueChanged.connect(self.edited)
            self.adv_row(v, "Debounce", "debounce", self.debounce)
            self.sleep = W.QComboBox()
            for s in (1, 3, 6, 12, 18, 30, 60, 90, 180):
                self.sleep.addItem(f"{s*10} s" if s < 6 else f"{s*10//60} min", s)
            self.sleep.currentIndexChanged.connect(self.edited)
            self.adv_row(v, "Dormir tras", "sleep", self.sleep)
            self.angle, self.ripple = (W.QCheckBox() for _ in range(2))
            for chk, title, key in ((self.angle, "Angle snapping", "angle"),
                                    (self.ripple, "Ripple control", "ripple")):   # "apagar luz al mover": no funciona en este modelo
                chk.toggled.connect(self.edited); self.adv_row(v, title, key, chk)
            v.addStretch()
            sc = W.QScrollArea(); sc.setWidget(w); sc.setWidgetResizable(True); return sc

        def page_backup(self):
            w = W.QWidget(); v = W.QVBoxLayout(w); v.setContentsMargins(24, 18, 24, 12)
            self.page_title(v, "Copias de seguridad",
                            "Cada vez que abrís la app, y antes de cada cambio, se guarda una copia de toda la "
                            f"configuración del mouse en:\n{BACKUP_DIR}")
            for text, fn in (("Guardar copia ahora", self.backup_now), ("Restaurar una copia…", self.restore),
                             ("Abrir carpeta de copias", lambda: G.QDesktopServices.openUrl(C.QUrl.fromLocalFile(BACKUP_DIR)))):
                b = W.QPushButton(text); b.clicked.connect(fn); b.setMaximumWidth(280); v.addWidget(b)
            v.addStretch(); return w

        # ---------- lógica
        def set_busy(self, on):
            self.setEnabled(not on)
            W.QApplication.setOverrideCursor(C.Qt.CursorShape.WaitCursor) if on else W.QApplication.restoreOverrideCursor()
            W.QApplication.processEvents()

        def reload(self):
            """Relee toda la configuración del mouse (al conectar, tras aplicar/restaurar)."""
            self.mouse.close(); self.cur = None; self.tick()

        def tick(self):
            """Automático: detecta conexión/cable, carga la configuración la primera vez y lee la batería."""
            wired, wireless = find_nodes()
            try:
                if self.mouse.fd is None or bool(wired) != self.mouse.cable or not os.path.exists(self.mouse.node or ""):
                    self.mouse.open()
                if self.cur is None:
                    self.set_busy(True)
                    try:
                        self.mem = self.mouse.dump(); self.cur = decode(self.mem)
                        if not hasattr(self, "_backed"):
                            save_backup(self.mem); self._backed = True
                        self.pages.setEnabled(True); self.outer.setCurrentIndex(1); self.show_state()
                    finally:
                        self.set_busy(False)
                pct, chg, full = self.mouse.battery()
                self.set_status(True, "Conectado por " + ("cable" if self.mouse.cable else "receptor 2.4 GHz"))
                if chg and not full:
                    self.batico.setPixmap(pix("power_charging.png")); self.bat.setText("Cargando")
                else:
                    self.batico.setPixmap(pix(f"power{min(4, max(1, (pct + 24) // 25))}.png"))
                    self.bat.setText(f"{pct} %")
            except MouseError as e:
                self.mouse.close()
                asleep = bool(wired or wireless)
                self.set_status(False, "Mouse dormido o en Bluetooth: movelo o pasalo a 2.4 GHz" if asleep
                                else "No se encuentra el receptor ni el cable")
                self.batico.clear(); self.bat.setText("")
                if self.cur is None:
                    self.outer.setCurrentIndex(0); self.wait_text.setText(self.status.text())
                    self.apply_btn.setEnabled(False); self.revert_btn.setEnabled(False)
            if self.isVisible() and not self.isMinimized() and not self.timer.isActive():
                self.timer.start()

        def poll_level(self):
            if self.cur is None or self.mouse.fd is None or not self.isEnabled():
                return
            try:
                r = self.mouse.read(0x04, 2)
            except MouseError:
                return                       # dormido: de eso se ocupa tick()
            lvl = r[0]
            if r[0] + r[1] != 0x55 or lvl == self.cur["level"] or lvl > 7:
                return
            ui_level = self.level_group.checkedId()
            pending = ui_level != self.cur["level"]       # el usuario eligió otro nivel y no aplicó
            self.cur["level"] = lvl; self.mem = self.mem[:4] + bytes(r) + self.mem[6:]
            if not pending:
                b = self.level_group.button(lvl); b and b.setChecked(True)
            self.edited()

        def set_status(self, ok, text):
            self.status.setText(text)
            self.dot.setStyleSheet(f"color:{'#3fb950' if ok else '#d29922'}; font-size: 12pt")

        def showEvent(self, e):
            self.timer.start(); self.ltimer.start()

        def hideEvent(self, e):
            self.timer.stop(); self.ltimer.stop()

        def changeEvent(self, e):
            if e.type() == C.QEvent.Type.WindowStateChange:
                if self.isMinimized():
                    self.timer.stop(); self.ltimer.stop()
                else:
                    self.timer.start(); self.ltimer.start(); self.tick()

        def show_state(self):
            if not self.cur: return
            s = self.cur; self.loading = True
            self.btn_codes = list(s["buttons"])
            b = self.rate_group.button(s["rate"]); b and b.setChecked(True)
            for i, (c, use, sw, sp) in enumerate(self.rows):
                sp.setValue(s["dpi"][i]); self.colors[i] = s["color"][i]; self.paint(i)
            bt = self.level_group.button(min(s["level"], 7)); bt and bt.setChecked(True)
            self.set_levels(s["levels"], edit=False)
            self.led_on.setChecked(s["ledmode"] != 0)
            self.ledA.setValue(LED_TABLE.index(s["ledA"]) + 1 if s["ledA"] in LED_TABLE else 10)
            self.ledAv.setText(str(self.ledA.value()))
            if self.lod.findData(s["lod"]) < 0: self.lod.addItem(f"{s['lod']}", s["lod"])
            self.lod.setCurrentIndex(self.lod.findData(s["lod"]))
            self.debounce.setValue(s["debounce"])
            if self.sleep.findData(s["sleep"]) < 0: self.sleep.addItem(f"{s['sleep']*10} s", s["sleep"])
            self.sleep.setCurrentIndex(self.sleep.findData(s["sleep"]))
            self.angle.setChecked(bool(s["angle"]))
            self.ripple.setChecked(bool(s["ripple"]))
            self.loading = False; self.edited()

        def paint(self, i):
            r, g, b = self.colors[i]
            self.rows[i][2].setStyleSheet(f"background: rgb({r},{g},{b}); border: 2px solid #1d1f21; border-radius: 15px;")

        def pick_color(self, i):
            c = W.QColorDialog.getColor(G.QColor(*self.colors[i]), self, f"Color de la rueda en el nivel {i+1}")
            if c.isValid():
                self.colors[i] = (c.red(), c.green(), c.blue()); self.paint(i); self.edited()

        def choose_func(self, idx):
            m = W.QMenu(self)
            for lab, code in FUNCS:
                a = m.addAction(lab); a.setCheckable(True); a.setChecked(tuple(code) == tuple(self.btn_codes[idx]))
                a.triggered.connect(lambda _, code=code: (self.btn_codes.__setitem__(idx, code), self.edited()))
            m.exec(G.QCursor.pos())

        def wanted(self):
            s = copy.deepcopy(self.cur)
            s["rate"] = self.rate_group.checkedId()
            s["levels"] = self.nlevels; s["level"] = max(0, self.level_group.checkedId())
            for i, (c, use, sw, sp) in enumerate(self.rows):
                s["dpi"][i] = sp.value() // 50 * 50; s["color"][i] = tuple(self.colors[i])
            s["ledmode"] = (self.cur["ledmode"] or 1) if self.led_on.isChecked() else 0
            if not (self.cur["ledA"] not in LED_TABLE and self.ledA.value() == 10):
                s["ledA"] = LED_TABLE[self.ledA.value() - 1]
            # ledB (byte 0x50): no hace nada visible en este modelo, se deja como está
            s["buttons"] = [tuple(b) for b in self.btn_codes]
            s["lod"] = self.lod.currentData(); s["debounce"] = self.debounce.value()
            s["sleep"] = self.sleep.currentData()   # motion sync: tu modelo no lo usa, no se toca
            s["angle"] = int(self.angle.isChecked()); s["ripple"] = int(self.ripple.isChecked())
            return s

        def edited(self, *_):
            if self.loading or not self.cur: return
            new = self.wanted(); ch = changes(self.cur, new)
            for idx, x, y, side in HOTSPOTS:
                self.canvas.set_text(idx, BUTTONS[idx][0], func_name(new["buttons"][idx]),
                                     tuple(new["buttons"][idx]) != tuple(self.cur["buttons"][idx]))
            for i, (c, use, sw, sp) in enumerate(self.rows):
                act = i == new["level"]; use.setText("✓ Activo" if act else "Usar ahora")
                c.setProperty("active", act); c.style().unpolish(c); c.style().polish(c)
            self.ladder.set([(new["dpi"][i], new["color"][i]) for i in range(new["levels"])], new["level"])
            self.wheel.set(new["color"][new["level"]], self.ledA.value(), self.led_on.isChecked())
            self.pending.setText(("●  " + ", ".join(x[2] for x in ch)) if ch else "")
            self.apply_btn.setEnabled(bool(ch)); self.revert_btn.setEnabled(bool(ch))
            self.canvas.update()

        def apply(self):
            new = self.wanted(); ch = changes(self.cur, new)
            if not ch: return
            if (0x01, 0x01, 0x00) not in [tuple(b) for b in new["buttons"]]:
                W.QMessageBox.warning(self, "No se aplicó", "Ningún botón quedaría como clic izquierdo."); return
            self.set_busy(True)
            try:
                save_backup(self.mem, "antes_de_aplicar")
                for addr, data, _ in ch:
                    self.mouse.write(addr, data)
                self.mem = self.mouse.dump(); self.cur = decode(self.mem)
                bad = changes(self.cur, new)
                self.set_busy(False)
                if bad:
                    W.QMessageBox.warning(self, "Revisar", "El mouse aceptó, pero al releer no coincide: " + ", ".join(b[2] for b in bad))
                self.show_state()
                self.pending.setText("✓  Aplicado: " + ", ".join(c[2] for c in ch))
            except MouseError as e:
                self.set_busy(False); W.QMessageBox.critical(self, "Error", str(e)); self.reload()

        def backup_now(self):
            if self.mem is None: return
            fn = save_backup(self.mouse.dump(), "manual"); self.pending.setText(f"✓  Copia guardada: {os.path.basename(fn)}")

        def restore(self):
            fn, _ = W.QFileDialog.getOpenFileName(self, "Elegí una copia", BACKUP_DIR, "Copias (*.bin)")
            if not fn: return
            data = open(fn, "rb").read()
            if len(data) != MEM_SIZE:
                W.QMessageBox.warning(self, "Copia inválida", "El archivo no tiene el tamaño esperado."); return
            if W.QMessageBox.question(self, "Restaurar", f"¿Escribir en el mouse la configuración de\n{os.path.basename(fn)}?") \
                    != W.QMessageBox.StandardButton.Yes:
                return
            self.set_busy(True)
            try:
                save_backup(self.mem, "antes_de_restaurar")
                for a in range(0, MEM_SIZE, 10):
                    if data[a:a + 10] != self.mem[a:a + 10]:
                        self.mouse.write(a, data[a:a + 10])
                self.set_busy(False); self.reload(); self.pending.setText("✓  Copia restaurada")
            except MouseError as e:
                self.set_busy(False); W.QMessageBox.critical(self, "Error", str(e)); self.reload()

    w = Win(); w.show()
    sys.exit(app.exec())


def selftest():
    m = Mouse(); m.open()
    mem = m.dump(); s = decode(mem)
    print("nodo", m.node, "cable", m.cable, "batería", m.battery())
    for k, v in s.items(): print(f"{k:9} {v}")
    # comprobar que codificar lo leído da los mismos bytes
    for i in range(8):
        assert dpi_encode(s["dpi"][i]) == mem[0x0C + 4 * i:0x10 + 4 * i], i
        assert block(*s["color"][i]) == mem[0x2C + 4 * i:0x30 + 4 * i], i
    for i, (_, a) in enumerate(BUTTONS):
        assert block(*s["buttons"][i]) == mem[a:a + 4], a
    assert changes(s, s) == []
    print("codificación OK: releer y recodificar da exactamente los mismos bytes")


if __name__ == "__main__":
    selftest() if "--selftest" in sys.argv else gui()
