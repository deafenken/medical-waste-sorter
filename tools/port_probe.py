"""Diagnose what's on the other end of a serial port.

Tries G-code (GRBL/Marlin), reports baud rate, captures the boot banner,
and runs a minimal G28 + G1 + status query so you know whether your arm
speaks the same dialect as the main pipeline.

    python tools/port_probe.py --port /dev/ttyUSB0
    python tools/port_probe.py --port COM5 --baud 250000
"""
from __future__ import annotations

import argparse
import sys
import time

import serial


def probe(port: str, baud: int, timeout: float = 2.0) -> None:
    print(f"[probe] opening {port} @ {baud} ...")
    try:
        ser = serial.Serial(port, baud, timeout=timeout)
    except Exception as exc:
        print(f"[probe] FAILED to open: {exc}")
        sys.exit(1)

    time.sleep(2.0)  # wait for board reset
    print("[probe] reading boot banner...")
    deadline = time.time() + 2.0
    while time.time() < deadline:
        line = ser.readline().decode(errors="replace").strip()
        if line:
            print(f"[banner] {line!r}")

    cmds = ["?", "$$", "M115", "G28", "G1 X0 Y150 Z80 F1500", "M114"]
    for cmd in cmds:
        print(f"\n[probe] sending: {cmd}")
        ser.write((cmd + "\r\n").encode())
        time.sleep(0.5)
        deadline = time.time() + 3.0
        while time.time() < deadline:
            line = ser.readline().decode(errors="replace").strip()
            if not line:
                break
            print(f"  <- {line!r}")

    print("\n[probe] done. close port.")
    ser.close()


def main():
    parser = argparse.ArgumentParser(description="Serial / G-code probe")
    parser.add_argument("--port", required=True, help="e.g. /dev/ttyUSB0 or COM5")
    parser.add_argument("--baud", type=int, default=115200)
    args = parser.parse_args()
    probe(args.port, args.baud)


if __name__ == "__main__":
    main()
