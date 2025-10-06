#!/usr/bin/env python3
"""
M15 Calibration — Headless Policy Diagnostics
---------------------------------------------
Reads data/processed/feedback_log.csv and produces:
- reward_heatmap.png
- policy_boundary.png
- rolling_winrate.png
Run:
  python ops/calibrate_policy.py
"""
import numpy as np, pandas as pd, matplotlib.pyplot as plt
from collections import defaultdict
from pathlib import Path

CAL_DIR = Path("data/processed/calibration")
CAL_DIR.mkdir(parents=True, exist_ok=True)
LOG_PATH = Path("data/processed/feedback_log.csv")
if not LOG_PATH.exists():
    raise FileNotFoundError(f"Missing feedback log: {LOG_PATH}. Run backtest/paper to create it.")

df = pd.read_csv(LOG_PATH).fillna("")
df["macro_state"] = df["macro_state"].astype(int)
df["micro_state"] = df["micro_state"].astype(int)
df["side"] = df["side"].astype(str).str.upper()
df["delta_pnl"] = df["delta_pnl"].astype(float)

# --- Reward convergence (EMA per (macro,micro)) ---
class EMATable:
    def __init__(self, alpha=0.02): self.alpha=float(alpha); self.avg=defaultdict(float)
    def update(self, key, reward: float): a=self.alpha; self.avg[key]=(1-a)*self.avg[key]+a*reward
    def get(self,key,default=0.0): return self.avg.get(key,default)

R = EMATable(alpha=0.02)
for _, r in df.iterrows(): R.update((r.macro_state, r.micro_state), r.delta_pnl)

rows = [{"macro": M, "micro": S, "reward": v} for (M,S),v in R.avg.items()]
R_df = pd.DataFrame(rows)

plt.figure(figsize=(8,4))
plt.bar(np.arange(len(R_df)), R_df["reward"])
plt.xticks(np.arange(len(R_df)), [f"({m},{s})" for m,s in zip(R_df["macro"],R_df["micro"])])
plt.title("EMA Reward per (macro,micro) state")
plt.ylabel("ΔPnL")
plt.tight_layout(); plt.savefig(CAL_DIR/"reward_heatmap.png"); plt.close()

# --- TinyMLP probe boundary drift (simple features: conf + macro/micro one-hots) ---
class TinyMLP:
    def __init__(self,d_in:int,d_hidden:int=16,seed:int=7):
        rng=np.random.default_rng(seed)
        self.W1=rng.normal(0,0.05,(d_in,d_hidden)); self.b1=np.zeros(d_hidden)
        self.W2=rng.normal(0,0.05,(d_hidden,1));    self.b2=np.zeros(1)
    def _fwd(self,x):
        h=np.tanh(x@self.W1+self.b1); z=h@self.W2+self.b2; y=1/(1+np.exp(-z)); return h,y
    def step(self,x,y_true,lr=1e-4,clip=0.05):
        h,y=self._fwd(x); dz=(y-y_true.reshape(-1,1))
        dW2=h.T@dz/len(x); db2=dz.mean(0)
        dh=dz@self.W2.T*(1-h**2); dW1=x.T@dh/len(x); db1=dh.mean(0)
        for g in (dW1,db1,dW2,db2): np.clip(g,-clip,clip,out=g)
        self.W1-=lr*dW1; self.b1-=lr*db1; self.W2-=lr*dW2; self.b2-=lr*db2
    def predict_proba(self,x): _,y=self._fwd(x); return y.ravel()

def feats(row):
    conf=float(row.get("conf",0.5)); m=int(row["macro_state"]); s=int(row["micro_state"])
    mvec=np.zeros(4); svec=np.zeros(8); mvec[min(m,3)]=1; svec[min(s,7)]=1
    return np.concatenate([[conf],mvec,svec])

X=np.stack([feats(r) for _,r in df.iterrows()])
y=np.array([(1 if (r.side=="BUY" and r.delta_pnl>0) else 0) for _,r in df.iterrows()],dtype=float)
mlp=TinyMLP(d_in=X.shape[1],d_hidden=16)

probe_log=[]
for i in range(0,len(X),100):
    j=min(i+64,len(X)); mlp.step(X[i:j], y[i:j])
    probe=float(mlp.predict_proba(X[i:j].mean(0)[None,:])[0]); probe_log.append(probe)

plt.figure(figsize=(8,4))
plt.plot(probe_log)
plt.title("TinyMLP probe p(BUY) over time"); plt.xlabel("batch index"); plt.ylabel("p(BUY)")
plt.tight_layout(); plt.savefig(CAL_DIR/"policy_boundary.png"); plt.close()

# --- Rolling win-rate (on executed BUY/SELL only) ---
df_side=df[df.side.isin(["BUY","SELL"])].copy(); df_side["win"]=df_side["delta_pnl"]>0
win=pd.Series(df_side["win"].astype(int)).rolling(100,min_periods=25).mean()

plt.figure(figsize=(8,3))
plt.plot(win.values)
plt.title("Rolling win-rate (100 trades)"); plt.ylim(0,1); plt.xlabel("trade index"); plt.ylabel("win-rate")
plt.tight_layout(); plt.savefig(CAL_DIR/"rolling_winrate.png"); plt.close()

print("Calibration complete → PNGs in", CAL_DIR.resolve())
