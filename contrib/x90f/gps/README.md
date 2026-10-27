# GPS on the Yoga Book YB1-X90F

The clean-room BCM4752 initialisation daemon moved out of this repository and now lives on its own with its
full commit history:

    https://github.com/mbicz/bcm4752-init

What remains here is only the vendor-runtime tooling used for comparison on this device:

| file | role |
| --- | --- |
| `prepare_runtime.py` | extracts the stock GPS daemon and its bionic dependency closure from your own `system.ext4` into a chroot runtime; proprietary files stay outside git |
| `run_gps.py` | launches that runtime as root, checks the daemon hash, and saves NMEA and a `strace` trace for comparison |

The reimplementation is the thing to use if you want the GPS initialised: run it against the RAM patch
extracted from your own copy of the vendor daemon. Nothing in this repository redistributes Broadcom
firmware.
