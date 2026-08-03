function rodar_rotacoes()
% RODAR_ROTACOES  Treina uma RNA de 2h por rotacao (Santa Tereza), gerando os
% MESMOS artefatos das redes que ja temos:
%   saida/<nome>.mat                        (formato dos RNAPREV__* do PREVINE)
%   saida/<nome>_AUDITAVEL_INPUTS_RNA.xlsx  (6 abas, igual audit_workbooks/)
%   saida/ranking_rotacoes.xlsx             (compara todas as rotacoes)
%
% Voce so precisa: (1) por modelo_2h_novo.xlsx nesta pasta, (2) rodar isto no
% MATLAB. As rotacoes e hiperparametros ficam em config_rotacoes.m.
%
% Um modelo ALT preve a VARIACAO de nivel em 2h; o nivel previsto e
%   nivel_atual + variacao. A base de comparacao (persistencia) e "variacao 0".

cfg = config_rotacoes();
if ~exist(cfg.saida_dir,'dir'), mkdir(cfg.saida_dir); end

% ------------------------------------------------ leitura da planilha VAR ---
fprintf('Lendo %s (aba %s)...\n', cfg.xlsx, cfg.plan);
T = readtable(cfg.xlsx,'Sheet',cfg.plan,'VariableNamingRule','preserve');
evento = T{:,7};                       % coluna G
data6  = T{:,1:6};                     % ANO..COD_SEQUENCIAL
X      = T{:,8:8+cfg.n_input-1};       % 15 inputs (H..V)
alvo   = T{:,23};                      % OUT2H DIF (variacao observada, W)
ok = ~any(isnan(X),2) & ~isnan(alvo) & ~isnan(evento);
evento=evento(ok); data6=data6(ok,:); X=X(ok,:); alvo=alvo(ok);
nivel_atual = X(:,1);                   % input_01 = nivel atual
observado   = nivel_atual + alvo;       % nivel daqui a 2h
N = numel(alvo);
fprintf('  %d linhas completas, %d eventos.\n', N, numel(unique(evento)));

% li/ls (folga f) calculados sobre TODO o alvo -> iguais para toda rotacao
f  = cfg.par.f;  amp = max(alvo)-min(alvo);
li = min(alvo) - f*amp;   ls = max(alvo) + f*amp;   au = ls-li;  bu = li;

R = size(cfg.rotacoes,1);
resumo = cell(R,1);

for r = 1:R
    nome   = cfg.rotacoes{r,1};
    ev_val = cfg.rotacoes{r,2};
    ev_ver = cfg.rotacoes{r,3};

    serie = ones(N,1);                                   % 1 = treino
    serie(ismember(evento,ev_val)) = 2;                  % 2 = validacao
    serie(ismember(evento,ev_ver)) = 3;                  % 3 = verificacao
    itr = serie==1;  iva = serie==2;  ive = serie==3;

    % --- normalizacao dos inputs: media/desvio(ddof=1) do TREINO ---
    be = mean(X(itr,:),1);   ae = std(X(itr,:),0,1);   ae(ae<1e-9)=1;
    norm = struct('be',be,'ae',ae,'au',au,'bu',bu);
    Pt = ((X(itr,:)-be)./ae)';   Tt = ((alvo(itr)-li)./au)';
    Pv = ((X(iva,:)-be)./ae)';   Tv = ((alvo(iva)-li)./au)';

    fprintf('[%d/%d] %-22s treino=%d valida=%d verifica=%d ...\n', ...
            r,R,nome,sum(itr),sum(iva),sum(ive));
    tic;
    net = rna_treina(Pt, Tt, Pv, Tv, cfg.par);
    tt = toc;

    % --- previsao em cm para TODAS as linhas ---
    y  = rna_forward(net, norm, X);           % variacao prevista
    rna_nivel = nivel_atual + y;              % nivel previsto

    % --- metricas por conjunto ---
    M = struct();
    for k = 1:4
        switch k, case 1, s=true(N,1); rot='GERAL';
                 case 2, s=itr; rot='TREINO';
                 case 3, s=iva; rot='VALIDACAO';
                 case 4, s=ive; rot='TESTE'; end
        M(k) = metricas(rot, alvo(s), y(s));
    end
    fprintf('        TESTE: N=%d PERS=%.4f MAE=%.2f NASH=%.4f  (%.0fs, reinicio %d)\n', ...
            M(4).N, M(4).PERS, M(4).MAE, M(4).NASH, tt, net.reinicio);

    % --- grava .mat (formato PREVINE) ---
    salva_mat(fullfile(cfg.saida_dir,[nome '.mat']), net, norm, li, ls, f, ...
              cfg, X, alvo, serie, y, M, nome);

    % --- grava Excel auditavel (6 abas) ---
    escreve_auditavel(fullfile(cfg.saida_dir,[nome '_AUDITAVEL_INPUTS_RNA.xlsx']), ...
        cfg, nome, evento, serie, data6, X, alvo, nivel_atual, observado, ...
        y, rna_nivel, M);

    resumo{r} = {nome, M(2).N, M(3).N, M(4).N, M(4).PERS, M(4).MAE, M(4).E95, ...
                 M(4).NASH, M(3).PERS, M(3).MAE, net.reinicio};
end

% --------------------------------------------------- ranking geral ----------
cab = {'rotacao','n_treino','n_valida','n_teste','TESTE_PERS','TESTE_MAE', ...
       'TESTE_E95','TESTE_NASH','VALID_PERS','VALID_MAE','reinicio_escolhido'};
lin = vertcat(resumo{:});
% ordena por PERS do teste (desc)
pers = cell2mat(lin(:,5));  [~,ord] = sort(pers,'descend');  lin = lin(ord,:);
Tk = cell2table(lin,'VariableNames',cab);
writetable(Tk, fullfile(cfg.saida_dir,'ranking_rotacoes.xlsx'));
fprintf('\nPronto. Ranking em %s\n', fullfile(cfg.saida_dir,'ranking_rotacoes.xlsx'));
disp(Tk);
end

% ============================================================ locais ========
function m = metricas(rot, obs, sim)
% obs/sim: variacao (cm). Base = persistencia (variacao 0).
e = sim - obs;  sse = sum(e.^2);  sst = sum((obs-mean(obs)).^2);
ssb = sum(obs.^2);                         % erro da persistencia (prev=0)
m.conjunto = rot;  m.N = numel(obs);
m.MAE  = mean(abs(e));
m.RMSE = sqrt(sse/m.N);
m.NASH = 1 - sse/sst;
m.PERS = 1 - sse/ssb;
m.E95  = pctl(abs(e),95);
m.SOMA_E2_RNA  = sse;
m.SOMA_E2_PERS = ssb;
end
