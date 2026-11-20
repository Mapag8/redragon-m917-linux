# Redragon M917 ST4R Pro — HID protocol

Devices: `25a7:fa7c` (2.4 GHz receiver, "Compx 2.4G Wireless Receiver") and
`25a7:fa7b` (mouse on USB cable, "Compx 3-mode mouse"). Bluetooth mode bypasses
the receiver and is not covered.

Documented for interoperability, from static analysis of the official Windows
configuration software and tests on a real mouse. No vendor code is included in
this repository.

Legend: ✅ confirmed in the official software · 🧪 tested on a real mouse · ❓ unconfirmed

## Transport ✅🧪

The command interface is the hidraw node whose report descriptor contains vendor
usage page `0xFF02` with feature report `0x08` (hex `0602ff0902a1018508`).

Request — `SET_FEATURE`, report `0x08`, 17 bytes:

| byte | meaning |
|---|---|
| 0 | `0x08` (report id) |
| 1 | command |
| 2 | `0x00` |
| 3, 4 | address high, low |
| 5 | length (≤ 10) |
| 6–15 | data |
| 16 | checksum = `0x55 - sum(bytes 0..15)` (mod 256) |

Reply — input report `0x09` on the same node: `[1]` = command, `[2]` = status
(`0` = OK), `[6..]` = data. The first replies after waking the mouse can be stale:
check that bytes 3–4 echo the address and retry.

| cmd | function |
|---|---|
| `0x01` | handshake (returns CID/MID) |
| `0x03` | connection status: `[6]` = 1 if the mouse is linked |
| `0x04` | battery: `[6]` = percent (5 % steps), `[7]` = charging |
| `0x07` | **write** memory 🧪 (no separate "save" command) |
| `0x08` | read memory 🧪 |

Most values are stored as a pair `(v, 0x55 - v)`. Multi-byte blocks end with a
control byte = `0x55 - sum(block bytes)`.

## Battery ✅🧪

`cmd 0x04` → `[6]` = %, `[7]` = charging. `charging == 1 && percent == 1` means
**charge complete** (the official software shows 100 %). The percentage is voltage
based: it reads high while the cable is plugged (it tops out at 95 on cable), so the
official software hides the number while charging. The mouse sleeps after the
configured idle time and then stops answering.

## Memory map

| addr | content |
|---|---|
| `0x00` | polling rate ✅🧪: 1 = 1000 Hz, 2 = 500, 4 = 250, 8 = 125 |
| `0x02` | number of DPI levels ✅ (1–8) |
| `0x04` | active DPI level ✅ (0–7) |
| `0x0A` | lift-off distance ✅ |
| `0x0C` | DPI, 8 blocks of 4 bytes ✅: `[x_lo, y_lo, flags, ctrl]` |
| `0x2C` | colour of each DPI level, 8 × `[R, G, B, ctrl]` ✅ |
| `0x4C` | DPI indicator (wheel LED) effect ✅: `[mode, 55-mode, table, 55-table, b, 55-b]` |
| `0x54`/`0x58` | second light zone ✅ format; ❓ unused on this model |
| `0x60` | buttons, 16 × `[type, a, b, ctrl]` ✅ |
| `0xA0` | main light, 7 bytes ✅ (not present on this model) |
| `0xA9` | debounce in ms ✅ |
| `0xAB` | motion sync ✅ |
| `0xAD` | sleep time = value × 10 s ✅ |
| `0xAF` | angle snapping ✅ |
| `0xB1` | ripple control ✅ |
| `0xB3` | light off while moving ✅ (no visible effect on this model 🧪) |
| `0xB5`, `0xB7` | unnamed advanced settings ❓ |
| `0x100–0x2FF` | key combinations ✅ (address only) |
| `0x301+` | macros, 0x180-byte blocks ✅ (address; inner format ❓) |

### DPI encoding

`flags = ((y_hi << 2 | mul) << 4) | (x_hi << 2 | mul)`, `n = hi << 8 | lo`,
`DPI = (n + 1) × 50` (with `mul = 1`: `(n + 1) × 100`). Sensor PAW3395, 50–26000.

### Wheel LED (`0x4C`) 🧪

On this model the wheel LED is the DPI indicator: its colour follows `0x2C`. The
table byte (`0x4E`, values `10 1E 3C 5A 80 96 B4 D2 E6 FF` = level 1–10) is the
**brightness**. The other value (`0x50`) has no visible effect. Mode 0 = off.

### Buttons (`0x60`)

| type | a, b | action |
|---|---|---|
| `01` | mask | mouse button: `01` left, `02` right, `04` middle, `08` back, `10` forward |
| `02` | `01`/`02`/`03` | DPI loop / DPI+ / DPI- ❓ (order of + and -) |
| `04` | modifier, keycode | keyboard key |
| `06` | id | macro |
| `0A` | n | DPI lock |
| `00` | — | disabled |
| `07`–`09` | | fire key / RGB toggle / polling switch ❓ |

Physical buttons on the M917 and their slots: `0x60` left, `0x64` right,
`0x68` middle, `0x6C` back, `0x70` forward, `0x74` DPI. The remaining slots belong to
buttons this model does not have (shared firmware).

### Main light (`0xA0`) — not on the M917

`[mode, R, G, B, speed, brightness, ctrl]`; modes: 2 static, 1 breathing,
0 streaming, 3 neon, 5 single-colour flow, 7 multicolour breathing, 4 off.
