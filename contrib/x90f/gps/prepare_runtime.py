#!/usr/bin/env python3
"""Extract the stock BCM4752 daemon and its bionic dependency closure.

Input is the decoded ext4 system image, not the Android sparse image or ZIP.
The proprietary files remain outside git; their original bytes are not patched.
Example (macOS):
  python3 prepare_runtime.py /tmp/yb-rom/system.ext4 /tmp/android-gps-root \
    --debugfs /opt/homebrew/opt/e2fsprogs/sbin/debugfs
Copy the resulting directory to Debian, then use run_gps.py as root.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

DAEMON_SHA256 = "d135fc515dd3802dcd9fe807b942e1e112767f56b5a44463c64121317753c715"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    parser.add_argument("runtime", type=Path)
    parser.add_argument("--debugfs", default="debugfs")
    parser.add_argument("--objdump", default="objdump")
    args = parser.parse_args()
    image = args.image.resolve(strict=True)
    runtime = args.runtime.resolve()
    if any(c in str(runtime) for c in ('"', '\n')):
        parser.error("runtime path cannot contain a quote or newline")
    manifest = {}

    def extract(source, destination):
        target = runtime / destination
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            raise FileExistsError(f"Refusing to overwrite {target}; use a new runtime directory")
        subprocess.run([args.debugfs, "-R", f'dump {source} "{target}"', str(image)], check=True)
        if not target.is_file():
            raise RuntimeError(f"debugfs did not extract {source}")
        manifest[destination] = {
            "source": source,
            "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        }
        return target

    daemon = extract("/vendor/bin/gpsd", "system/bin/glgps_intelx86android")
    if manifest["system/bin/glgps_intelx86android"]["sha256"] != DAEMON_SHA256:
        raise RuntimeError("Daemon does not match the investigated Lenovo stock ROM")
    linker = extract("/bin/linker64", "system/bin/linker64")
    daemon.chmod(0o755)
    linker.chmod(0o755)
    pending = [daemon]
    libraries = set()
    while pending:
        binary = pending.pop()
        headers = subprocess.check_output([args.objdump, "-p", str(binary)], text=True)
        for library in re.findall(r"NEEDED\s+(\S+)", headers):
            if library in libraries:
                continue
            if "/" in library:
                raise RuntimeError(f"Unexpected dependency path: {library}")
            libraries.add(library)
            pending.append(extract("/lib64/" + library, "system/lib64/" + library))

    stock_config = extract("/vendor/etc/gps.xml", "vendor/etc/gps-stock.xml")
    props = extract("/build.prop", "system/build.prop")
    extract("/usr/share/zoneinfo/tzdata", "system/usr/share/zoneinfo/tzdata")
    properties = dict(line.split("=", 1) for line in props.read_text().splitlines()
                      if line and not line.startswith("#") and "=" in line)
    config = stock_config.read_bytes().rstrip(b"\x00").decode("utf-8")
    replacements = {
        'PortName="/dev/gps/ttyGPS"': 'PortName="/dev/ttyS2"',
        'FrqPlan="FROM_PROPERTY"': f'FrqPlan="{properties["ro.spid.gps.FrqPlan"]}"',
        'RfType="FROM_PROPERTY"': f'RfType="{properties["ro.spid.gps.RfType"]}"',
        'SuplEnable="true"': 'SuplEnable="false"',
        'HttpSyncLto="true"': 'HttpSyncLto="false"',
    }
    for before, after in replacements.items():
        if config.count(before) != 1:
            raise RuntimeError(f"Stock config does not contain exactly one {before}")
        config = config.replace(before, after)
    (runtime / "vendor/etc/gps-debian.xml").write_text(config)
    for directory in ("data/gps", "dev", "proc"):
        (runtime / directory).mkdir(parents=True, exist_ok=True)
    (runtime / "stock-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Extracted original daemon, linker and {len(libraries)} libraries to {runtime}")
    print("Board frequency/RF settings copied from the stock build.prop; assistance network disabled.")


if __name__ == "__main__":
    main()
