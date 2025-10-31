import threading
from pathlib import Path
from typing import Dict, Any, Optional
import numpy as np
from joblib import load
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from loguru import logger
from .config import settings
from . import model_store

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
    if _MODEL is None:
        logger.warning("No active model yet (waiting for first promotion)...")
    else:
        logger.info(f"Loaded active model (states={_META.get('n_states')}, metric={_META.get('metric_value')})")


class _BumpHandler(FileSystemEventHandler):
    def on_modified(self, event):
        # Reload when version.txt changes or metadata updates
        if event.is_directory:
            return
        if event.src_path.endswith("version.txt") or event.src_path.endswith("metadata.json"):
            logger.info("Detected model version bump; reloading...")
            _load_active_model()


def start_watchdog():
    global _OBSERVER
    # Ensure there is a current folder to watch; if not, just load once and bail
    model_store._registry().mkdir(parents=True, exist_ok=True)
    _load_active_model()

    cur = Path(settings.CURRENT_SYMLINK)
    parent = cur if cur.is_dir() else cur.parent
    parent.mkdir(parents=True, exist_ok=True)

    event_handler = _BumpHandler()
    observer = Observer()
    # Watch the symlink target dir (if missing, still watch parent)
    watch_dir = cur.resolve() if cur.exists() else parent.resolve()
    observer.schedule(event_handler, path=str(watch_dir), recursive=False)
    observer.daemon = True
    observer.start()
    _OBSERVER = observer
    logger.info(f"Started model watcher on {watch_dir}")


def predict_proba(logret_series) -> Dict[str, Any]:
    with _MODEL_LOCK:
        model, scaler, meta = _MODEL, _SCALER, _META
    if model is None:
        raise RuntimeError("No active model yet. Train and promote one first.")
    X = np.asarray(logret_series, dtype=float).reshape(-1, 1)
    Xs = scaler.transform(X)
    post = model.predict_proba(Xs[-1:])[0].tolist()
    return {"regime_proba": post, "model_meta": meta}
