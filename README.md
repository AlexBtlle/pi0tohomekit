# pi0 Camera Homekit

*[English version](README.en_US.md)*

Ce projet ne prend en charge que le streaming en direct de la caméra, si vous souhaitez utiliser la détection de mouvement, allez faire un tour sur cet autre projet : [Pi4 IA Homekit camera](https://github.com/AlexBtlle/pi4-IA-Homekit-Camera) (aussi compatible avec le Pi0 2w).

Projet open source permettant d'envoyer le flux vidéo d'une caméra CSI (module Pi Camera)
branchée sur un **Raspberry Pi Zero 2** vers l'application **Maison** d'Apple via **HomeKit**.

*J'ai pu installer pi0 Camera Homekit sur un pi 0 v1, l'installation a été extrêmement lonque (2-3h), mais ca semble fonctionner et être stable.*

L'ajout se fait par la saisie d'un code à 8 chiffres ou le scan d'un QRcode, exactement comme une caméra du commerce, et le visionnage en direct est totalement transparent dans l'application Maison.

## Fonctionnement

`pi0-Camera-HomeKiy` s'appuie sur [HAP-python](https://github.com/ikalchev/HAP-python), une
implémentation Python du protocole HomeKit Accessory Protocol. Le pont :

- s'annonce automatiquement sur le réseau via mDNS/Bonjour (détectable par l'app Maison) ;
- gère l'appairage chiffré et la négociation des sessions de streaming SRTP ;
- encode la vidéo en **H.264 matériel** avec `rpicam-vid` (pile `libcamera` de Raspberry Pi
  OS Bookworm), puis l'emballe en SRTP avec `ffmpeg` **sans réencodage** (`-c:v copy`).

Cette chaîne maintient une charge CPU minimale, adaptée aux 512 Mo du Raspberry Pi Zero 2.

## Caméras compatibles

Tout module caméra CSI supporté par **libcamera** sous Raspberry Pi OS Bookworm
fonctionne. En pratique :

| Module | Capteur | Autofocus | Réglage `autofocus` |
|--------|---------|-----------|---------------------|
| Pi Camera v1 | OV5647 | Non (fixe) | `none` |
| Pi Camera v2 | IMX219 | Non (fixe) | `none` |
| Pi Camera v3 | IMX708 | Oui | **`manual`** |
| Pi HQ Camera | IMX477 | Non (fixe) | `none` |
| Pi Global Shutter | IMX296 | Non (fixe) | `none` |
| Génériques CSI (fisheye, grand-angle…) | OV5647 / IMX219 | Non (fixe) | `none` |

> Les caméras à focus fixe (toutes sauf la v3) **ne supportent pas** l'option
> `--autofocus-mode`. Par défaut `autofocus: none` est utilisé et aucune option AF
> n'est transmise à `rpicam-vid`. Ne mettez `autofocus: manual` que si vous utilisez
> un **module Pi Camera v3**.
>
> Les modules **génériques/clones** (notamment OV5647) ne sont pas toujours auto-détectés :
> si `rpicam-hello --list-cameras` ne les voit pas, déclarez le `dtoverlay` correspondant
> dans `/boot/firmware/config.txt` (voir [Dépannage](#dépannage)).

## Prérequis

- Raspberry Pi Zero 2 sous **Raspberry Pi OS Bookworm**.
- Un module caméra CSI raccordé et activé.
- Le Pi et l'appareil Apple sur le **même réseau local** (AppleTV ou HomePod).

## Installation

```bash
git clone https://github.com/AlexBtlle/pi0-Camera-HomeKit.git
cd pi0-Camera-HomeKit
sudo ./install.sh
```

Le script installe les dépendances (`ffmpeg`, `rpicam-apps`, `avahi-daemon`…), crée un
environnement virtuel Python, génère un code d'appairage et active un service systemd qui
démarre automatiquement au boot durée ~ 3 min.

## Appairage dans l'application Maison

1. Affichez le QR code d'appairage généré au premier démarrage :

   ```bash
   journalctl -u pi0tohomekit -f
   ```
Ou utilisez le core d'appairage indiqué dans le script d'installation.

2. Sur l'iPhone/iPad, ouvrez l'app **Maison** → **+** → **Ajouter un accessoire**.
3. Scannez le QR code affiché dans le terminal (ou plus d'option, la caméra apparait et vous demande le code).
4. Acceptez que ce n'est pas un appareil officiel HomeKit.
5. La caméra apparaît comme un accessoire natif ; ouvrez sa vignette pour voir le flux en direct.

## Configuration

> ⚠️ **Important** : le service lit **`/opt/pi0tohomekit/config.yaml`** (et non la copie
> du dépôt git). C'est ce fichier-là qu'il faut éditer, avec `sudo` :
> `sudo nano /opt/pi0tohomekit/config.yaml`. Modifier le `config.yaml` cloné dans votre
> dossier personnel n'a aucun effet sur le service. Lors d'une mise à jour du code
> (`sudo cp -r src /opt/pi0tohomekit/`), votre configuration dans `/opt` est préservée.

Réglages disponibles :

| Section    | Clé        | Description                                              |
|------------|------------|----------------------------------------------------------|
| `camera`   | `width`, `height`, `fps` | Plafond de résolution et de fluidité (cf. note ci-dessous) |
| `camera`   | `bitrate`  | Débit vidéo en bits/s (≤ 4 Mbit/s recommandé sur Pi Zero 2) |
| `camera`   | `rotation` | Rotation de l'image : `0` ou `180` (90/270 non gérés par libcamera) |
| `camera`   | `autofocus`| `none` pour toute caméra à focus fixe (défaut) ; `manual` uniquement pour Pi Camera v3 |
| `homekit`  | `name`     | Nom affiché dans l'app Maison                            |
| `homekit`  | `pincode`  | Code d'appairage `XXX-XX-XXX` (généré si vide)           |
| `homekit`  | `port`     | Port TCP du pont HomeKit                                 |
| `advanced` | `profile`, `level` | Profil et niveau H.264 par défaut               |

Après modification : `sudo systemctl restart pi0tohomekit`.

`width`, `height` et `fps` plafonnent ce que le flux peut atteindre : seules les
résolutions inférieures ou égales sont annoncées à HomeKit, et `fps`/`bitrate` bornent
ce que la caméra encode même si l'app Maison demande davantage. C'est le levier principal
contre les saccades sur Pi Zero 2 (essayez 1280×720 à 20 fps). Si vous changez ces
valeurs, supprimez l'appairage et ré-ajoutez la caméra dans Maison pour que les nouvelles
capacités soient prises en compte.

## Lancement manuel (développement / débogage)

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python -m src.main
```

Le QR code et le code d'appairage s'affichent directement dans le terminal.

## Dépannage

- **Caméra générique non détectée** (flux et vignette en échec, `rpicam-jpeg`/`rpicam-vid`
  qui renvoient une erreur) : les modules CSI génériques/clones ne sont pas toujours
  auto-détectés sous Bookworm. Vérifiez d'abord avec `rpicam-hello --list-cameras` ; si la
  liste est vide, déclarez le capteur explicitement dans `/boot/firmware/config.txt` :

  ```ini
  camera_auto_detect=0
  dtoverlay=ov5647   # ou imx219, imx477, imx708… selon le capteur
  ```

  puis `sudo reboot`. Re-testez ensuite `rpicam-hello --list-cameras`.
- **La caméra n'apparaît pas dans Maison** : vérifiez que `avahi-daemon` tourne et que le Pi
  et l'appareil Apple sont sur le même réseau (`avahi-browse -rt _hap._tcp`).
- **Pas de flux / écran noir** : testez la chaîne caméra seule avec
  `rpicam-vid -t 5000 --codec h264 -o test.h264`. Les erreurs de `rpicam-vid` et
  `rpicam-jpeg` apparaissent aussi dans `journalctl -u pi0tohomekit`.
- **Réappairer depuis zéro** : arrêtez le service, supprimez `/opt/pi0tohomekit/accessory.state`,
  puis redémarrez le service.

## Licence

GPLv3 — voir [LICENSE](LICENSE).
