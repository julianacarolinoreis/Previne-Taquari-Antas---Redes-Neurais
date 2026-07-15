#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Validação do forward-pass da RNA — Santa Tereza (86472600), modelo 2h ALT C0472.

Objetivo: provar, SEM MATLAB, que a implementação em Python da rede reproduz
EXATAMENTE as previsões gravadas dentro do próprio arquivo .mat treinado.

Como funciona a rede (decodificada e confirmada a partir do .mat):
  1. normalização de entrada:  pn = (P - be) / ae      (be = média, ae = desvio, por input)
  2. camada oculta (30 neur.):  h  = logsig(wh · pn + bh)
  3. camada de saída:           yn = logsig(ws · h  + bs)
  4. desnormalização:           variação = yn * au + bu
  5. como é modelo ALT:         nível_previsto = nível_atual + variação

Rodar:  python validar_forward_pass.py caminho/para/rot_003_06_2h_alt_2H_ALT_C0472.mat
Saída esperada:  RMSE = 0.0  |  erro máximo = 0.0  (reprodução exata de Tctot1)
"""
import sys
import numpy as np
from scipy.io import loadmat

def logsig(z):
    return 1.0 / (1.0 + np.exp(-z))

def forward(m, P):
    """P: matriz (n_amostras, 15) com os 15 inputs crus. Devolve a variação (cm)."""
    wh = np.atleast_2d(np.asarray(m["wh"], float))   # (30,15) pesos ocultos
    bh = np.asarray(m["bh"], float).ravel()          # (30,)   bias oculto
    ws = np.asarray(m["ws"], float).ravel()          # (30,)   pesos de saída
    bs = float(np.atleast_1d(m["bs"])[0])            # bias de saída
    ae = np.asarray(m["ae"], float).ravel()          # desvio por input
    be = np.asarray(m["be"], float).ravel()          # média  por input
    au = float(np.atleast_1d(m["au"])[0])            # escala de saída
    bu = float(np.atleast_1d(m["bu"])[0])            # offset de saída
    pn = (P - be) / ae                               # (n,15) normalizado
    H  = logsig(pn @ wh.T + bh)                       # (n,30)
    yn = logsig(H @ ws + bs)                          # (n,)
    return yn * au + bu                               # variação prevista (cm)

def main(mat_path):
    m = loadmat(mat_path, squeeze_me=True)
    DADOS  = np.asarray(m["DADOS"], float)            # (1810,16): 15 inputs + alvo
    P      = DADOS[:, :15]
    ATUAL  = np.asarray(m["ATUAL_TOT"], float)        # nível atual (cm)
    Tctot1 = np.asarray(m["Tctot1"], float)           # previsão absoluta gravada no .mat

    pred = ATUAL + forward(m, P)                      # nossa reprodução
    err  = pred - Tctot1
    rmse = float(np.sqrt(np.mean(err**2)))
    emax = float(np.max(np.abs(err)))

    print(f"amostras: {P.shape[0]}  |  inputs: {P.shape[1]}  |  neurônios: {np.asarray(m['wh']).shape[0]}")
    print(f"métricas gravadas no .mat -> NASH={float(m['NASH']):.4f}  PERS={float(m['PERS']):.4f}  E95={float(m['e95']):.2f} cm")
    print(f"RMSE (Python vs .mat) = {rmse:.6f} cm   |   erro máximo = {emax:.6f} cm")
    print("exemplo: nível atual %.0f cm -> previsto 2h = %.1f cm (%.2f m)"
          % (ATUAL[100], pred[100], pred[100] / 100))
    assert rmse < 1e-6, "Reprodução NÃO é exata — revisar o forward-pass!"
    print("OK: a rede em Python reproduz o modelo treinado com erro numérico nulo.")

if __name__ == "__main__":
    mat = sys.argv[1] if len(sys.argv) > 1 else "../../previne/assets/mat/rot_003_06_2h_alt_2H_ALT_C0472.mat"
    main(mat)
