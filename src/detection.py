"""Détection de personne : frame differencing (léger) + inférence TFLite (EfficientDet-Lite0).

Le module est importable même si tflite_runtime/ai_edge_litert n'est pas installé ;
la classe Detector lèvera ImportError uniquement au moment de l'instanciation.
"""

import io
import logging
import os

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

# Index COCO 0-based pour "person" dans coco_labels.txt (Coral/TFHub)
_DEFAULT_PERSON_IDX = 0


def jpeg_to_gray(jpeg_bytes: bytes, size: tuple[int, int] = (320, 240)) -> np.ndarray:
    """Décode un JPEG et retourne un tableau uint8 en niveaux de gris."""
    img = Image.open(io.BytesIO(jpeg_bytes)).convert("L").resize(size, Image.LANCZOS)
    return np.array(img, dtype=np.uint8)


def has_motion(prev: np.ndarray | None, curr: np.ndarray, sensitivity: float) -> bool:
    """Retourne True si la différence absolue moyenne de luminance dépasse le seuil."""
    if prev is None or prev.shape != curr.shape:
        return False
    return float(np.abs(curr.astype(np.int16) - prev.astype(np.int16)).mean()) > sensitivity


def _load_person_idx(labels_path: str | None) -> int:
    """Retourne l'index 0-based de la classe 'person' dans le fichier de labels."""
    if labels_path and os.path.isfile(labels_path):
        with open(labels_path, encoding="utf-8") as fh:
            for idx, line in enumerate(fh):
                if line.strip().lower() == "person":
                    return idx
    return _DEFAULT_PERSON_IDX


class Detector:
    """Détecteur de personnes via un modèle EfficientDet-Lite0 int8/uint8."""

    def __init__(self, model_path: str, confidence: float, labels_path: str | None = None):
        try:
            from ai_edge_litert.interpreter import Interpreter  # type: ignore[import]
        except ImportError:
            try:
                from tflite_runtime.interpreter import Interpreter  # type: ignore[import]
            except ImportError as exc:
                raise ImportError(
                    "Runtime TFLite introuvable. Installez : pip install ai-edge-litert"
                ) from exc

        self._confidence = confidence
        self._interp = Interpreter(model_path=model_path, num_threads=4)
        self._interp.allocate_tensors()

        inp = self._interp.get_input_details()[0]
        self._input_idx = inp["index"]
        _, h, w, _ = inp["shape"]
        self._input_size = (w, h)

        # EfficientDet-Lite0 : sorties [boxes(0), classes(1), scores(2), count(3)]
        self._out = self._interp.get_output_details()
        self._person_idx = _load_person_idx(labels_path)

        logger.info(
            "Modèle TFLite chargé : %s (entrée %dx%d, person=class %d)",
            os.path.basename(model_path), w, h, self._person_idx,
        )

    def detect_person(self, jpeg_bytes: bytes) -> bool:
        """Retourne True si une personne est détectée avec un score >= confidence."""
        w, h = self._input_size
        img = Image.open(io.BytesIO(jpeg_bytes)).convert("RGB").resize((w, h), Image.LANCZOS)
        arr = np.expand_dims(np.array(img, dtype=np.uint8), axis=0)

        self._interp.set_tensor(self._input_idx, arr)
        self._interp.invoke()

        classes = self._interp.get_tensor(self._out[1]["index"]).flatten()
        scores = self._interp.get_tensor(self._out[2]["index"]).flatten()

        for cls, score in zip(classes, scores):
            if int(round(float(cls))) == self._person_idx and float(score) >= self._confidence:
                logger.debug("Personne détectée (score=%.2f)", score)
                return True
        return False
