import numpy as np

# Simple per-preset linear bandit with Thompson Sampling using ridge posterior.


class LinTS:
    def __init__(self, d: int, l2: float = 1.0):
        self.d = d
        self.l2 = l2
        self.A = None  # (K, d, d)
        self.b = None  # (K, d)
        self.K = 0

    def ensure_K(self, K: int):
        if self.K == K and self.A is not None:
            return
        self.K = K
        self.A = np.array([self.l2 * np.eye(self.d) for _ in range(K)])
        self.b = np.zeros((K, self.d))

    def choose(self, X: np.ndarray) -> int:
        # X shape (K, d) context per arm (often same x repeated).
        K, d = X.shape
        self.ensure_K(K)
        idx = []
        for k in range(K):
            Ainv = np.linalg.inv(self.A[k])
            mu = Ainv @ self.b[k]
            w = np.random.multivariate_normal(mu, Ainv)
            idx.append(w @ X[k])
        return int(np.argmax(idx))

    def update(self, k: int, x: np.ndarray, reward: float):
        self.A[k] += np.outer(x, x)
        self.b[k] += reward * x
