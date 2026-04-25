import os
import pickle
from dataclasses import dataclass

from app.config import settings
from app.logger import get_logger

log = get_logger(__name__)


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
