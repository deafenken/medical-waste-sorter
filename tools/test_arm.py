"""Manual jog tool. Reads config.yaml for port + protocol settings, then
exposes a tiny REPL to send commands to whichever arm backend is configured.
Works for both G-code and Panthera-HT.

    python tools/test_arm.py
    > home
    > move 0 180 80
    > grip close
    > grip open
    > stop
    > raw G1 X20 Y180 Z40 F2000   # G-code only
    > quit
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

# Allow `python tools/test_arm.py` from repo root
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import arms as arms_mod  # noqa: E402
from src import config as config_mod  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")


def repl(arm, cfg) -> None:
    print("Commands: home | move X Y Z | grip open | grip close | stop | raw <cmd> | quit")
    while True:
        try:
            line = input("arm> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not line:
            continue
        parts = line.split()
        c = parts[0].lower()
        try:
            if c in ("quit", "exit"):
                return
            elif c == "home":
                arm.home()
            elif c == "move" and len(parts) == 4:
                arm.move(float(parts[1]), float(parts[2]), float(parts[3]))
            elif c == "grip" and len(parts) == 2:
                gripper_open_cmd = getattr(cfg.arm, "gripper_open_cmd", None)
                gripper_close_cmd = getattr(cfg.arm, "gripper_close_cmd", None)
                if parts[1] == "open":
                    arm.gripper_open(gripper_open_cmd)
                elif parts[1] == "close":
                    arm.gripper_close(gripper_close_cmd)
                else:
                    print("usage: grip open|close")
            elif c == "stop":
                arm.stop()
            elif c == "raw" and len(parts) >= 2:
                arm.send(line[4:])
            else:
                print("unknown command")
        except Exception as exc:
            print(f"ERROR: {exc}")


def main() -> None:
    cfg = config_mod.load_config()
    with arms_mod.open_arm(cfg.arm) as arm:
        repl(arm, cfg)


if __name__ == "__main__":
    main()
