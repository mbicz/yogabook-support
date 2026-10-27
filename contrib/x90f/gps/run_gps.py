#!/usr/bin/env python3
"""Run the original BCM4752 initialization/acquisition in a private mount namespace.

sudo python3 run_gps.py ~/src/android-gps-root --seconds 120 \
  --output /tmp/gps.nmea --trace /tmp/gps.strace
A second process can consume the real decoded NMEA with: tail -f /tmp/gps.nmea
The daemon retains its embedded ASIC patch/GLME implementation and CRTSCTS setup.
No Android-kernel API is emulated. The stock clock code falls back to Linux
CLOCK_BOOTTIME when its legacy /dev/alarm probe fails; failures remain reported.
The original daemon exit status is preserved, including shutdown failures.
"""

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import select
import signal
import stat
import subprocess
import sys
import termios
import time

DAEMON_SHA256 = "d135fc515dd3802dcd9fe807b942e1e112767f56b5a44463c64121317753c715"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runtime", type=Path)
    parser.add_argument("--seconds", type=float, default=120)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--trace", type=Path)
    parser.add_argument("--inside", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if sys.platform != "linux" or os.geteuid() != 0:
        parser.error("run on the Debian Yoga Book as root")
    if args.seconds <= 0:
        parser.error("--seconds must be positive")
    runtime = args.runtime.resolve(strict=True)
    output = args.output.resolve()
    trace = args.trace.resolve() if args.trace else None
    if output.is_relative_to(runtime / "dev") or output.is_relative_to(runtime / "proc"):
        parser.error("output must not be inside a temporary mount")
    if trace and (trace.is_relative_to(runtime / "dev") or trace.is_relative_to(runtime / "proc")):
        parser.error("trace must not be inside a temporary mount")
    if not args.inside:
        command = ["unshare", "--mount", "--propagation", "private", sys.executable,
                   str(Path(__file__).resolve()), str(runtime), "--seconds", str(args.seconds),
                   "--output", str(output), "--inside"]
        if trace:
            command += ["--trace", str(trace)]
        os.execvp(command[0], command)

    daemon = runtime / "system/bin/glgps_intelx86android"
    if hashlib.sha256(daemon.read_bytes()).hexdigest() != DAEMON_SHA256:
        raise RuntimeError("Daemon differs from the investigated original ROM binary")
    gps_entries = [p for p in Path("/sys/class/rfkill").glob("rfkill*")
                   if (p / "type").read_text().strip() == "gps"]
    if len(gps_entries) != 1 or (gps_entries[0] / "name").read_text().strip() != "BCM4752:00":
        raise RuntimeError("Expected exactly one GPS rfkill owned by BCM4752:00")
    state = gps_entries[0] / "state"
    power = Path("/sys/class/tty/ttyS2/device/power/control")
    consumers = subprocess.run(["fuser", "/dev/ttyS2"], capture_output=True, text=True)
    if consumers.returncode == 0:
        raise RuntimeError(f"GPS UART is already in use: {consumers.stdout} {consumers.stderr}")
    if consumers.returncode != 1:
        raise RuntimeError(f"Cannot inspect UART ownership: {consumers.stderr}")

    with open("/run/lock/yogabook-gps.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        old_state, old_power = state.read_text(), power.read_text()
        tty = os.open("/dev/ttyS2", os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        old_termios = termios.tcgetattr(tty)
        os.close(tty)
        process = None
        fifo_fd = None
        stopped = False
        counts = {"bytes": 0, "sentences": 0, "valid_checksums": 0, "fix_sentences": 0}
        pending = b""
        alarm_missing = not Path("/dev/alarm").exists()
        if alarm_missing:
            print("WARNING: Debian lacks legacy Android /dev/alarm. The stock clock code "
                  "falls back to genuine Linux CLOCK_BOOTTIME after ENOENT/EBADF; "
                  "repeated failed probes add overhead and remain visible in the trace.", file=sys.stderr)

        def request_stop(signum, frame):
            nonlocal stopped
            stopped = True

        signal.signal(signal.SIGINT, request_stop)
        signal.signal(signal.SIGTERM, request_stop)
        try:
            power.write_text("on")
            state.write_text("0")
            time.sleep(1)
            subprocess.run(["mount", "-t", "tmpfs", "-o", "size=64k,nosuid", "tmpfs", str(runtime / "dev")], check=True)
            for name in ("null", "zero", "random", "urandom", "ttyS2", "rfkill"):
                source = Path("/dev") / name
                info = source.stat()
                if not stat.S_ISCHR(info.st_mode):
                    raise RuntimeError(f"Not a character device: {source}")
                os.mknod(runtime / "dev" / name, stat.S_IFCHR | 0o600, info.st_rdev)
            (runtime / "dev/fd").symlink_to("/proc/self/fd")
            for name, number in (("stdin", 0), ("stdout", 1), ("stderr", 2)):
                (runtime / "dev" / name).symlink_to(f"/proc/self/fd/{number}")
            subprocess.run(["mount", "-t", "proc", "proc", str(runtime / "proc")], check=True)
            fifo = runtime / "data/gps/nmeapipe"
            if not fifo.exists():
                os.mkfifo(fifo, 0o600)
            if not stat.S_ISFIFO(fifo.stat().st_mode):
                raise RuntimeError(f"Expected NMEA FIFO: {fifo}")
            fifo_fd = os.open(fifo, os.O_RDWR | os.O_NONBLOCK)
            command = ["chroot", str(runtime), "/system/bin/glgps_intelx86android",
                       "/vendor/etc/gps-debian.xml", "Periodic"]
            if trace:
                command = ["strace", "-f", "-tt", "-yy", "-s", "32768", "-xx",
                           "-e", "trace=openat,read,write,writev,ioctl,close", "-o", str(trace)] + command
            env = {**os.environ, "ANDROID_ROOT": "/system", "ANDROID_DATA": "/data"}
            process = subprocess.Popen(command, env=env, start_new_session=True)
            deadline = time.monotonic() + args.seconds
            with output.open("wb") as capture:
                while not stopped and process.poll() is None and time.monotonic() < deadline:
                    if not select.select([fifo_fd], [], [], 0.2)[0]:
                        continue
                    chunk = os.read(fifo_fd, 65536)
                    capture.write(chunk)
                    capture.flush()
                    counts["bytes"] += len(chunk)
                    pending += chunk
                    while b"\n" in pending:
                        line, pending = pending.split(b"\n", 1)
                        line = line.strip()
                        counts["sentences"] += 1
                        if not line.startswith(b"$") or b"*" not in line:
                            continue
                        body, checksum = line[1:].rsplit(b"*", 1)
                        value = 0
                        for byte in body:
                            value ^= byte
                        if checksum.upper() != f"{value:02X}".encode():
                            continue
                        counts["valid_checksums"] += 1
                        fields = body.split(b",")
                        if ((fields[0].endswith(b"GGA") and len(fields) > 6 and fields[6] not in (b"", b"0"))
                                or (fields[0].endswith(b"RMC") and len(fields) > 2 and fields[2] == b"A")):
                            counts["fix_sentences"] += 1
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
            result = {**counts, "daemon_exit": process.returncode, "android_alarm_missing": alarm_missing,
                      "nmea_output": str(output), "trace": str(trace) if trace else None}
            print(json.dumps(result, indent=2))
            if process.returncode:
                return process.returncode if process.returncode > 0 else 128 - process.returncode
            return 0 if counts["fix_sentences"] else 2
        finally:
            try:
                if process is not None and process.poll() is None:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                if fifo_fd is not None:
                    os.close(fifo_fd)
            finally:
                try:
                    fd = os.open("/dev/ttyS2", os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
                    try:
                        termios.tcsetattr(fd, termios.TCSANOW, old_termios)
                    finally:
                        os.close(fd)
                finally:
                    try:
                        state.write_text(old_state)
                    finally:
                        power.write_text(old_power)
            # Mounts belong only to this process's namespace and disappear on exit.


if __name__ == "__main__":
    sys.exit(main())
