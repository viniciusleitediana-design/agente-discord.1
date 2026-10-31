"""Ponto de entrada do bot. No Render, o comando de início é `python server.py`.

O código fica no pacote `ecopulse/` (veja a estrutura no README).
"""
from ecopulse.app import app, main  # noqa: F401  (app também serve para `uvicorn server:app`)

if __name__ == "__main__":
    main()
