# pi0tohomekit

Projet open source permettant d'envoyer le flux vidéo d'une caméra CSI (module Pi Camera)
branchée sur un **Raspberry Pi Zero 2** vers l'application **Maison** d'Apple via **HomeKit**.

L'ajout se fait par la saisie d'un code à 6 chiffres (QRcode en cours de développement), exactement comme une caméra du commerce, et le visionnage en direct est totalement transparent dans l'application Maison.

## Fonctionnement

`pi0tohomekit` s'appuie sur [HAP-python](https://github.com/ikalchev/HAP-python), une
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

## Détection de personne (Motion Sensor HomeKit)

### Fonctionnement

La détection fonctionne en deux étapes combinées (mode `hybrid`, recommandé) :

1. **Frame differencing** (différence de luminance entre deux snapshots) — filtre CPU ultra-léger
   qui détecte tout mouvement ;
2. **Inférence IA** (EfficientDet-Lite0 int8, TensorFlow Lite) — ne s'exécute que si
   l'étape 1 détecte un mouvement, et confirme ou infirme la présence d'une personne.

La détection tourne en tâche de fond permanente et prend un snapshot via `rpicam-jpeg` toutes
les `interval` secondes. Elle est automatiquement suspendue quand un flux HomeKit est actif
(la caméra est alors occupée par `rpicam-vid`).

Quand une personne est détectée, le **Motion Sensor** apparaît comme « Mouvement détecté »
dans l'application Maison, pendant `cooldown` secondes. Vous pouvez créer une automatisation
HomeKit (ex. : *Quand Pi Camera détecte un mouvement → Envoyer une notification*).

### Charge sur Pi Zero 2

| Composant | RAM | CPU moyen |
|-----------|-----|-----------|
| Runtime TFLite + modèle | +30 MB | — |
| Détection (1 inférence toutes les ~30 s) | — | < 5 % |
| Streaming H.264 (inchangé) | — | ~0,2 % |

L'encodage H.264 reste 100 % matériel (ISP) — la détection IA n'affecte pas la fluidité du flux.

### Configuration

Section `detection` dans `/opt/pi0tohomekit/config.yaml` :

```yaml
detection:
  mode: hybrid        # off | motion | hybrid (motion + IA personne)
  sensitivity: 25     # Seuil de mouvement (0–100 ; plus bas = plus sensible)
  confidence: 0.5     # Score IA minimum pour valider une personne (0–1)
  cooldown: 15        # Secondes avant remise à zéro du capteur dans Maison
  interval: 3         # Secondes entre deux prises de vue pour la détection
```

| `mode`     | Description |
|------------|-------------|
| `off`      | Détection désactivée (aucune charge supplémentaire) |
| `motion`   | Mouvement uniquement (frame diff, pas d'IA — aucune dépendance TFLite) |
| `hybrid`   | Mouvement comme pré-filtre, puis IA pour confirmer une personne (recommandé) |

> **Conseil** : commencez par `mode: motion` pour valider que le Motion Sensor fonctionne
> dans l'app Maison, puis passez à `hybrid` pour réduire les faux positifs (animaux, lumière…).

### Si le modèle n'est pas téléchargé

`install.sh` télécharge automatiquement le modèle EfficientDet-Lite0 depuis les dépôts
officiels Google Coral. Si le téléchargement a échoué, relancez manuellement :

```bash
cd /opt/pi0tohomekit
sudo mkdir -p models
sudo wget -O models/efficientdet_lite0_uint8.tflite \
    'https://github.com/google-coral/test_data/raw/master/efficientdet_lite0_uint8.tflite'
sudo wget -O models/coco_labels.txt \
    'https://raw.githubusercontent.com/google-coral/test_data/master/coco_labels.txt'
```

En l'absence du modèle, le mode `hybrid` se dégrade automatiquement vers `motion`.

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
