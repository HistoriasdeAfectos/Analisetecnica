"""Perfis de desporto.

Importar este pacote regista todos os perfis. Acrescentar um desporto é
acrescentar um módulo aqui — o pipeline em `core/` não muda.
"""

from . import arco, ciclismo, corrida, lancamentos, natacao  # noqa: F401

__all__ = ["ciclismo", "corrida", "arco", "natacao", "lancamentos"]
