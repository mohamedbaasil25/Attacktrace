"""Next-step forecasters: GDN-style graph attention (primary) and an MLP (fallback).

Both map a window of normalized node values (B, W, N) to a prediction of the next sample
(B, N) and share one interface. `residual=True` predicts `last value + delta` instead of the
absolute value (which hides persistent offsets).
"""

from dataclasses import dataclass

import numpy as np
import torch
from numpy.typing import NDArray
from torch import nn
from torch.nn.functional import leaky_relu, mse_loss

F64 = NDArray[np.float64]

WINDOW = 10  # samples (5 s at 2 Hz)


@dataclass(frozen=True)
class Norm:
    mu: F64
    sd: F64

    @classmethod
    def fit(cls, x: F64) -> "Norm":
        return cls(x.mean(axis=0), np.maximum(x.std(axis=0), 1e-3))

    def apply(self, x: F64) -> F64:
        return (x - self.mu) / self.sd


def make_windows(xn: F64, w: int = WINDOW) -> tuple[F64, F64]:
    """(T, N) → windows (T-w, w, N) and the sample that follows each, (T-w, N)."""
    idx = np.arange(w)[None, :] + np.arange(len(xn) - w)[:, None]
    return xn[idx], xn[w:]


class GDN(nn.Module):
    """Node embeddings + masked graph attention over each node's parents (and itself)."""

    def __init__(
        self, n: int, w: int, adj: NDArray[np.bool_], d: int = 16, residual: bool = False
    ) -> None:
        super().__init__()
        self.residual = residual
        self.emb = nn.Parameter(torch.randn(n, d) * 0.1)
        self.inp = nn.Linear(w, d)
        self.a_dst = nn.Linear(2 * d, 1)
        self.a_src = nn.Linear(2 * d, 1)
        self.head = nn.Sequential(nn.Linear(d, d), nn.ReLU(), nn.Linear(d, 1))
        self.register_buffer("mask", torch.from_numpy(adj.copy()))
        self.mask: torch.Tensor

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        h = self.inp(x.transpose(1, 2))  # (B, N, d)
        emb = self.emb.unsqueeze(0).expand(h.shape[0], -1, -1)
        g = torch.cat([emb, h], dim=-1)
        e = leaky_relu(self.a_dst(g) + self.a_src(g).transpose(1, 2), 0.2)  # (B, N, N)
        att = torch.softmax(e.masked_fill(~self.mask, float("-inf")), dim=-1)
        z = torch.relu(att @ h)
        out = self.head(emb * z).squeeze(-1)
        res: torch.Tensor = x[:, -1, :] + out if self.residual else out
        return res


class MLPForecaster(nn.Module):
    def __init__(self, n: int, w: int, hidden: int = 128, residual: bool = False) -> None:
        super().__init__()
        self.residual = residual
        self.net = nn.Sequential(
            nn.Flatten(),
            nn.Linear(w * n, hidden),
            nn.ReLU(),
            nn.Linear(hidden, hidden),
            nn.ReLU(),
            nn.Linear(hidden, n),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        out: torch.Tensor = self.net(x)
        res: torch.Tensor = x[:, -1, :] + out if self.residual else out
        return res


def build_model(
    kind: str, n: int, w: int, adj: NDArray[np.bool_], residual: bool = False
) -> nn.Module:
    if kind == "gdn":
        return GDN(n, w, adj, residual=residual)
    if kind == "mlp":
        return MLPForecaster(n, w, residual=residual)
    raise ValueError(f"unknown forecaster {kind!r}")


def predict(model: nn.Module, windows: F64) -> F64:
    model.eval()
    with torch.no_grad():
        out = model(torch.as_tensor(windows, dtype=torch.float32))
    return np.asarray(out.numpy(), dtype=np.float64)


def train(
    model: nn.Module,
    train_xy: tuple[F64, F64],
    val_xy: tuple[F64, F64],
    epochs: int = 40,
    batch: int = 256,
    lr: float = 2e-3,
    seed: int = 0,
) -> float:
    """Fit on clean data; restores the best-validation weights. Returns the best val MSE."""
    torch.manual_seed(seed)
    xt = torch.as_tensor(train_xy[0], dtype=torch.float32)
    yt = torch.as_tensor(train_xy[1], dtype=torch.float32)
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    best, best_state = float("inf"), {k: v.clone() for k, v in model.state_dict().items()}
    for _ in range(epochs):
        model.train()
        perm = torch.randperm(len(xt))
        for i in range(0, len(xt), batch):
            b = perm[i : i + batch]
            opt.zero_grad()
            loss: torch.Tensor = mse_loss(model(xt[b]), yt[b])
            loss.backward()  # type: ignore[no-untyped-call]
            opt.step()
        val = float(np.mean((predict(model, val_xy[0]) - val_xy[1]) ** 2))
        if val < best:
            best, best_state = val, {k: v.clone() for k, v in model.state_dict().items()}
    model.load_state_dict(best_state)
    return best
