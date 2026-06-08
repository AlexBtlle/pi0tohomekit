# pi0tohomekit

Projet open source permettant d'envoyer le flux vidéo d'une caméra CSI (module Pi Camera)
branchée sur un **Raspberry Pi Zero 2** vers l'application **Maison** d'Apple via **HomeKit**.

L'ajout se fait par simple scan d'un QR code, exactement comme une caméra du commerce
(par exemple une caméra Eve), et le visionnage en direct est totalement transparent dans
l'application Maison.

## Fonctionnement

`pi0tohomekit` s'appuie sur [HAP-python](https://github.com/ikalchev/HAP-python), une
implémentation Python du protocole HomeKit Accessory Protocol. Le pont :

- s'annonce automatiquement sur le réseau via mDNS/Bonjour (détectable par l'app Maison) ;
- gère l'appairage chiffré et la négociation des sessions de streaming SRTP ;
- encode la vidéo en **H.264 matériel** avec `rpicam-vid` (pile `libcamera` de Raspberry Pi
  OS Bookworm), puis l'emballe en SRTP avec `ffmpeg` **sans réencodage** (`-c:v copy`).

Cette chaîne maintient une charge CPU minimale, adaptée aux 512 Mo du Raspberry Pi Zero 2.

## Prérequis

- Raspberry Pi Zero 2 (ou modèle plus récent) sous **Raspberry Pi OS Bookworm**.
- Un module caméra CSI raccordé et activé (Bookworm le détecte automatiquement).
- Le Pi et l'appareil Apple sur le **même réseau local**.

## Installation

```bash
git clone https://github.com/AlexBtlle/pi0tohomekit.git
cd pi0tohomekit
sudo ./install.sh
```

Le script installe les dépendances (`ffmpeg`, `rpicam-apps`, `avahi-daemon`…), crée un
environnement virtuel Python, génère un code d'appairage et active un service systemd qui
démarre automatiquement au boot.

## Appairage dans l'application Maison

1. Affichez le QR code d'appairage généré au premier démarrage :

   ```bash
   journalctl -u pi0tohomekit -f
   ```

2. Sur l'iPhone/iPad, ouvrez l'app **Maison** → **+** → **Ajouter un accessoire**.
3. Scannez le QR code affiché dans le terminal.
4. La caméra apparaît comme un accessoire natif ; ouvrez sa vignette pour voir le flux en direct.

## Configuration

Les réglages se trouvent dans `config.yaml` (copié dans `/opt/pi0tohomekit/config.yaml`
lors de l'installation) :

| Section    | Clé        | Description                                              |
|------------|------------|----------------------------------------------------------|
| `camera`   | `width`, `height`, `fps` | Résolution et fluidité de la capture        |
| `camera`   | `bitrate`  | Débit vidéo en bits/s (≤ 4 Mbit/s recommandé)            |
| `camera`   | `rotation` | Rotation de l'image : 0, 90, 180, 270                    |
| `homekit`  | `name`     | Nom affiché dans l'app Maison                            |
| `homekit`  | `pincode`  | Code d'appairage `XXX-XX-XXX` (généré si vide)           |
| `homekit`  | `port`     | Port TCP du pont HomeKit                                 |
| `advanced` | `profile`, `level` | Profil et niveau H.264 par défaut               |

Après modification : `sudo systemctl restart pi0tohomekit`.

## Lancement manuel (développement / débogage)

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python -m src.main
```

Le QR code et le code d'appairage s'affichent directement dans le terminal.

## Dépannage

- **La caméra n'apparaît pas dans Maison** : vérifiez que `avahi-daemon` tourne et que le Pi
  et l'appareil Apple sont sur le même réseau (`avahi-browse -rt _hap._tcp`).
- **Pas de flux / écran noir** : testez la chaîne caméra seule avec
  `rpicam-vid -t 5000 --codec h264 -o test.h264`.
- **Réappairer depuis zéro** : arrêtez le service, supprimez `/opt/pi0tohomekit/accessory.state`,
  puis redémarrez le service.

## Licence

GPLv3 — voir [LICENSE](LICENSE).
