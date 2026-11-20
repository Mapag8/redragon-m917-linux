# Redragon M917 ST4R Pro on Linux

Configuration app for the **Redragon M917 ST4R Pro** wireless mouse (2.4 GHz receiver
`25a7:fa7c`, cable `25a7:fa7b`). Redragon only ships Windows software; this talks to the
mouse directly over hidraw.

*[Español más abajo](#español)*

## What it does

PyQt6 app, UI in Spanish:
- Polling rate (125 / 250 / 500 / 1000 Hz)
- DPI levels: number of levels, DPI and colour of each, active level (updates live
  when you press the DPI button)
- Wheel LED brightness
- Button remapping (left, right, wheel, back, forward, DPI)
- Advanced: lift-off distance, debounce, sleep time, angle snapping, ripple control
- Battery level, auto-detects receiver / cable / sleeping mouse

### Safety
- Full backup of the mouse memory on every launch and before every apply/restore,
  kept in `~/.local/share/redragon-m917/copias` (restorable from the app).
- Only changed fields are written, then read back and verified.
- Refuses to apply a layout with no left-click button.
- `redragon-m917 --selftest` is read-only: decodes the config and checks re-encoding.

## Install

Requirements: Python 3 and PyQt6 (`python-pyqt6` on Arch).

```sh
git clone https://github.com/Mapag8/redragon-m917-linux
cd redragon-m917-linux
./install.sh
```

It installs to `~/.local` and adds a udev rule (`/etc/udev/rules.d/70-redragon-m917.rules`)
so your user can access the mouse without root. Remove with `./uninstall.sh`.

The mouse must be in **2.4 GHz mode or on the cable**: in Bluetooth mode the receiver
is not used.

## Notes

- Battery is reported by the mouse in 5 % steps and is voltage based. On the cable it
  reads high, so like the official app it shows "Cargando" instead of a number.
- Only tested on one M917 ST4R Pro. Other Redragon/Compx mice may share the protocol
  but **are not supported**: the app only opens `25a7:fa7b` / `25a7:fa7c`.
- Protocol notes: [docs/PROTOCOL.md](docs/PROTOCOL.md).

Not affiliated with Redragon. Use at your own risk: the app writes to the mouse's
configuration memory (with backups).

License: GPL-3.0-or-later.

---

## Español

App de configuración para el mouse **Redragon M917 ST4R Pro**. Redragon solo tiene programa
para Windows; esto habla con el mouse directo por hidraw.

Polling rate, niveles de DPI (valor y color de cada uno), brillo de la luz de la rueda,
botones, ajustes avanzados (LOD, debounce, tiempo para dormir, angle snapping, ripple) y
batería. Hace una copia de la memoria del mouse cada vez que se abre y antes de aplicar
cambios.

Instalación: `./install.sh` (pide la contraseña una vez para la regla de udev).
Desinstalar: `./uninstall.sh`.

El mouse tiene que estar en modo 2.4 GHz o con cable (en Bluetooth no se usa el receptor).
No tiene relación con Redragon.
