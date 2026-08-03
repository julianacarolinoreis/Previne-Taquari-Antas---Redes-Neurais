function cfg = config_rotacoes()
% CONFIG_ROTACOES  Parametros e definicao das rotacoes da RNA de 2h (Santa Tereza).
%
% Edite APENAS este arquivo para:
%   - apontar para a planilha auditavel de origem;
%   - mudar os hiperparametros da rede;
%   - adicionar/remover rotacoes (quais EVENTOS ficam em validacao/verificacao).
%
% Uma "rotacao" e simplesmente uma atribuicao dos eventos aos conjuntos:
%   SERIE = 1 -> Treino | 2 -> Validacao | 3 -> Verificacao (teste)
% Todo evento que NAO estiver listado em .valida nem em .verifica vai para o
% treino. E exatamente o que a coluna Y (SERIE) da planilha VAR ja codifica.
%
% Os hiperparametros abaixo foram lidos de dentro do proprio .mat entregue
% (RNAPREV__SANTA_TEREZA__02h__ALT__15inputs_VFINAL_20260731.mat):
%   input=15  nh=31  Cic=30000  nit=10  f=0.05  Mom=0  lr~0.01

% ---------------------------------------------------------------- origem ----
cfg.xlsx      = 'modelo_2h_novo.xlsx';   % planilha de origem (na mesma pasta)
cfg.plan      = 'VAR';                    % aba com os eventos ja montados
cfg.col_ini_input = 'H';   % primeira coluna de input   (input_01)
cfg.n_input   = 15;        % 15 inputs -> colunas H..V
cfg.col_evento  = 'G';     % coluna do numero do evento
cfg.col_alvo    = 'W';     % OUT2H DIF  (variacao a prever -> modelo ALT)
cfg.col_nivel   = 'H';     % nivel atual = input_01 (base da persistencia)
cfg.linha_ini   = 2;       % primeira linha de dados
cfg.saida_dir   = 'saida'; % onde gravam os .mat e os Excel auditaveis

% nomes legiveis dos 15 inputs (para a aba INPUTS do auditavel)
cfg.nomes_input = { ...
  'inp01_nivel_86472600',        'inp02_DifN-1h_86472600', ...
  'inp03_DifN-2h_86472600',      'inp04_DifN-4h_86472600', ...
  'inp05_Acel-1h_86472600',      'inp06_Acel-2h_86472600', ...
  'inp07_Acel-4h_86472600',      'inp08_Acel-08h_86472600', ...
  'inp09_Acel-12h_86472600',     'inp10_nivel_86472000', ...
  'inp11_DifN-1h_86472000',      'inp12_DifN-2h_86472000', ...
  'inp13_DifN-5h_86472000',      'inp14_Acel-12h_86472000', ...
  'inp15_Acel-20h_86472000'};

% --------------------------------------------------- hiperparametros --------
cfg.par.nh   = 31;      % neuronios na camada oculta
cfg.par.Cic  = 30000;   % ciclos maximos por reinicio
cfg.par.nit  = 10;      % reinicios aleatorios (fica o melhor pela validacao)
cfg.par.lr   = 0.01;    % taxa de aprendizado inicial
cfg.par.Mom  = 0.0;     % momento
cfg.par.f    = 0.05;    % folga da normalizacao de saida (li/ls)
cfg.par.Prc  = 1e-3;    % melhora minima relativa da validacao p/ resetar paciencia
cfg.par.pac  = 3000;    % paciencia (ciclos sem melhora -> para o reinicio)
cfg.par.lr_inc = 1.05;  % adaptacao da taxa (aumenta quando melhora)
cfg.par.lr_dec = 0.70;  % adaptacao da taxa (reduz quando piora)
cfg.par.semente = 20260731;  % semente base (reprodutibilidade)

% ------------------------------------------------------- rotacoes -----------
% Cada linha: {nome, [eventos_validacao], [eventos_verificacao]}.
% rot_00_original REPRODUZ o split do modelo entregue (referencia de controle).
% As demais giram qual evento/cheia fica de fora para teste.
cfg.rotacoes = {
  'rot_00_original',  [1 5 10 15 17 21], [12]        % == modelo entregue
  'rot_01_teste_e03', [1 5 10 17 21],    [3]         % cheia jul/2023 (1250 cm)
  'rot_02_teste_e04', [1 5 10 15 21],    [4]         % cheia set/2023 (2365 cm)
  'rot_03_teste_e06', [1 5 10 15 17],    [6]         % cheia nov/2023 (2161 cm)
  'rot_04_teste_e20', [1 5 10 15 17],    [20]        % cheia jul/2026 (1746 cm)
  'rot_05_teste_e21', [1 5 10 15 17],    [21]        % cheia jul/2026 (1340 cm)
  'rot_06_teste_e12', [1 5 15 17 20],    [12]        % cheia jun/2025 (1332 cm)
  'rot_07_teste_recentes', [1 5 10 15 17], [20 21]   % as duas cheias de 2026
  'rot_08_teste_grandes',  [1 5 15 17],    [4 6]     % duas maiores cheias
  'rot_09_valida_2024',    [8 9 10 11],    [12]      % validacao com 2024
  'rot_10_teste_2025',     [1 5 10 21],    [13 15 17]% teste com o 2o semestre 2025
};

% Metodo do treino: 'reconstruido' usa rna_treina.m (fiel a receita do .mat).
% Se voce tiver a sua funcao MATLAB original de treino, troque por 'proprio'
% e edite rna_treina.m para chamar a sua (ver README).
cfg.metodo = 'reconstruido';
end
