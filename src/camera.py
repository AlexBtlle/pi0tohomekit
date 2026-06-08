"""Accessoire caméra HomeKit s'appuyant sur la caméra CSI d'un Raspberry Pi.

La diffusion repose sur ``rpicam-vid`` (encodage H.264 matériel via libcamera sous
Raspberry Pi OS Bookworm) dont la sortie est redirigée vers ``ffmpeg`` en mode
``-c:v copy`` : FFmpeg ne fait que l'emballage SRTP attendu par HomeKit, sans
réencodage. Cela maintient une charge CPU minimale, adaptée au Raspberry Pi Zero 2.
"""

import asyncio
import logging
import subprocess

from pyhap.camera import (
    Camera,
    VIDEO_CODEC_PARAM_LEVEL_TYPES,
    VIDEO_CODEC_PARAM_PROFILE_ID_TYPES,
)

logger = logging.getLogger(__name__)

# Correspondance entre les profils/niveaux H.264 négociés par HomeKit et les
# arguments attendus par rpicam-vid.
_PROFILE_TO_RPICAM = {
    VIDEO_CODEC_PARAM_PROFILE_ID_TYPES["BASELINE"]: "baseline",
    VIDEO_CODEC_PARAM_PROFILE_ID_TYPES["MAIN"]: "main",
    VIDEO_CODEC_PARAM_PROFILE_ID_TYPES["HIGH"]: "high",
}

_LEVEL_TO_RPICAM = {
    VIDEO_CODEC_PARAM_LEVEL_TYPES["TYPE3_1"]: "4",
    VIDEO_CODEC_PARAM_LEVEL_TYPES["TYPE3_2"]: "4",
    VIDEO_CODEC_PARAM_LEVEL_TYPES["TYPE4_0"]: "4",
}


def build_options(address, resolutions):
    """Construit le dictionnaire d'options déclaré à HomeKit.

    :param address: adresse IP locale annoncée pour les flux SRTP.
    :param resolutions: liste de ``[largeur, hauteur, fps]`` supportées.
    """
    return {
        "video": {
            "codec": {
                "profiles": [
                    VIDEO_CODEC_PARAM_PROFILE_ID_TYPES["BASELINE"],
                    VIDEO_CODEC_PARAM_PROFILE_ID_TYPES["MAIN"],
                    VIDEO_CODEC_PARAM_PROFILE_ID_TYPES["HIGH"],
                ],
                "levels": [
                    VIDEO_CODEC_PARAM_LEVEL_TYPES["TYPE3_1"],
                    VIDEO_CODEC_PARAM_LEVEL_TYPES["TYPE3_2"],
                    VIDEO_CODEC_PARAM_LEVEL_TYPES["TYPE4_0"],
                ],
            },
            "resolutions": resolutions,
        },
        # HomeKit exige qu'au moins un codec audio soit négociable même lorsque le
        # flux est uniquement vidéo. On déclare Opus mais aucune piste audio n'est
        # réellement émise (option ``-an`` côté ffmpeg).
        "audio": {
            "codecs": [
                {"type": "OPUS", "samplerate": 24},
                {"type": "OPUS", "samplerate": 16},
            ],
        },
        "srtp": True,
        "address": address,
    }


class PiCamera(Camera):
    """Caméra HomeKit diffusant le module CSI du Raspberry Pi."""

    def __init__(self, options, driver, name, camera_config):
        """:param camera_config: section ``camera``/``advanced`` du fichier de config."""
        super().__init__(options, driver, name)
        self._camera_config = camera_config
        # Note : on ne crée pas notre propre dictionnaire de sessions. pyhap gère
        # déjà ``self.sessions`` en interne (un dict ``session_info`` par session,
        # contenant notamment ``stream_idx``). On stocke nos processus directement
        # dans ce ``session_info``, comme le fait l'implémentation par défaut.

    # -- Construction des commandes ------------------------------------------------

    def _rpicam_cmd(self, stream_config):
        cfg = self._camera_config
        width = stream_config["width"]
        height = stream_config["height"]
        # On plafonne fps et bitrate par la config : HomeKit négocie parfois des
        # valeurs supérieures à ce que le Pi Zero 2 encode/transmet sans saccades.
        fps = stream_config["fps"]
        if cfg.get("fps"):
            fps = min(fps, int(cfg["fps"]))
        # HomeKit fournit le bitrate maximal en kbit/s ; rpicam-vid attend des bit/s.
        bitrate = int(stream_config["v_max_bitrate"]) * 1000
        if cfg.get("bitrate"):
            bitrate = min(bitrate, int(cfg["bitrate"]))

        profile = _PROFILE_TO_RPICAM.get(
            stream_config.get("v_profile_id"), cfg.get("profile", "baseline")
        )
        level = _LEVEL_TO_RPICAM.get(
            stream_config.get("v_level"), str(cfg.get("level", "4"))
        )

        cmd = [
            "rpicam-vid",
            "-t", "0",
            "--inline",
            "--nopreview",
            "--width", str(width),
            "--height", str(height),
            "--framerate", str(fps),
            "--codec", "h264",
            "--profile", profile,
            "--level", level,
            "--bitrate", str(bitrate),
        ]

        rotation = int(cfg.get("rotation", 0))
        if rotation in (90, 180, 270):
            cmd += ["--rotation", str(rotation)]

        # Le module v3 (autofocus) initialise l'AF avant de démarrer le flux, ce
        # qui dépasse le délai d'attente de HomeKit et provoque un écran noir.
        # En mode manuel l'image commence immédiatement.
        autofocus = cfg.get("autofocus", "manual")
        cmd += ["--autofocus-mode", autofocus]

        cmd += ["-o", "-"]
        return cmd

    def _ffmpeg_cmd(self, stream_config):
        # pyhap ne décode pas v_payload_type : il le transmet sous forme d'octets
        # bruts (p. ex. b'c' pour 99). On le convertit en entier pour ffmpeg.
        payload_type = stream_config.get("v_payload_type", 99)
        if isinstance(payload_type, (bytes, bytearray)):
            payload_type = int.from_bytes(payload_type, "little")

        return [
            "ffmpeg",
            "-hide_banner",
            "-loglevel", "warning",
            "-f", "h264",
            "-i", "-",
            "-c:v", "copy",
            "-an",
            "-payload_type", str(payload_type),
            "-ssrc", str(stream_config["v_ssrc"]),
            "-f", "rtp",
            "-srtp_out_suite", "AES_CM_128_HMAC_SHA1_80",
            "-srtp_out_params", stream_config["v_srtp_key"],
            "srtp://{address}:{v_port}?rtcpport={v_port}&"
            "localrtcpport={v_port}&pkt_size=1316".format(
                address=stream_config["address"],
                v_port=stream_config["v_port"],
            ),
        ]

    # -- Cycle de vie des flux -----------------------------------------------------

    async def start_stream(self, session_info, stream_config):
        session_id = session_info["id"]
        rpicam_cmd = self._rpicam_cmd(stream_config)
        ffmpeg_cmd = self._ffmpeg_cmd(stream_config)

        logger.info("Démarrage du flux %s", session_id)
        logger.debug("rpicam-vid: %s", " ".join(rpicam_cmd))
        logger.debug("ffmpeg: %s", " ".join(ffmpeg_cmd))

        # On utilise subprocess.Popen (et non asyncio) pour relier directement la
        # sortie de rpicam-vid à l'entrée de ffmpeg, comme un pipe shell. Popen
        # rend la main immédiatement ; les processus tournent en arrière-plan.
        # stderr de ffmpeg est hérité du service (→ journald) afin que les erreurs
        # d'encodage/streaming soient visibles via journalctl.
        try:
            rpicam_proc = subprocess.Popen(
                rpicam_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            ffmpeg_proc = subprocess.Popen(
                ffmpeg_cmd,
                stdin=rpicam_proc.stdout,
                stdout=subprocess.DEVNULL,
                stderr=None,
            )
        except Exception:
            logger.exception("Échec du lancement du flux %s", session_id)
            return False

        # Permet à rpicam-vid de recevoir un SIGPIPE si ffmpeg se termine.
        rpicam_proc.stdout.close()

        # On stocke les processus dans le session_info géré par pyhap : le même
        # objet sera transmis à stop_stream. Surtout ne pas réutiliser
        # self.sessions, qui appartient à pyhap.
        session_info["rpicam_proc"] = rpicam_proc
        session_info["ffmpeg_proc"] = ffmpeg_proc
        return True

    async def stop_stream(self, session_info):
        # pyhap fait ``await self.stop_stream(...)`` : la méthode doit être une
        # coroutine, sinon ``await None`` lève une TypeError.
        session_id = session_info["id"]
        logger.info("Arrêt du flux %s", session_id)
        # On termine ffmpeg avant rpicam-vid pour éviter une écriture sur pipe fermé.
        for key in ("ffmpeg_proc", "rpicam_proc"):
            proc = session_info.get(key)
            if proc is None or proc.poll() is not None:
                continue
            try:
                proc.terminate()
            except ProcessLookupError:
                pass

    def reconfigure_stream(self, session_info, stream_config):
        # La reconfiguration à chaud n'est pas nécessaire pour un flux en direct :
        # HomeKit renégocie une nouvelle session si les paramètres changent.
        return True

    # -- Vignette ------------------------------------------------------------------

    async def async_get_snapshot(self, image_size):
        # pyhap appelle ``async_get_snapshot`` (coroutine) en priorité sur
        # ``get_snapshot`` (cf. hap_handler.py). Définir une coroutine ici évite
        # le « coroutine has no len() » qui survenait quand pyhap exécutait une
        # méthode async via run_in_executor.
        width = image_size.get("image-width", 1280)
        height = image_size.get("image-height", 720)
        autofocus = self._camera_config.get("autofocus", "manual")
        cmd = [
            "rpicam-jpeg",
            "--nopreview",
            "-t", "1",
            "--width", str(width),
            "--height", str(height),
            "--autofocus-mode", autofocus,
            "-o", "-",
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            stdout, _ = await proc.communicate()
            if proc.returncode == 0 and stdout:
                return stdout
            logger.warning("rpicam-jpeg a échoué (code %s)", proc.returncode)
        except Exception:
            # La caméra est probablement déjà occupée par un flux en cours.
            logger.exception("Capture de vignette impossible")
        return b""
