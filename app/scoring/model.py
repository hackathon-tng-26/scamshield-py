import os
import pickle
from dataclasses import dataclass

from app.config import settings
from app.logger import get_logger

log = get_logger(__name__)

_CLASS_TO_SCORE: dict[int, float] = {0: 0.0, 1: 50.0, 2: 100.0}


@dataclass
class ModelBundle:
    estimator: object
    feature_order: list[str]


_loaded: ModelBundle | None = None
_tried_load: bool = False


def get_model() -> ModelBundle | None:
    global _loaded, _tried_load
    if _tried_load:
        return _loaded
    _tried_load = True

    path = settings.model_path
    if not os.path.exists(path):
        log.info("scorer.model.absent", path=path, fallback="rules-only")
        return None

    try:
        with open(path, "rb") as f:
            _loaded = pickle.load(f)
        log.info("scorer.model.loaded", path=path)
    except Exception as exc:
        log.error("scorer.model.load_failed", path=path, error=str(exc), fallback="rules-only")
        _loaded = None

    return _loaded


def score_from_model(bundle: ModelBundle, features: dict) -> int | None:
    try:
        vector = [[float(features.get(f, 0.0)) for f in bundle.feature_order]]
        probs = bundle.estimator.predict_proba(vector)[0]
        classes: list[int] = list(bundle.estimator.classes_)
        weighted = sum(probs[i] * _CLASS_TO_SCORE.get(cls, 50.0) for i, cls in enumerate(classes))
        return int(round(weighted))
    except Exception as exc:
        log.warning("scorer.model.predict_failed", error=str(exc)[:100])
        return None
