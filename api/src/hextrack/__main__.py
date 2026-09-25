"""``python -m hextrack``: the production units run the CLI this way, from a venv that holds
only the dependencies (the package itself comes from ``PYTHONPATH``)."""

from hextrack.cli import app

app()
