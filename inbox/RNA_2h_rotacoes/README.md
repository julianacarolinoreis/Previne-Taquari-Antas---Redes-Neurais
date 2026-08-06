# Inbox — RNA_2h_rotacoes (Santa Tereza)

Pasta temporária para eu (agente Cursor) receber os modelos novos de 2h.

## O que colocar aqui

Copie de `D:\PREVINE\redes_neurais\santa tereza\RNA_2h_rotacoes`:

1. **`mat/`** — todos os `.mat` (obrigatório)
2. **`resultados/`** — CSV(s) de resultados da rodada (recomendado)
3. **`auditaveis/`** — planilhas `.xlsx` (opcional; é a parte mais pesada)

## Como enviar

### Opção A — GitHub (arrastar e soltar)
Abra este link e arraste as pastas/arquivos:

https://github.com/julianacarolinoreis/Previne-Taquari-Antas---Redes-Neurais/upload/cursor/inbox-rna-2h-rotacoes-7179/inbox/RNA_2h_rotacoes

Depois clique em **Commit changes**.

### Opção B — do seu PC (Git)
```bat
git clone -b cursor/inbox-rna-2h-rotacoes-7179 https://github.com/julianacarolinoreis/Previne-Taquari-Antas---Redes-Neurais.git
cd Previne-Taquari-Antas---Redes-Neurais
xcopy /E /I "D:\PREVINE\redes_neurais\santa tereza\RNA_2h_rotacoes\mat" inbox\RNA_2h_rotacoes\mat
xcopy /E /I "D:\PREVINE\redes_neurais\santa tereza\RNA_2h_rotacoes\resultados" inbox\RNA_2h_rotacoes\resultados
git add inbox/RNA_2h_rotacoes
git commit -m "inbox: modelos RNA_2h_rotacoes"
git push
```

### Opção C — link Drive/OneDrive
Se ficar pesado demais pro GitHub, suba um zip e cole o link no chat do agente.

## Depois
Eu leio esta pasta, atualizo o site (apago os 2h antigos, publico os novos) e removo o inbox.
