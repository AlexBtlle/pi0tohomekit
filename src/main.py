"""Point d'entrée : charge la configuration, démarre le pont HomeKit et affiche
le QR code d'appairage."""

import logging
import os
import signal
import socket
import sys

import yaml
from pyhap.accessory_driver import AccessoryDriver

from .camera import PiCamera, build_options

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("pi0tohomekit")

# Emplacements recherchés pour le fichier de configuration.
_CONFIG_CANDIDATES = (
    os.environ.get("PI0TOHOMEKIT_CONFIG"),
    os.path.join(os.getcwd(), "config.yaml"),
    "/opt/pi0tohomekit/config.yaml",
)

# Résolutions annoncées à HomeKit : [largeur, hauteur, fps].
SUPPORTED_RESOLUTIONS = [
    [1920, 1080, 30],
    [1280, 720, 30],
    [640, 480, 30],
    [320, 240, 15],
]


def load_config():
    for path in _CONFIG_CANDIDATES:
        if path and os.path.isfile(path):
            logger.info("Configuration chargée depuis %s", path)
            with open(path, "r", encoding="utf-8") as fh:
                return yaml.safe_load(fh) or {}
    logger.error("Aucun fichier config.yaml trouvé.")
    sys.exit(1)


def get_local_address():
    """Détecte l'adresse IP locale utilisée pour joindre le réseau."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Aucune donnée n'est réellement envoyée ; sert à choisir l'interface.
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def print_pairing_info(accessory, driver):
    """Affiche le QR code et le PIN pour l'ajout dans l'application Maison."""
    pincode = driver.state.pincode.decode()
    setup_uri = accessory.xhm_uri()

    print("\n" + "=" * 48)
    print(" Ajout à l'application Maison (Apple HomeKit)")
    print("=" * 48)
    try:
        import qrcode

        qr = qrcode.QRCode(border=2)
        qr.add_data(setup_uri)
        qr.print_ascii(invert=True)
    except Exception:
        logger.warning("Module qrcode indisponible ; QR code non affiché.")
    print(f" Code d'appairage : {pincode}")
    print(f" URI de configuration : {setup_uri}")
    print("=" * 48 + "\n")


def main():
    config = load_config()
    camera_cfg = config.get("camera", {})
    advanced_cfg = config.get("advanced", {})
    homekit_cfg = config.get("homekit", {})

    # Fusionne les réglages caméra/avancés transmis à l'accessoire.
    camera_config = {**camera_cfg, **advanced_cfg}

    address = get_local_address()
    logger.info("Adresse IP locale détectée : %s", address)

    options = build_options(address, SUPPORTED_RESOLUTIONS)

    persist_file = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "accessory.state"
    )

    driver = AccessoryDriver(
        address=address,
        port=int(homekit_cfg.get("port", 51826)),
        persist_file=persist_file,
        pincode=homekit_cfg.get("pincode", "").encode() or None,
    )

    accessory = PiCamera(
        options,
        driver,
        homekit_cfg.get("name", "Pi Camera"),
        camera_config,
    )
    driver.add_accessory(accessory=accessory)

    print_pairing_info(accessory, driver)

    signal.signal(signal.SIGTERM, driver.signal_handler)
    signal.signal(signal.SIGINT, driver.signal_handler)

    logger.info("Démarrage du pont HomeKit…")
    driver.start()


if __name__ == "__main__":
    main()
