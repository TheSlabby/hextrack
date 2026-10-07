"""The Hex Score networks.

:class:`HexImpactNet` (current): one player's stat line, role and champion -> their *impact*,
in logits of their team's win chance. It is trained on whole games, where the ten impacts add
up (own team minus enemy team) to the log-odds that the team won, so each player is credited
only for what their own line adds; see :mod:`hextrack.hextrack_ai.train`.

:class:`WinPredictionNet` (legacy, ``kind = "win_probability"`` models): n -> 64 -> 32 -> 16 -> 1,
ReLU, dropout 0.2, raw logits of "this stat line is on the winning team". Kept so older
model versions still load and can be re-activated.

WinPredictionNet details:

Same architecture as ``hextrack-ai/model.py``: three ReLU hidden layers with dropout after
the first two, and a linear output. The network returns logits; training uses
``BCEWithLogitsLoss`` and scoring applies the sigmoid. Layers live in one ``nn.Sequential``
(state_dict keys ``net.<i>.weight``), so legacy ``layer_1``-style checkpoints do not load,
which is intended: the feature set changed and retraining is mandatory.
"""

from __future__ import annotations

import torch
from torch import nn
from torch.nn import functional as F

from hextrack.hextrack_ai.features import ROLE_SLOTS

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


#: HexImpactNet hidden layers (stats + role one-hot + champion embedding in).
IMPACT_HIDDEN: tuple[int, ...] = (64, 32, 16)
IMPACT_DROPOUT = 0.1
CHAMPION_DIM = 8


class HexImpactNet(nn.Module):
    """``(scaled stats, role slot, champion slot) -> impact`` (logits, shape ``(batch,)``).

    ``role`` is a :func:`~hextrack.hextrack_ai.features.role_slot` (the last slot means
    "unknown"), fed as a one-hot. ``champion`` indexes a learned embedding; slot 0 is
    "a champion the model never saw". ``n_champions = 0`` builds the network without one.
    Leading batch dimensions are free: ``(games, 10, n_features)`` works too.
    """

    def __init__(
        self,
        n_features: int,
        *,
        n_champions: int = 0,
        hidden: tuple[int, ...] = IMPACT_HIDDEN,
        dropout: float = IMPACT_DROPOUT,
        champion_dim: int = CHAMPION_DIM,
    ) -> None:
        super().__init__()
        if n_features < 1:
            raise ValueError("n_features must be positive")
        if not 0.0 <= dropout < 1.0:
            raise ValueError("dropout must be in [0, 1)")
        self.n_features = n_features
        self.n_champions = n_champions
        self.champion = nn.Embedding(n_champions + 1, champion_dim) if n_champions else None
        layers: list[nn.Module] = []
        width = n_features + ROLE_SLOTS + (champion_dim if n_champions else 0)
        for i, size in enumerate(hidden):
            layers += [nn.Linear(width, size), nn.ReLU()]
            if i < len(hidden) - 1:
                layers.append(nn.Dropout(dropout))
            width = size
        layers.append(nn.Linear(width, 1))
        self.net = nn.Sequential(*layers)

    def forward(
        self, x: torch.Tensor, role: torch.Tensor, champion: torch.Tensor | None = None
    ) -> torch.Tensor:
        parts = [x, F.one_hot(role, ROLE_SLOTS).to(x.dtype)]
        if self.champion is not None:
            if champion is None:
                champion = torch.zeros_like(role)
            parts.append(self.champion(champion))
        return self.net(torch.cat(parts, dim=-1)).squeeze(-1)


def describe_impact_architecture(
    n_features: int, *, n_champions: int, dropout: float = IMPACT_DROPOUT
) -> str:
    extra = f" + champion[{n_champions}x{CHAMPION_DIM}]" if n_champions else ""
    sizes = " -> ".join(str(s) for s in (*IMPACT_HIDDEN, 1))
    return (
        f"HexImpactNet({n_features} stats + role[{ROLE_SLOTS}]{extra} -> {sizes}, "
        f"ReLU, dropout={dropout})"
    )
