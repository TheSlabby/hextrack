"""WinPredictionNet: n -> 64 -> 32 -> 16 -> 1, ReLU, dropout 0.2, raw logits (legacy port).

Same architecture as ``hextrack-ai/model.py``: three ReLU hidden layers with dropout after
the first two, and a linear output. The network returns logits; training uses
``BCEWithLogitsLoss`` and scoring applies the sigmoid. Layers live in one ``nn.Sequential``
(state_dict keys ``net.<i>.weight``), so legacy ``layer_1``-style checkpoints do not load,
which is intended: the feature set changed and retraining is mandatory.
"""

from __future__ import annotations

import torch
from torch import nn

HIDDEN_SIZES: tuple[int, int, int] = (64, 32, 16)
DEFAULT_DROPOUT = 0.2


class WinPredictionNet(nn.Module):
    def __init__(self, n_features: int, dropout: float = DEFAULT_DROPOUT) -> None:
        super().__init__()
        if n_features < 1:
            raise ValueError("n_features must be positive")
        if not 0.0 <= dropout < 1.0:
            raise ValueError("dropout must be in [0, 1)")
        self.n_features = n_features
        h1, h2, h3 = HIDDEN_SIZES
        self.net = nn.Sequential(
            nn.Linear(n_features, h1),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(h1, h2),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(h2, h3),
            nn.ReLU(),
            nn.Linear(h3, 1),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """Returns logits of shape (batch, 1)."""
        return self.net(x)


def describe_architecture(n_features: int, dropout: float = DEFAULT_DROPOUT) -> str:
    """Human-readable architecture string stored in meta.json."""
    sizes = " -> ".join(str(s) for s in (n_features, *HIDDEN_SIZES, 1))
    return f"WinPredictionNet({sizes}, ReLU, dropout={dropout})"
