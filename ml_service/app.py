# ml_service/app.py  — M11: Auto-retrain & Blue/Green + M13: H2 Hierarchical HMM
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
from fastapi import FastAPI, HTTPException

# HMM + Policy
from hmmlearn.hmm import GaussianHMM
from joblib import dump, load
from pydantic import BaseModel, Field
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.preprocessing import StandardScaler

MODEL_DIR = Path(__file__).parent / "model_store"
MODEL_DIR.mkdir(parents=True, exist_ok=True)
HMM_PATH = MODEL_DIR / "hmm_v1.joblib"
SCL_PATH = MODEL_DIR / "scaler_v1.joblib"
POL_PATH = MODEL_DIR / "policy_v1.joblib"

# M11: versioning + blue/green serving
MODELS: Dict[str, dict] = {}  # tag -> {"hmm":..., "scaler":..., "policy":...}
ACTIVE_TAG_PATH = MODEL_DIR / "active_tag.txt"
ACTIVE_H2_TAG_PATH = MODEL_DIR / "active_h2_tag.txt"

# M13: H2 hierarchical models
H2_MODELS: Dict[str, dict] = (
    {}
)  # tag -> {"macro": hmm, "micro": {macro_state:int -> hmm}, "scaler_macro":..., "scaler_micro":..., "policy":...}


def _timestamp_tag(prefix="v"):
    return f"{prefix}-{datetime.utcnow().strftime('%Y%m%dT%H%M%S')}"


def _tag_paths(tag: str):
    base = MODEL_DIR / tag
    return {
        "hmm": base.with_suffix(".hmm.joblib"),
        "scaler": base.with_suffix(".scaler.joblib"),
        "policy": base.with_suffix(".policy.joblib"),
    }


def _save_models(tag: str, hmm, scaler, policy):
    paths = _tag_paths(tag)
    dump(hmm, paths["hmm"])
    dump(scaler, paths["scaler"])
    if policy is not None:
        dump(policy, paths["policy"])
    # Update active tag file to point to this tag (for persistence)
    ACTIVE_TAG_PATH.write_text(
        ACTIVE_TAG_PATH.read_text().strip() if ACTIVE_TAG_PATH.exists() else tag
    )


def _load_tag(tag: str):
    paths = _tag_paths(tag)
    if not paths["hmm"].exists() or not paths["scaler"].exists():
        raise FileNotFoundError(f"Tag {tag} incomplete")
    m = {
        "hmm": load(paths["hmm"]),
        "scaler": load(paths["scaler"]),
        "policy": load(paths["policy"]) if paths["policy"].exists() else None,
    }
    MODELS[tag] = m
    return m


def _active_tag():
    return ACTIVE_TAG_PATH.read_text().strip() if ACTIVE_TAG_PATH.exists() else None


def _set_active_tag(tag: str):
    if tag not in MODELS:
        _load_tag(tag)
    ACTIVE_TAG_PATH.write_text(tag)


def _active_h2_tag() -> Optional[str]:
    return ACTIVE_H2_TAG_PATH.read_text().strip() if ACTIVE_H2_TAG_PATH.exists() else None


def _set_active_h2_tag(tag: str):
    ACTIVE_H2_TAG_PATH.write_text(tag)


app = FastAPI()
hmm: Optional[GaussianHMM] = None
scaler: Optional[StandardScaler] = None
policy: Optional[GradientBoostingClassifier] = None

# ---------- Schemas ----------


class TrainRequest(BaseModel):
    symbol: str = "BTCUSDT"
    # A list of sequences; each sequence is a list of feature vectors
    feature_sequences: List[List[List[float]]]
    # Optional supervised labels aligned with each vector across all sequences
    # For simplicity: a flattened label vector (0=HOLD, 1=BUY, 2=SELL)
    labels: Optional[List[int]] = None
    k_min: int = 3
    k_max: int = 5
    random_state: int = 7
    max_iter: int = 200


class PartialFitRequest(BaseModel):
    feature_sequences: List[List[List[float]]]
    max_iter: int = 25  # short update
    random_state: int = 7


class InferRequest(BaseModel):
    symbol: str
    features: List[float] = Field(..., description="Single feature vector")
    ts: int
    tag: Optional[str] = None  # NEW: candidate tag for canary


class InferResponse(BaseModel):
    state: int
    probs: List[float]
    confidence: float
    action: dict


# ---------- Utils ----------


def _concat_sequences(seqs: List[np.ndarray]) -> Tuple[np.ndarray, np.ndarray]:
    """Concatenate variable-length sequences for hmmlearn fit."""
    lengths = np.array([len(s) for s in seqs], dtype=int)
    X = np.vstack(seqs) if len(seqs) else np.empty((0, 0))
    return X, lengths


def _bic(hmm: GaussianHMM, X: np.ndarray, lengths: np.ndarray) -> float:
    # BIC = -2 * logL + p * logN; p ~ free parameters
    logL = hmm.score(X, lengths)
    n_states = hmm.n_components
    n_feats = X.shape[1]
    # params: startprob(n-1) + trans(n*(n-1)) + means(n*f) + covars(n*f)
    p = (n_states - 1) + n_states * (n_states - 1) + n_states * n_feats + n_states * n_feats
    return -2.0 * logL + p * np.log(len(X))


def _standardize_fit(seqs: List[np.ndarray]) -> Tuple[List[np.ndarray], StandardScaler]:
    X, lengths = _concat_sequences(seqs)
    scaler = StandardScaler()
    scaler.fit(X)
    seqs_std = [scaler.transform(s) for s in seqs]
    return seqs_std, scaler


def _standardize_apply(seqs: List[np.ndarray], scaler: StandardScaler) -> List[np.ndarray]:
    return [scaler.transform(s) for s in seqs]


def _decide_from_policy(state: int, conf: float, x: np.ndarray) -> dict:
    """Map model outputs to an action. If policy exists & trained, use it; else a rule."""
    global policy
    if policy is not None and hasattr(policy, "classes_"):
        # Input = [state_one_hot, features...]
        one_hot = np.zeros((1, policy.n_features_in_ - x.shape[1]))
        if state < one_hot.shape[1]:
            one_hot[0, state] = 1.0
        Xp = np.hstack([one_hot, x.reshape(1, -1)])
        pred: int = int(policy.predict(Xp)[0])
        if pred == 1:
            return {"side": "BUY", "qty": 0.001, "limit_px": None}
        if pred == 2:
            return {"side": "SELL", "qty": 0.001, "limit_px": None}
        return {"side": "HOLD", "qty": 0, "limit_px": None}
    # Fallback heuristic: only act if confident and in specific states
    if conf >= 0.65 and state in (1,):
        return {"side": "BUY", "qty": 0.001, "limit_px": None}
    return {"side": "HOLD", "qty": 0, "limit_px": None}


def _load_models():
    global hmm, scaler, policy
    hmm = load(HMM_PATH) if HMM_PATH.exists() else None
    scaler = load(SCL_PATH) if SCL_PATH.exists() else None
    policy = load(POL_PATH) if POL_PATH.exists() else None


# --- new imports/schemas ---
class H2TrainRequest(BaseModel):
    symbol: str
    macro_sequences: List[List[float]]  # list of macro feature vectors (slow cadence)
    micro_sequences_by_macro: Dict[
        int, List[List[float]]
    ]  # per macro label -> micro feature vectors
    n_macro: int = 3
    n_micro: int = 4
    train_policy: bool = True


class H2InferRequest(BaseModel):
    symbol: str
    macro_feats: List[float]
    micro_feats: List[float]
    ts: int
    tag: Optional[str] = None


class H2InferResponse(BaseModel):
    macro_state: int
    micro_state: int
    confidence: float
    action: dict  # side/qty/limit_px


# --- helper taggers ---
def _h2_timestamp_tag():
    return f"h2-{datetime.utcnow().strftime('%Y%m%dT%H%M%SS')}"


def _h2_tag_paths(tag: str):
    base = MODEL_DIR / tag
    return {
        "macro": base.with_suffix(".macro.joblib"),
        "microdict": base.with_suffix(".microdict.joblib"),
        "scalermacro": base.with_suffix(".scalermacro.joblib"),
        "scalermicro": base.with_suffix(".scalermicro.joblib"),
        "policy": base.with_suffix(".policy.joblib"),
    }


def _stabilize_transitions(hmm: GaussianHMM) -> None:
    """Ensure transition/start probabilities form valid distributions."""
    tm = hmm.transmat_.copy()
    n = hmm.n_components
    for i in range(n):
        total = float(tm[i].sum())
        if total <= 0:
            tm[i] = np.full(n, 1.0 / n, dtype=tm.dtype)
        else:
            tm[i] = tm[i] / total
    hmm.transmat_ = tm
    start = hmm.startprob_
    total = start.sum()
    if total <= 0:
        hmm.startprob_ = np.full_like(start, 1.0 / hmm.n_components)
    else:
        hmm.startprob_ = start / total


# ---------- Lifecyle ----------


@app.on_event("startup")
def startup():
    import logging

    _load_models()
    if hmm is None or scaler is None:
        logging.getLogger(__name__).info("No saved models found, using placeholders")
    else:
        logging.getLogger(__name__).info("Models loaded OK")


@app.get("/health")
def health():
    return {"ok": True, "hmm": hmm is not None, "policy": policy is not None}


# ---------- New M11 endpoints ----------
@app.get("/models")
def list_models():
    active = _active_tag()
    return {"active": active, "loaded": list(MODELS.keys())}


class PromoteReq(BaseModel):
    tag: str


@app.post("/promote")
def promote(req: PromoteReq):
    if req.tag not in MODELS:
        _load_tag(req.tag)
    _set_active_tag(req.tag)
    return {"ok": True, "active": req.tag}


class LoadReq(BaseModel):
    tag: str


@app.post("/load")
def load_tag(req: LoadReq):
    _load_tag(req.tag)
    return {"ok": True, "loaded": list(MODELS.keys())}


# ---------- Train ----------


@app.post("/train")
def train(req: TrainRequest):
    global hmm, scaler, policy

    # Convert to arrays
    seqs = [np.array(s, dtype=np.float32) for s in req.feature_sequences]
    if not seqs or any(len(s) == 0 for s in seqs):
        raise HTTPException(400, "Empty sequences")

    # Standardize per model (crypto is 24/7; training-time scaler is fine)
    seqs_std, scaler_fit = _standardize_fit(seqs)
    X, lengths = _concat_sequences(seqs_std)

    # Select K by BIC
    best = None
    best_bic = np.inf
    for k in range(req.k_min, req.k_max + 1):
        m = GaussianHMM(
            n_components=k,
            covariance_type="diag",
            n_iter=req.max_iter,
            random_state=req.random_state,
            verbose=False,
        )
        m.fit(X, lengths)
        bic = _bic(m, X, lengths)
        if bic < best_bic:
            best_bic, best = bic, m

    if best is None:
        raise HTTPException(500, "HMM training failed")

    # Optional policy training
    pol = None
    if req.labels:
        y = np.array(req.labels, dtype=int)
        # Flatten sequences to align labels
        if len(y) != len(X):
            raise HTTPException(400, "labels length must equal total frames across all sequences")
        # Features for policy = [one-hot(state), standardized features]
        states = best.predict(X, lengths)
        n_states = best.n_components
        one_hot = np.eye(n_states, dtype=np.float32)[states]
        Xp = np.hstack([one_hot, X])
        pol = GradientBoostingClassifier(random_state=req.random_state)
        pol.fit(Xp, y)

    # M11: save with timestamp tag
    tag = _timestamp_tag()
    _save_models(tag, best, scaler_fit, pol)
    MODELS[tag] = {"hmm": best, "scaler": scaler_fit, "policy": pol}
    # if no active, activate first one
    if _active_tag() is None:
        _set_active_tag(tag)

    # Update live refs (backward compat)
    hmm, scaler, policy = best, scaler_fit, pol
    return {
        "ok": True,
        "tag": tag,
        "n_components": best.n_components,
        "bic": float(best_bic),
        "policy_trained": pol is not None,
    }


# ---------- Partial fit (light re-fit) ----------


@app.post("/partial_fit")
def partial_fit(req: PartialFitRequest):
    global hmm, scaler, policy
    if hmm is None or scaler is None:
        raise HTTPException(400, "Train first")

    seqs = [np.array(s, dtype=np.float32) for s in req.feature_sequences]
    if not seqs or any(len(s) == 0 for s in seqs):
        raise HTTPException(400, "Empty sequences")

    seqs_std = _standardize_apply(seqs, scaler)
    X, lengths = _concat_sequences(seqs_std)

    # Refit starting from current params (avoid re-init)
    upd = GaussianHMM(
        n_components=hmm.n_components,
        covariance_type=hmm.covariance_type,
        n_iter=req.max_iter,
        random_state=req.random_state,
        init_params="",  # keep current params
        params="stmcw",  # update all
    )
    # copy params
    upd.startprob_ = hmm.startprob_.copy()
    upd.transmat_ = hmm.transmat_.copy()
    upd.means_ = hmm.means_.copy()
    upd.covars_ = hmm.covars_.copy()

    upd.fit(X, lengths)

    dump(upd, HMM_PATH)
    hmm = upd
    return {"ok": True, "n_components": hmm.n_components}


# ---------- Infer ----------


@app.post("/infer", response_model=InferResponse)
def infer(req: InferRequest):
    tag = req.tag or _active_h2_tag()
    if tag is None or tag not in MODELS:
        # fallback to legacy singletons if present
        use = {"hmm": hmm, "scaler": scaler, "policy": policy}
    else:
        use = MODELS[tag]

    if use["hmm"] is None or use["scaler"] is None:
        return InferResponse(
            state=0,
            probs=[1.0],
            confidence=1.0,
            action={"side": "HOLD", "qty": 0, "limit_px": None},
        )

    x = np.array(req.features, dtype=np.float32).reshape(1, -1)
    x = use["scaler"].transform(x)

    # Use posterior from score_samples; last frame posterior ~ state probs
    logp, post = use["hmm"].score_samples(x)
    probs = post[-1].astype(float).tolist()
    state = int(np.argmax(probs))
    conf = float(max(probs))
    action = _decide_from_policy(state, conf, x[0])

    return InferResponse(state=state, probs=probs, confidence=conf, action=action)


# --- endpoint: /train_h2 ---
@app.post("/train_h2")
def train_h2(req: H2TrainRequest):
    import numpy as np
    from hmmlearn.hmm import GaussianHMM
    from sklearn.preprocessing import StandardScaler

    # Macro HMM
    X_macro = np.asarray(req.macro_sequences, dtype=np.float32)
    scaler_macro = StandardScaler().fit(X_macro)
    X_macro_s = scaler_macro.transform(X_macro)
    macro_hmm = GaussianHMM(n_components=req.n_macro, covariance_type="diag", n_iter=200).fit(
        X_macro_s
    )
    _stabilize_transitions(macro_hmm)

    # Micro HMMs per macro
    scaler_micro = StandardScaler()
    # Fit scaler on concatenated micro
    all_micro = []
    for _, seq in req.micro_sequences_by_macro.items():
        all_micro.extend(seq)
    X_micro_all = np.asarray(all_micro, dtype=np.float32)
    scaler_micro.fit(X_micro_all)

    micro_by_macro = {}
    for m_state, seq in req.micro_sequences_by_macro.items():
        X_m = scaler_micro.transform(np.asarray(seq, dtype=np.float32))
        hmm_m = GaussianHMM(n_components=req.n_micro, covariance_type="diag", n_iter=200).fit(X_m)
        _stabilize_transitions(hmm_m)
        micro_by_macro[m_state] = hmm_m

    # Optional policy head on (macro_state, micro_state, micro_feats)
    policy = None
    if req.train_policy and len(X_micro_all) > 100:
        # simple logistic/gbdt placeholder; keep consistent with your existing policy trainer
        from sklearn.linear_model import LogisticRegression

        y = np.zeros(len(X_micro_all), dtype=int)  # replace with your PnL-derived labels
        policy = LogisticRegression(max_iter=200).fit(X_micro_all, y)

    tag = _h2_timestamp_tag()
    H2_MODELS[tag] = {
        "macro": macro_hmm,
        "micro": micro_by_macro,
        "scaler_macro": scaler_macro,
        "scaler_micro": scaler_micro,
        "policy": policy,
    }
    # Persist to disk (similar to single-level)
    base = MODEL_DIR / tag
    dump(macro_hmm, base.with_suffix(".macro.joblib"))
    dump(micro_by_macro, base.with_suffix(".microdict.joblib"))
    dump(scaler_macro, base.with_suffix(".scalermacro.joblib"))
    dump(scaler_micro, base.with_suffix(".scalermicro.joblib"))
    if policy:
        dump(policy, base.with_suffix(".policy.joblib"))
    if _active_h2_tag() is None:
        _set_active_h2_tag(tag)
    return {"ok": True, "tag": tag, "n_macro": req.n_macro, "n_micro": req.n_micro}


def _try_load_h2(tag: str):
    base = MODEL_DIR / tag
    macro_p = base.with_suffix(".macro.joblib")
    microdict_p = base.with_suffix(".microdict.joblib")
    if not macro_p.exists() or not microdict_p.exists():
        return None
    mset = {
        "macro": load(macro_p),
        "micro": load(microdict_p),
        "scaler_macro": load(base.with_suffix(".scalermacro.joblib")),
        "scaler_micro": load(base.with_suffix(".scalermicro.joblib")),
        "policy": (
            load(base.with_suffix(".policy.joblib"))
            if base.with_suffix(".policy.joblib").exists()
            else None
        ),
    }
    H2_MODELS[tag] = mset
    return mset


def _decide_h2_policy(M: int, S: int, conf: float, micro_vec, policy):
    # simple gating example: macro 0=risk-off,1=neutral,2=risk-on
    macro_bias = {0: 0.5, 1: 1.0, 2: 1.5}.get(M, 1.0)
    # direction from micro state prior (reuse your STATE_EDGE or learned mapping)
    from engine.strategies.policy_hmm import STATE_EDGE

    prior = STATE_EDGE.get(S, 0.0)
    edge = prior * (2 * conf - 1.0) * macro_bias
    if edge > 0:
        side = "BUY"
    elif edge < 0:
        side = "SELL"
    else:
        side = "HOLD"
    qty = float(min(0.01, max(0.0005, abs(edge) / 10.0)))
    return {"side": side, "qty": qty, "limit_px": None}


# --- endpoint: /infer_h2 ---
@app.post("/infer_h2", response_model=H2InferResponse)
def infer_h2(req: H2InferRequest):
    import numpy as np

    tag = req.tag or _active_tag()
    mset = H2_MODELS.get(tag) or _try_load_h2(tag)
    if mset is None:
        # fallback to single-level
        ir = infer(InferRequest(symbol=req.symbol, features=req.micro_feats, ts=req.ts, tag=tag))
        return H2InferResponse(
            macro_state=0,
            micro_state=ir.state,
            confidence=ir.confidence,
            action=ir.action,
        )

    xM = np.asarray(req.macro_feats, dtype=np.float32).reshape(1, -1)
    xM = mset["scaler_macro"].transform(xM)
    _, postM = mset["macro"].score_samples(xM)
    pM = postM[-1]
    macro_state = int(np.argmax(pM))
    macro_conf = float(np.max(pM))

    xS = np.asarray(req.micro_feats, dtype=np.float32).reshape(1, -1)
    xS = mset["scaler_micro"].transform(xS)
    micro_hmm = mset["micro"].get(macro_state)
    if micro_hmm is None:
        # unseen macro -> pick any available
        micro_hmm = next(iter(mset["micro"].values()))
    _, postS = micro_hmm.score_samples(xS)
    pS = postS[-1]
    micro_state = int(np.argmax(pS))
    micro_conf = float(np.max(pS))

    conf = float(min(1.0, 0.5 * macro_conf + 0.5 * micro_conf))

    # policy gating: macro controls aggression
    action = _decide_h2_policy(macro_state, micro_state, conf, xS[0], mset["policy"])
    return H2InferResponse(
        macro_state=macro_state, micro_state=micro_state, confidence=conf, action=action
    )
