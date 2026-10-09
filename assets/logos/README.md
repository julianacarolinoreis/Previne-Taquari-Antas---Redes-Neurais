# Assinatura institucional PREVINE, UFRGS e LAGAM

Os três PNGs são cópias integrais dos arquivos fornecidos pelo projeto no Google
Drive. Nenhum pixel, cor ou proporção foi modificado. As molduras do CSS exibem
a região da marca com uma margem de proteção e deixam de ocupar espaço com a
área externa vazia do arquivo original.

- `previne.png`: arquivo `LOGO FUNDO TRANSPARENTE`, ID
  `1YvuQjg9UE565glyDU5JCn58_5jLuVfj_`, na pasta de logos e template fornecida.
- `lagam.png`: arquivo `Logo LAGAM.png`, ID
  `1Qp3yoXS6D8xFC4UknpMsb8909Ds6K62j`, fornecido diretamente.
- `ufrgs.png`: imagem `ppt/media/image1.png` extraída, sem recodificação, do
  `Template Padrão Previne edição _20260128_104514_0000.pptx`, ID
  `1n4n0ccCprCzg5VhsassvPjeTyfdjvn2C`. É a marca UFRGS do próprio template,
  com resolução maior que o PNG separado de 122 × 95 px na mesma pasta.

O deploy aplica `scripts/apply_institutional_logos.py` ao artefato `_site` antes
do upload. Isso também atende páginas de pesquisa geradas por outros scripts.
HTML de fontes externas em diretórios `raw`, rascunhos e redirecionamentos são
preservados. As páginas de destino dos redirecionamentos recebem a assinatura.

A aplicação é idempotente. Cada página recebe uma assinatura acessível e os
caminhos relativos necessários à sua profundidade. Mapas em tela inteira
reservam 84 px para a assinatura, a legenda e os controles permanecem acima dela.
