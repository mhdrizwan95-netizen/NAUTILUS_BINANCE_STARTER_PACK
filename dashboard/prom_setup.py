import os, pathlib
from prometheus_client import CollectorRegistry, multiprocess, REGISTRY


def get_registry():
    mp = os.getenv("PROMETHEUS_MULTIPROC_DIR")
    if mp:
        pathlib.Path(mp).mkdir(parents=True, exist_ok=True)
        reg = CollectorRegistry()
        multiprocess.MultiProcessCollector(reg)
        return reg
    return REGISTRY
