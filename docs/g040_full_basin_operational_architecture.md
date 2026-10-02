# PREVINE G040 — arquitetura de bacia inteira

## Regra principal

O domínio da pesquisa é a Bacia Hidrográfica Taquari–Antas (G040) inteira. Nenhuma estação, município ou ponto de controle define o fim do modelo. Muçum, Encantado, Arroio do Meio, Lajeado, Estrela, Porto Mariante, Taquari, Triunfo e os controles de tributários são sensores e controles distribuídos dentro do mesmo sistema.

A cadeia deve responder primeiro “como está a G040?” e só depois permitir consultas locais.

## Domínio espacial

Há dois domínios com funções diferentes:

1. Máscara hidrológica G040 — união dos polígonos atuais Q040/G040. É a única área que pode contribuir chuva efetiva, escoamento, volume ou balanço hídrico.
2. Domínio de aquisição G040 + buffer — a máscara acrescida de um buffer métrico configurável, inicialmente 50 km. Serve para baixar pluviômetros próximos da borda e campos meteorológicos ECMWF/IFS sem introduzir artefatos de borda.

Dados do buffer externo podem ajudar a estimar o campo meteorológico na borda, mas nunca adicionam área de drenagem à G040.

## Pergunta operacional padrão

Quando a consulta for “como está a bacia nas próximas horas?”, a sequência é:

1. carregar ou atualizar a máscara G040 e o buffer;
2. obter chuva observada antecedente em toda a G040 e contexto de borda;
3. consolidar acumulados de 1, 3, 6, 12, 24, 48, 72, 120 e 168 horas;
4. obter o estado hidrométrico atual de todos os controles disponíveis;
5. obter ou atualizar estado de umidade do solo e memória hídrica;
6. baixar a rodada ECMWF/IFS mais recente para G040 + buffer;
7. preservar ciclo, lead time e horário válido;
8. unir observado até t0 com previsto após t0;
9. rodar transformação chuva–vazão distribuída;
10. propagar pela rede completa;
11. assimilar e comparar com controles frescos;
12. gerar mapas de bacia inteira e tabela distribuída por controle.

## Grade meteorológica

A grade retangular histórica de 600 células permanece apenas para compatibilidade com artefatos HEC existentes.

A grade canônica de aquisição passa a ser derivada da geometria G040 + buffer. Cada célula armazena:

- centro e extensão;
- se o centro está dentro da G040;
- área total da célula;
- área de interseção com a G040;
- fração da célula pertencente à G040;
- chuva prevista por horizonte.

Para média ou integração de chuva da bacia, o peso é a área de interseção com a G040. Células que existem apenas no buffer têm peso hidrológico zero.

## Produtos obrigatórios

A saída padrão inclui mapas de chuva antecedente, chuva observada atual, chuva prevista, umidade ou estado hídrico e resposta hidrológica. Onde houver hidráulica validada, acrescentam-se nível, profundidade, velocidade, mancha e impacto.

A tabela distribuída não pressupõe um ponto final. Para cada controle disponível ela deve mostrar observação atual, idade do dado, nível/vazão, tendência, contexto de montante, chuva antecedente, chuva prevista, estado do solo, previsão do modelo, horizonte, confiança e bloqueios.

## Calibração

O objetivo é um modelo calibrado e validado multiestação e multievento. O eixo principal e tributários entram conjuntamente.

A meta HEC completa permanece 145 sub-bacias + 72 reaches. O modelo por ramos BHO6 continua como camada intermediária de desenvolvimento e validação enquanto a topologia final é recuperada ou reconstruída.

O HEC-HMS contínuo/SMA, MGB e membros RNA só podem ser combinados depois de comparados em eventos e controles comuns.

## Implementação iniciada

A branch de pesquisa introduz:

- contrato operacional de bacia inteira;
- gerador da máscara G040 e buffer;
- downloader ECMWF/IFS para G040 + buffer;
- ponderação de células pela interseção real com a G040;
- snapshot único de bacia;
- CSV multiestação;
- testes de contrato;
- workflow periódico/manual para atualização dos artefatos.

O snapshot não inventa previsão de nível ou vazão onde a calibração distribuída ainda não passou pelos gates de validação.
