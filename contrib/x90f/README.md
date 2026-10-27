# X90F support sources

These are the remaining support files used while bringing up the Android-edition
Lenovo Yoga Book YB1-X90F. They are published for upstream discussion, separately
from the two-commit modes-handler submission. This directory is not installed by
the Debian package. It is not an installer or a claim that every workaround
should become the default.

The original source files are copied unchanged. Camera userspace and the
camera-only ACPI patcher live in [yogabook-camera](https://github.com/mbicz/yogabook-camera).
The [hardware-check suite](https://github.com/mbicz/yogabook-hardware-check)
separates interface checks, active operation and physical acceptance.

## Pen

- [libwacom descriptor](libwacom/wacom-hid-169-pen.tablet): marks the digitizer
  as display/system-integrated so Mutter maps it to the built-in panel.
- [bind helper](yogabook-fix-wacom-bind), [service](yogabook-fix-wacom.service)
  and [timer](yogabook-fix-wacom.timer): recover the observed lost I2C-HID binding
  at boot or after mode changes. This is a workaround, not a kernel probe fix.

The descriptor belongs in `/usr/share/libwacom/`; the helper and units use the
paths shown in the service. Restart the desktop session after changing the
mapping. Clear an obsolete per-user output override with:

```sh
gsettings reset org.gnome.desktop.peripherals.tablet:/org/gnome/desktop/peripherals/tablets/056a:0169/ output
```

Do not combine this with the retired pen calibration-matrix rule or an explicit
`Rotate=` setting. Pen corners and rotation were physically confirmed on an
earlier LTS boot; publication is not a new pressure/accuracy test.

## Accelerometers and Halo shortcuts

[61-sensor-yogabook-local.rules](61-sensor-yogabook-local.rules) identifies the
display and base accelerometers by physical HID product rather than allocated
`.auto` or IIO instance numbers. It includes the measured base mount matrix.
It belongs in `/etc/udev/rules.d/`; remove obsolete local hwdb overrides rather
than stacking contradictory mappings. Reload rules and restart iio-sensor-proxy
after a deliberate installation. This does not repair ambient-light sensing.

[yogabook-halo-keybindings](yogabook-halo-keybindings) adds GNOME's app-grid and
overview shortcuts for the printed Halo keys, preserving existing bindings.
Run it as the desktop user, not from a root package hook; it needs Python GI
and the GNOME Shell schemas. Keycode mappings themselves are in the separate
[touch-keyboard series](https://github.com/jekhor/chromiumos_touch_keyboard/compare/master...mbicz:jekhor-submission).
The US pc104 layout and optional per-user touchpad tap-to-click setting are
configuration choices, not new keyboard or haptic drivers.

## Thermal ACPI correction

[patch_thermal_tables.py](acpi/patch_thermal_tables.py) repairs the known `_TMP`
methods that returned 0 K or a dummy temperature because they were gated on a
missing virtual GPIO provider. It requires the native Whiskey Cove thermal ADC
implementation in the [deployed LTS tree](https://github.com/mbicz/yogabook-linux-kernel/tree/fe92d01241f2adc9acec9e78dc232c0a21f8608e),
[commit c81f87c2f967](https://github.com/mbicz/yogabook-linux-kernel/commit/c81f87c2f967ef24c6f3ddbf20d3611b41751a1e).
That driver change is not in the current 21-commit 6.17 submission.

Use your own camera-corrected OEM-revision-6 DSDT and stock OEM-revision-3
`DptfTab` SSDT. On a boot without overrides, SSDT files are available under
`/sys/firmware/acpi/tables/`; select the table with OEM table ID `DptfTab`, not
an arbitrary SSDT. The script checks complete input hashes and refuses unknown
firmware. Camera DSDT generation is documented in
[yogabook-camera/KERNEL.md](https://github.com/mbicz/yogabook-camera/blob/v0.1/KERNEL.md).

```sh
python3 acpi/patch_thermal_tables.py dsdt-camera.aml dsdt-thermal.aml
python3 acpi/patch_thermal_tables.py ssdt-DptfTab-stock.aml ssdt-thermal.aml
```

Outputs are DSDT revision 7 and SSDT revision 4. They preserve table lengths,
trip points and unrelated methods. Plausible changing temperatures were observed;
calibration, thermal trip actions and load-cooling effectiveness are not claimed.
Only thermal reads are implemented by the kernel change, not full DPTF policy.

The [initramfs hook](initramfs-tools/hooks/yogabook-dsdt-override) is the original
integration. It prepends uncompressed early ACPI cpio for kernel releases
containing `-cam`; releases also containing `-thermal` require both thermal
outputs. Its input paths are explicit in the source. Those release tokens are
local deployment policy, not a kernel ABI. Do not install the hook or change a
remote boot entry without a known-good fallback and a recovery plan. No table
binaries or boot changes are supplied by this branch.

## Boot configuration and firmware

[yogabook-modprobe.conf](yogabook-modprobe.conf) prevents two unusable/conflicting
probes on this board: duplicate PC-speaker registration and unsupported Intel
SPI flash access. [kernel/quiet-boot.config](kernel/quiet-boot.config) records
the three deployed configuration changes that removed driver-debug flooding,
mislevelled Broadcom informational logs and the unusable uvesafb probe. This is
a fragment, not the complete build configuration. The old public defconfig is
not an exact copy of the deployed full configuration.

Other boot fixes are already in the
[kernel submission](https://github.com/jekhor/yogabook-linux-kernel/compare/master...mbicz:jekhor-submission):
duplicate GPS/virtual-GPIO enumeration and the YETI-11 i915 backlight quirk.
They are separate from GPS initialization and thermal-table correction. Some
ACPI and i915 workqueue warnings remain; not every boot message is fixed.

Audio works with the existing RT5677/SST drivers, Debian `firmware-intel-sound`
and the existing [Yoga Book UCM profiles](https://github.com/jekhor/alsa-ucm-conf-yogabook/tree/1b0f23d0fe722d991135808dc62d77cf1e1479c9/ucm2/cht-yogabook).
The missing DSP file was `intel/fw_sst_22a8.bin`; the speaker route also needed
to be enabled. No new audio-driver patch or persistent pro-audio override is
part of this work.

Bluetooth now loads the stock Lenovo patchram
`BCM4354A2_001.003.015.0079.0252_ORC.hcd` from S100043
`/vendor/etc/firmware/bt`, installed as `/lib/firmware/brcm/BCM4356A2.hcd`.
Build 0252 loads and the address stopped changing; pairing, audio/HID and
reconnect acceptance remain open. Obtain firmware from your own licensed
image: it is not redistributed here. Wi-Fi is PCIe BCM4356 and already worked;
any NVRAM MAC adjustment is per-device, not a value to copy from another unit.

## GPS comparison tools

[gps/](gps/) contains the vendor-runtime extractor and launcher source used for
comparison and the historical outdoor NMEA fix. Users supply their own stock
system image and proprietary daemon/libraries. The tools do not download or
redistribute those files. Preparation needs `debugfs` and `objdump`; launching
requires Linux root, a private mount namespace and exclusive UART access. Read
both scripts before running them; outputs can disclose location and belong
outside Git. There is no automatic GPS service or desktop-location integration.

The independent [bcm4752-init](https://github.com/mbicz/bcm4752-init) program
implements receiver power-up, firmware loading and initialization to GLME.
It does not implement tracking or generate the historical NMEA fix.

## Sleep policy, not a suspend fix

[logind-yogabook-nosleep.conf](logind-yogabook-nosleep.conf) records the current
remote-access safety policy. The sleep targets are masked separately and the
experimental lid watcher is disabled. The old watcher and one-off diagnostic
programs are intentionally not offered here as a working sleep implementation.
Repeated suspend has hung; this branch does not fix or enable it. Edge-LED
suspend callbacks and successful EFI power-off do not establish reliable sleep.
Ambient-light response also remains intermittent; automatic brightness is off.

## License

The exported helper/configuration sources are Copyright 2026 Michal Bicz,
GPL-2.0-or-later; see [COPYING](COPYING). No proprietary firmware, runtime
binaries, AML tables, location captures, private device identities or secrets
are included.
