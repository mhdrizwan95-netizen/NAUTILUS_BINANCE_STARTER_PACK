
import threading
from pathlib import Path
from typing import Dict, Any, Optional
import numpy as np
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from joblib import load
from loguru import logger
from . import model_store
from .config import settings

_MODEL_LOCK = threading.RLock()
_MODEL = None
_SCALER = None
_META: Dict[str, Any] = {}
_OBSERVER: Optional[Observer] = None

def _load_active_model():
    global _MODEL, _SCALER, _META
    model, scaler, meta = model_store.load_current()
    with _MODEL_LOCK:
        _MODEL, _SCALER, _META = model, scaler, meta
    if model is None:
        logger.warning("No active model yet")
    else:
        logger.info(f"Loaded active model (states={_META.get('n_states')}, metric={_META.get('metric_value')})")

class _Bump(FileSystemEventHandler):
    def on_modified(self, event):
        if event.is_directory: return
        if event.src_path.endswith("version.txt") or event.src_path.endswith("metadata.json"):
            logger.info("Detected model update; reloading")
            _load_active_model()

def start_watchdog():
    cur = Path(settings.CURRENT_SYMLINK)
    parent = cur if cur.is_dir() else cur.parent
    parent.mkdir(parents=True, exist_ok=True)
    event_handler = _Bump()
    obs = Observer()
    watch_dir = cur.resolve() if cur.exists() else parent.resolve()
    obs.schedule(event_handler, path=str(watch_dir), recursive=False)
    obs.daemon = True
    obs.start()
    _load_active_model()
    logger.info(f"Started watcher on {watch_dir}")

def predict_proba(logret_series):
    with _MODEL_LOCK:
        model, scaler, meta = _MODEL, _SCALER, _META
    if model is None:
        raise RuntimeError("No active model. Train first.")
    import numpy as np
    X = np.asarray(logret_series, dtype=float).reshape(-1,1)
    Xs = scaler.transform(X)
    post = model.predict_proba(Xs[-1:])[0].tolist()
    return {"regime_proba": post, "model_meta": meta}
