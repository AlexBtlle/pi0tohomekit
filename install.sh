#!/usr/bin/env bash
#
# Installeur pi0tohomekit : installe les dépendances, configure un environnement
# virtuel Python et active le service systemd. À exécuter sur le Raspberry Pi.
#
#   sudo ./install.sh
#
set -euo pipefail

INSTALL_DIR="/opt/pi0tohomekit"
SERVICE_NAME="pi0tohomekit"
# Utilisateur sous lequel tournera le service (défaut : l'utilisateur appelant sudo).
RUN_USER="${SUDO_USER:-pi}"

if [[ $EUID -ne 0 ]]; then
    echo "Ce script doit être exécuté avec sudo." >&2
    exit 1
fi

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> Installation des paquets système…"
apt-get update
apt-get install -y python3-venv python3-pip ffmpeg rpicam-apps avahi-daemon

echo "==> Copie du projet vers ${INSTALL_DIR}…"
mkdir -p "${INSTALL_DIR}"
# Copie le code source et les fichiers de support (sans l'état d'appairage ni le venv).
cp -r "${SRC_DIR}/src" "${INSTALL_DIR}/"
cp "${SRC_DIR}/requirements.txt" "${INSTALL_DIR}/"
# Ne pas écraser une configuration existante.
if [[ ! -f "${INSTALL_DIR}/config.yaml" ]]; then
    cp "${SRC_DIR}/config.yaml" "${INSTALL_DIR}/config.yaml"
fi

echo "==> Création de l'environnement virtuel Python…"
python3 -m venv "${INSTALL_DIR}/venv"
"${INSTALL_DIR}/venv/bin/pip" install --upgrade pip
"${INSTALL_DIR}/venv/bin/pip" install -r "${INSTALL_DIR}/requirements.txt"

echo "==> Installation de la runtime TFLite (nécessaire pour la détection de personne)…"
# ai-edge-litert est le successeur de tflite-runtime (dispo sur aarch64 Bookworm).
"${INSTALL_DIR}/venv/bin/pip" install ai-edge-litert 2>/dev/null \
    || "${INSTALL_DIR}/venv/bin/pip" install tflite-runtime 2>/dev/null \
    || echo "    ⚠  Runtime TFLite non disponible — seul le mode 'motion' fonctionnera."

echo "==> Téléchargement du modèle de détection de personne…"
mkdir -p "${INSTALL_DIR}/models"
MODEL_FILE="${INSTALL_DIR}/models/efficientdet_lite0_uint8.tflite"
LABELS_FILE="${INSTALL_DIR}/models/coco_labels.txt"

if [[ ! -f "${MODEL_FILE}" ]]; then
    wget -q --show-progress -O "${MODEL_FILE}" \
        'https://github.com/google-coral/test_data/raw/master/efficientdet_lite0_uint8.tflite' \
        || { echo "    ⚠  Téléchargement du modèle échoué — mode 'hybrid' indisponible." ; rm -f "${MODEL_FILE}" ; }
fi
if [[ ! -f "${LABELS_FILE}" ]]; then
    wget -q --show-progress -O "${LABELS_FILE}" \
        'https://raw.githubusercontent.com/google-coral/test_data/master/coco_labels.txt' \
        || { echo "    ⚠  Téléchargement des labels échoué." ; rm -f "${LABELS_FILE}" ; }
fi

echo "==> Génération du code d'appairage si nécessaire…"
# Génère un PIN au format HomeKit XXX-XX-XXX si le champ est vide.
if grep -qE '^[[:space:]]*pincode:[[:space:]]*""' "${INSTALL_DIR}/config.yaml"; then
    PIN="$(printf '%03d-%02d-%03d' \
        "$((RANDOM % 1000))" "$((RANDOM % 100))" "$((RANDOM % 1000))")"
    sed -i "s/^\([[:space:]]*pincode:[[:space:]]*\)\"\"/\1\"${PIN}\"/" "${INSTALL_DIR}/config.yaml"
    echo "    Code d'appairage généré : ${PIN}"
fi

echo "==> Permissions…"
chown -R "${RUN_USER}:${RUN_USER}" "${INSTALL_DIR}"
# Accès à la caméra et au GPU.
usermod -aG video "${RUN_USER}" || true
# Accès aux groupes caméra/I2C pour libcamera.
usermod -aG i2c "${RUN_USER}" 2>/dev/null || true

echo "==> Installation du service systemd…"
sed "s/__USER__/${RUN_USER}/" "${SRC_DIR}/${SERVICE_NAME}.service" \
    > "/etc/systemd/system/${SERVICE_NAME}.service"
systemctl daemon-reload
systemctl enable --now "${SERVICE_NAME}"

echo
echo "==> Installation terminée."
echo "    Affichez le QR code d'appairage avec :"
echo "        journalctl -u ${SERVICE_NAME} -f"
echo "    Puis scannez-le dans l'application Maison (Ajouter un accessoire)."
