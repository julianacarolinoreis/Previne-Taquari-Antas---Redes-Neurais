# Planos de atuação — mestrado (multi-risco) e IC

Rascunho em texto corrido para o coordenador incorporar no projeto. Não é alocação fechada de bolsista nem produto operacional. Serve para os avaliadores verem que a equipe tem noção do que cada perfil pode fazer, e que as etapas variam conforme dados, acesso institucional e duração da bolsa.

O que já existe no PREVINE (previsão de nível, mapas-piloto em Santa Tereza e Muçum, vulnerabilidade social, movimentos de massa de 2024, serviços pontuais) entra como ponto de partida. O que ainda não está cruzado, validado em campo ou autorizado permanece proposto.

---

## 1. Mestrado — abordagem multi-risco

O plano de mestrado situa-se na abordagem multi-risco geo-hidrológico da Bacia Hidrográfica do Rio Taquari-Antas: inundação, enxurrada e movimentos de massa, lidos junto com exposição e vulnerabilidade social. O objetivo não é inventar um índice único de “risco total”, nem substituir o alerta oficial. É montar, documentar e testar um recorte de pesquisa em que perigo, exposição e vulnerabilidade permanecem camadas distintas, com proveniência, data e limitação explícitas, e só se cruzam onde houver base espacial compatível.

A primeira etapa é recortar a pergunta e o território. O mestrado parte dos 18 municípios da bacia e usa Santa Tereza e Muçum como leituras-piloto, porque nelas o projeto já publicou previsão de nível, mancha experimental e fichas municipais. Nessa etapa o bolsista descreve o que cada ameaça representa no recorte, quais fontes oficiais e de pesquisa já existem, e o que continua desconhecido. A profundidade varia: se um município não tiver setorização de risco, MDT adequado ou mancha conferida, isso não é preenchido por analogia; fica registrado como lacuna.

A segunda etapa trata do perigo. No hidrológico, o trabalho organiza cotas e séries de nível (ANA/SGB), confronta limiares por estação quando houver fonte, e usa as manchas experimentais já geradas por terreno (MDT/HAND) apenas como hipótese espacial — nível previsto não vira automaticamente profundidade de rua. No de encosta, parte dos pontos de iniciação e polígonos de deslizamento mapeados em 2024 e, onde existir, da setorização de risco do SGB (hoje publicada para Santa Tereza, sem extrapolação para o restante da bacia). Etapa variável: a comparação com modelagem hidrodinâmica, radar ou umidade do solo só entra se a base estiver disponível e auditável; caso contrário, o perigo permanece descritivo e local.

A terceira etapa trata da exposição: população e domicílios (Censo IBGE 2022, setores e grade), equipamentos pontuais já recortados do IEDE-RS (saúde, escolas, bombeiros) e, quando o documento municipal existir, abrigos e eixos viários como inventário — não como ocupação ou travessia atuais. Ausência de ponto na camada significa “não localizado nesta fonte”, não inexistência do serviço.

A quarta etapa trata da vulnerabilidade social e dos indicadores reutilizáveis. O projeto já reúne contagens de população, mulheres, crianças (0–4 e 5–9), idosos (60–69 e 70+), cor ou raça, água e esgoto em domicílios ocupados, renda do responsável, densidade, além de referências municipais de capacidade (ICM) e, com cobertura parcial, resiliência. O mestrado deve explicitar o que cada indicador mede, o denominador correto, o recorte (município inteiro versus setor na bacia) e o que não pode ser feito: valor omitido por sigilo não vira zero; indicador municipal não se soma com setorial; ICM e serviços pontuais não são mapa contínuo de perigo. A “noção de indicadores para o futuro” é justamente esse catálogo estável — o que se pode voltar a usar em outros recortes da bacia — e não um ranking improvisado.

A quinta etapa é o cruzamento espacial, somente onde geometria, datum e data permitirem. O produto esperado é um conjunto de mapas e tabelas de cenário (por exemplo: setores com mais idosos ou crianças na área da mancha-piloto; equipamentos cadastrados próximos a cotas estudadas; cicatrizes de 2024 em relação a ocupação). Onde o cruzamento não for defensável, o texto diz isso. Nenhum cenário vira rota liberada, abrigo confirmado ou ordem de evacuação.

A sexta etapa é a escrita e a validação de pesquisa: método, limitações, comparação com o que já existe em SIG multicritério e previsão baseada em impactos, e o que o recorte da Taquari-Antas acrescenta (dados locais, duas estações-piloto, distinção explícita entre pesquisa e operação). A defesa deve deixar claro o que é fundamentação da literatura e o que é funcionalidade proposta pelo projeto.

Etapas variáveis, em uma frase: a ordem se mantém (pergunta → perigo → exposição → vulnerabilidade → cruzamento → escrita), mas a espessura de cada bloco depende de acesso a dados, qualidade do terreno, parceria municipal e tempo de bolsa. O que não couber no mestrado permanece como agenda, não como resultado fingido.

---

## 2. Iniciação científica — dados, consistência, mapas e scripts

O plano de IC é de apoio transversal a vários objetivos do projeto, em tarefas básicas e repetíveis: organizar dados hidrológicos e territoriais, conferir consistência, produzir mapas de pesquisa e auxiliar nos scripts da plataforma digital. Não se espera que a IC desenvolva sozinha o WebGIS nem tome decisão operacional. Espera-se trilha de dados auditável — baixar, documentar fonte e data, preparar a “papinha” que os demais eixos usam, e registrar quando algo falhou.

A primeira etapa é o inventário. O bolsista ajuda a listar, para cada base, origem, recorte espacial, período, CRS, licença e arquivo de fontes. No hidrológico: telemetria de nível e, quando houver, chuva; no territorial: limite da bacia, setores, municípios, MDT, manchas-piloto, movimentos de massa, serviços pontuais. Etapa variável: novas fontes (radar, setorização de outros municípios, planos de contingência) só entram depois de URL, data e recorte conferidos.

A segunda etapa é baixar e preparar. O projeto já tem robôs em Python para previsão ao vivo, recorte de vulnerabilidade (IBGE) e serviços (IEDE-RS), publicados com `FONTES.md`. A IC reproduz esses fluxos, atualiza a documentação quando o dicionário da fonte muda, e não publica dado implausível (por exemplo recorte da bacia fora da faixa esperada). “Fazer papinha” aqui é: mesmo CRS, mesma data de referência, nulos preservados, nomes estáveis, JSON/GeoJSON que o site e o QGIS consigam ler.

A terceira etapa é a análise de consistência, o núcleo formativo da IC. Exemplos concretos, todos variáveis conforme a série disponível: horários e fuso; estação certa; lacunas não interpoladas como se fossem zero; nível ANA confrontado com o boletim SACE sem misturar limiares de cidades diferentes; no censo, sigilo estatístico mantido como nulo; no mapa, bounding box de encostas não confundida com o divisor oficial da bacia. O produto é um registro curto do que conferiu, o que divergiu e o que ficou pendente — não um “dado limpo” sem ressalva.

A quarta etapa é a produção de mapas de pesquisa. A partir dos GeoPackage/Shapefile já publicados, a IC monta layouts simples (perigo-piloto, vulnerabilidade, serviços, cicatrizes de 2024) com legenda, fonte, data e a frase de limitação no próprio mapa. Mapas novos só saem se a camada de origem estiver no inventário. Não se desenha rota, abrigo “confirmado” ou alerta.

A quinta etapa é auxiliar nos códigos da plataforma digital: rodar os scripts existentes, ler logs dos robôs (previsão, bacia, vulnerabilidade, serviços), reportar falha com evidência, e, com supervisão, ajustar caminho, metadado ou teste de sanidade. Eventualmente pode ajudar a executar um modelo já treinado ou um replay já protocolado — não a inventar modelo novo. A contribuição para a plataforma é operacional e documental: alimentar as camadas, manter a trilha de auditoria e deixar o próximo bolsista repetir o procedimento.

Etapas variáveis: se a telemetria atrasar, a IC documenta atraso em vez de completar série; se um serviço do IEDE sumir do catálogo, registra aviso e segue com os demais; se não houver MDT em um município, o mapa daquele recorte não é forçado. A IC atravessa os eixos do projeto justamente porque organização de dados, consistência e mapas são o chão comum da previsão, da vulnerabilidade e da plataforma.

---

## Como colar no WhatsApp (texto corrido, sem markdown)

**Mestrado**

O mestrado fica na abordagem multi-risco da Taquari-Antas: inundação, enxurrada e movimento de massa, junto com exposição e vulnerabilidade social. A ideia é pesquisar essas camadas juntas sem virar um índice único de risco e sem substituir a Defesa Civil. Primeiro recorta a pergunta e o território, usando Santa Tereza e Muçum como piloto porque já temos previsão, mancha experimental e ficha municipal; onde faltar dado, fica lacuna. Depois organiza o perigo: séries e cotas de nível, mancha só como hipótese espacial, e encostas a partir do mapeamento de 2024 e da setorização do SGB onde ela existir (hoje Santa Tereza, sem extrapolar). Em seguida exposição (população, domicílios, serviços pontuais, inventário de abrigos/vias quando o documento municipal existir) e vulnerabilidade com os indicadores que já temos e que dão para reutilizar no futuro: crianças, idosos, água, esgoto, renda, densidade, ICM etc., sempre com denominador certo e sem transformar sigilo em zero. O cruzamento espacial só acontece onde geometria e data baterem; o produto é mapa e tabela de cenário, não rota liberada nem ordem de evacuação. Fecha com método, limitações e o que é literatura versus o que o projeto ainda propõe. A ordem das etapas se mantém; a espessura de cada uma varia com dado, terreno, município e tempo de bolsa.

**IC**

A IC é apoio básico e transversal: organizar dados hidrológicos, conferir consistência, produzir mapas de pesquisa e ajudar nos scripts da plataforma. Inventaria cada base (fonte, recorte, data, CRS). Baixa e prepara a papinha que os outros eixos usam, reproduzindo os robôs que já existem e atualizando as fontes. Faz consistência: horário, estação, lacuna sem interpolar, ANA versus SACE sem misturar cidade, sigilo do censo como nulo. Produz mapas simples com legenda, data e limitação. Nos códigos, roda script, lê log, reporta falha e, com supervisão, ajusta caminho ou documentação; eventualmente ajuda a rodar um modelo já existente, não a criar modelo novo. Se a série atrasar ou a camada sumir, documenta em vez de completar no chute. Isso serve a vários objetivos do projeto porque dado organizado é o chão da previsão, da vulnerabilidade e da plataforma.
