# pi0 Camera Homekit

*[Version française](README.md)*

Open-source project that streams the video feed of a CSI camera (Pi Camera module)
connected to a **Raspberry Pi Zero 2** to Apple's **Home** app via **HomeKit**.

*I was able to install pi0-Camera-HomeKit on a Pi Zero v1, the installation took an extremely long time (2–3h), but it seems to work and run stable.*

Adding the camera is done by entering an 8-digit code or scanning a QR code, just like a
commercial camera, and live viewing is completely seamless in the Home app.

## How it works

`pi0tohomekit` is built on [HAP-python](https://github.com/ikalchev/HAP-python), a Python
implementation of the HomeKit Accessory Protocol. The bridge:

- advertises itself automatically on the network via mDNS/Bonjour (discoverable by the Home app);
- handles encrypted pairing and SRTP streaming session negotiation;
- encodes video in **hardware H.264** with `rpicam-vid` (the `libcamera` stack on Raspberry Pi
  OS Bookworm), then wraps it in SRTP with `ffmpeg` **without re-encoding** (`-c:v copy`).

This pipeline keeps CPU usage minimal, suited to the 512 MB of the Raspberry Pi Zero 2.

## Compatible cameras

Any CSI camera module supported by **libcamera** on Raspberry Pi OS Bookworm works.
In practice:

| Module | Sensor | Autofocus | `autofocus` setting |
|--------|--------|-----------|---------------------|
| Pi Camera v1 | OV5647 | No (fixed) | `none` |
| Pi Camera v2 | IMX219 | No (fixed) | `none` |
| Pi Camera v3 | IMX708 | Yes | **`manual`** |
| Pi HQ Camera | IMX477 | No (fixed) | `none` |
| Pi Global Shutter | IMX296 | No (fixed) | `none` |
| Generic CSI (fisheye, wide-angle…) | OV5647 / IMX219 | No (fixed) | `none` |

> Fixed-focus cameras (all except the v3) **do not support** the `--autofocus-mode`
> option. By default `autofocus: none` is used and no AF option is passed to
> `rpicam-vid`. Only set `autofocus: manual` if you are using a **Pi Camera v3 module**.
>
> **Generic/clone** modules (notably OV5647) are not always auto-detected: if
> `rpicam-hello --list-cameras` does not see them, declare the matching `dtoverlay` in
> `/boot/firmware/config.txt` (see [Troubleshooting](#troubleshooting)).

## Requirements

- Raspberry Pi Zero 2 running **Raspberry Pi OS Bookworm**.
- A CSI camera module connected and enabled.
- The Pi and the Apple device on the **same local network** (Apple TV or HomePod).

## Installation

```bash
git clone https://github.com/AlexBtlle/pi0-Camera-HomeKit.git
cd pi0-Camera-HomeKit
sudo ./install.sh
```

The script installs the dependencies (`ffmpeg`, `rpicam-apps`, `avahi-daemon`…), creates a
Python virtual environment, generates a pairing code and enables a systemd service that
starts automatically at boot (takes ~3 min).

## Pairing in the Home app

1. Display the pairing QR code generated on first start:

   ```bash
   journalctl -u pi0tohomekit -f
   ```
   Or use the pairing code shown in the install script output.

2. On your iPhone/iPad, open the **Home** app → **+** → **Add Accessory**.
3. Scan the QR code shown in the terminal (or tap "More options…", the camera appears and
   asks for the code).
4. Accept that this is not an official HomeKit accessory.
5. The camera appears as a native accessory; open its thumbnail to view the live feed.

## Configuration

> ⚠️ **Important**: the service reads **`/opt/pi0tohomekit/config.yaml`** (not the copy in
> the git repository). That is the file you must edit, with `sudo`:
> `sudo nano /opt/pi0tohomekit/config.yaml`. Editing the `config.yaml` cloned in your home
> directory has no effect on the service. When updating the code
> (`sudo cp -r src /opt/pi0tohomekit/`), your configuration in `/opt` is preserved.

Available settings:

| Section    | Key        | Description                                              |
|------------|------------|----------------------------------------------------------|
| `camera`   | `width`, `height`, `fps` | Resolution and frame-rate cap (see note below) |
| `camera`   | `bitrate`  | Video bitrate in bits/s (≤ 4 Mbit/s recommended on Pi Zero 2) |
| `camera`   | `rotation` | Image rotation: `0` or `180` (90/270 not supported by libcamera) |
| `camera`   | `autofocus`| `none` for any fixed-focus camera (default); `manual` only for Pi Camera v3 |
| `homekit`  | `name`     | Name shown in the Home app                               |
| `homekit`  | `pincode`  | Pairing code `XXX-XX-XXX` (generated if empty)           |
| `homekit`  | `port`     | HomeKit bridge TCP port                                  |
| `advanced` | `profile`, `level` | Default H.264 profile and level                  |

After editing: `sudo systemctl restart pi0tohomekit`.

`width`, `height` and `fps` cap what the stream can reach: only resolutions less than or
equal to them are advertised to HomeKit, and `fps`/`bitrate` bound what the camera encodes
even if the Home app requests more. This is the main lever against stutter on the Pi Zero 2
(try 1280×720 at 20 fps). If you change these values, remove the pairing and re-add the
camera in the Home app so the new capabilities are taken into account.

## Manual launch (development / debugging)

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python -m src.main
```

The QR code and the pairing code are printed directly in the terminal.

## Troubleshooting

- **Generic camera not detected** (stream and thumbnail failing, `rpicam-jpeg`/`rpicam-vid`
  returning an error): generic/clone CSI modules are not always auto-detected on Bookworm.
  Check first with `rpicam-hello --list-cameras`; if the list is empty, declare the sensor
  explicitly in `/boot/firmware/config.txt`:

  ```ini
  camera_auto_detect=0
  dtoverlay=ov5647   # or imx219, imx477, imx708… depending on the sensor
  ```

  then `sudo reboot`. Re-test with `rpicam-hello --list-cameras`.
- **The camera does not appear in Home**: check that `avahi-daemon` is running and that the
  Pi and the Apple device are on the same network (`avahi-browse -rt _hap._tcp`).
- **No stream / black screen**: test the camera chain on its own with
  `rpicam-vid -t 5000 --codec h264 -o test.h264`. Errors from `rpicam-vid` and `rpicam-jpeg`
  also appear in `journalctl -u pi0tohomekit`.
- **Re-pair from scratch**: stop the service, delete `/opt/pi0tohomekit/accessory.state`,
  then restart the service.

## License

GPLv3 — see [LICENSE](LICENSE).
