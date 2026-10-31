"""Roda todos os testes (cada arquivo num processo separado) e mostra o resumo.

Uso: python tests/rodar_testes.py
Os testes usam um Discord falso (fake_discord*.py): nada é enviado para o Discord de verdade.
"""
import glob
import os
import re
import subprocess
import sys
import time

PASTA = os.path.dirname(os.path.abspath(__file__))
falhas = []
inicio = time.time()
for arq in sorted(glob.glob(os.path.join(PASTA, "teste_*.py"))):
    nome = os.path.basename(arq)
    r = subprocess.run([sys.executable, arq], capture_output=True, text=True, timeout=600, cwd=PASTA)
    saida = (r.stdout + r.stderr).strip().splitlines()
    resumo = next((l for l in reversed(saida) if re.search(r"\b[A-ZÇÃ]+ OK\b", l)), "")
    if nome == "teste_handshake.py":
        resumo = next((l.strip() for l in saida if "tools/list" in l), "")
    if r.returncode != 0 or not resumo:
        falhas.append(nome)
        print(f"✘ {nome}\n" + "\n".join(saida[-15:]))
    else:
        print(f"✔ {nome:24} {resumo.strip()}")
print(f"\n{len(falhas)} falha(s) em {time.time() - inicio:.0f}s")
sys.exit(1 if falhas else 0)
