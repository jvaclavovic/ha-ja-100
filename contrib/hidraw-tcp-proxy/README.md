# hidraw-tcp-proxy

Exposes the Jablotron JA-100 USB cable (HID device `16d6:0008`) over TCP so
that the `jablotron100` integration can run on a host that does not have the
cable attached (for example a Home Assistant VM that must stay live-migratable).

Protocol: both directions use frames `!H` (2-byte big-endian length) + payload.
Each HID input report (64 B) from the device is sent to every connected client
as one frame; each frame from a client is written to the device as one report.

## Install (Debian / Raspberry Pi OS)

```sh
sudo mkdir -p /opt/hidraw-tcp-proxy
sudo cp hidraw_tcp_proxy.py /opt/hidraw-tcp-proxy/
sudo cp hidraw-tcp-proxy.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now hidraw-tcp-proxy
```

The device must not be bound to `usbip-host` on the same machine (unbind it or
disable `usbipd` first), otherwise `/dev/hidrawN` will not exist.

## Home Assistant side

In the Jablotron 100 integration set the serial port to `tcp://<host>:8765`.
