"""Ajuda dos testes: junta todos os módulos do pacote num objeto só (`bot`).

Ler `bot.algo` procura o nome no estado e em todos os módulos; trocar `bot.algo = x` troca em todos os
módulos que usam esse nome (assim dá para substituir o cliente HTTP por um Discord falso, por exemplo).
"""
import importlib
import os
import pkgutil
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

import ecopulse  # noqa: E402
import ecopulse.app  # noqa: E402,F401  (monta tudo na mesma ordem do server.py)
from ecopulse import estado  # noqa: E402

MODULOS = [importlib.import_module(m.name) for m in pkgutil.walk_packages(ecopulse.__path__, "ecopulse.")]


class _Bot:
    def __getattr__(self, nome):
        if nome in vars(estado):
            return getattr(estado, nome)
        for m in MODULOS:
            if nome in vars(m):
                return vars(m)[nome]
        raise AttributeError(nome)

    def __setattr__(self, nome, valor):
        if nome in vars(estado):
            setattr(estado, nome, valor)
            return
        achou = False
        for m in MODULOS:
            if nome in vars(m):
                setattr(m, nome, valor)
                achou = True
        if not achou:
            raise AttributeError(nome)


bot = _Bot()
