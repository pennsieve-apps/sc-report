"""The report's own figure: cell-type composition per sample, grouped by condition (PNG, 150 dpi)."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

DPI = 150
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948", "#1c9fb5",
          "#a0522d", "#7a7a00", "#c43c8a"]
OTHER = "#b9b8b2"
TEXT, TEXT2 = "#0b0b0b", "#52514e"


def composition_bars(frac: pd.DataFrame, cond: dict[str, str], title: str, path: Path, top: int = 11) -> Path:
    """Stacked bars, one per sample (sorted by condition), the `top` largest types coloured, the rest as 'other'."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    order = frac.mean().sort_values(ascending=False).index
    keep = list(order[:top])
    data = frac[keep].copy()
    if len(order) > top:
        data["other"] = frac[list(order[top:])].sum(axis=1)
    samples = sorted(data.index, key=lambda s: (cond.get(s, ""), s))
    data = data.loc[samples]
    fig, ax = plt.subplots(figsize=(max(5.0, 0.38 * len(samples) + 3.2), 4.2))
    bottom = pd.Series(0.0, index=samples)
    for i, c in enumerate(data.columns):
        ax.bar(range(len(samples)), data[c] * 100, bottom=bottom * 100, width=0.82, linewidth=0,
               color=OTHER if c == "other" else SERIES[i % len(SERIES)], label=str(c))
        bottom += data[c]
    labels = [f"{s} ({cond[s]})" if s in cond else s for s in samples]
    ax.set_xticks(range(len(samples)), labels, rotation=60, ha="right", fontsize=7)
    ax.set_ylabel("% of the sample's cells", color=TEXT2)
    ax.set_ylim(0, 100)
    ax.spines[["top", "right"]].set_visible(False)
    ax.set_title(title, fontsize=10, color=TEXT)
    ax.legend(frameon=False, fontsize=7, bbox_to_anchor=(1.01, 1), loc="upper left")
    fig.tight_layout()
    fig.savefig(path, dpi=DPI)
    plt.close(fig)
    return path
