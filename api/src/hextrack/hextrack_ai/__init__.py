"""AI Score: P(win | participant stat line) from a small MLP.

Each trained model lives in its own version directory, ``{settings.model_dir}/{version}/``,
holding model.pth, scaler.pkl, meta.json and train_curve.png. ``{settings.model_dir}/ACTIVE``
names the active version (kept in sync with ``ai_models.is_active`` by ``registry.activate``).
"""
