"""Análise técnica corporal a partir de vídeo e fotografia, multidesporto."""

from .core import pipeline, profile, reporting  # noqa: F401

__version__ = "0.1.0"


def load_profiles() -> None:
    """Regista todos os perfis de desporto disponíveis."""
    from . import sports  # noqa: F401


__all__ = ["pipeline", "profile", "reporting", "load_profiles", "__version__"]
