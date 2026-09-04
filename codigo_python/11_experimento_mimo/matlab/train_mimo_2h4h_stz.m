% TRAIN_MIMO_2H4H_STZ  Treino MIMO nativo 2h+4h (Santa Tereza) — pesquisa
% ---------------------------------------------------------------------------
% Pré-requisito: rodar o export Python antes:
%   python3 codigo_python/11_experimento_mimo/export_matlab_mimo_package.py
%
% Este script NÃO promove modelo ao vivo. Comparar contra:
%   - Direct scratch (mesmo CSV)
%   - mat_reference_metrics_teste (NASH 2h≈0.9962, 4h≈0.9926)
% NÃO usar replay alinhado (NASH≈1) como teto.
% ---------------------------------------------------------------------------

function train_mimo_2h4h_stz(dataDir, nh)
if nargin < 1 || isempty(dataDir)
    here = fileparts(mfilename('fullpath'));
    dataDir = fullfile(here, '..', '..', '..', 'assets', 'data', 'research_mimo_matlab_handoff');
end
if nargin < 2 || isempty(nh)
    nh = 40;
end

csvAll = fullfile(dataDir, 'mimo_aligned_2h4h_15in.csv');
assert(exist(csvAll, 'file') == 2, 'CSV ausente: %s (rode o export Python)', csvAll);

T = readtable(csvAll);
nin = 15;
X = table2array(T(:, 1:nin));
atual = T.atual_cm;
Ydelta = [T.delta_2h_cm, T.delta_4h_cm];
split = T.split;
event = T.event; %#ok<NASGU>

tr = split == 1; va = split == 2; te = split == 3;
[Xn, ae, be] = scale01(X);
[Ydn, au, bu] = scale01(Ydelta);

% MLP logsig: H = logsig(Pn*Wh'+bh); Yn = logsig(H*Ws'+bs)
rng(42);
Wh = 0.5 * randn(nh, nin);
bh = 0.5 * randn(nh, 1);
Ws = 0.5 * randn(2, nh);
bs = 0.5 * randn(2, 1);

lr = 0.015;
maxEpochs = 500;
patience = 40;
bestVal = inf;
best = struct('Wh', Wh, 'bh', bh, 'Ws', Ws, 'bs', bs);
stall = 0;

PnTr = Xn(tr, :); YnTr = Ydn(tr, :);
PnVa = Xn(va, :); YnVa = Ydn(va, :);

for ep = 1:maxEpochs
    [Wh, bh, Ws, bs] = backprop_batch(PnTr, YnTr, Wh, bh, Ws, bs, lr);
    predVa = forward(PnVa, Wh, bh, Ws, bs);
    valMse = mean((predVa - YnVa).^2, 'all');
    if valMse + 1e-6 < bestVal
        bestVal = valMse;
        best = struct('Wh', Wh, 'bh', bh, 'Ws', Ws, 'bs', bs);
        stall = 0;
    else
        stall = stall + 1;
    end
    if stall >= patience
        break
    end
end

Wh = best.Wh; bh = best.bh; Ws = best.Ws; bs = best.bs;
metrics = struct();
for name = {'treino','validacao','teste'}
    key = name{1};
    switch key
        case 'treino', mask = tr;
        case 'validacao', mask = va;
        otherwise, mask = te;
    end
    yn = forward(Xn(mask,:), Wh, bh, Ws, bs);
    dhat = yn .* au + bu;
    yhat = atual(mask) + dhat;
    ytrue = atual(mask) + Ydelta(mask,:);
    metrics.(key) = struct( ...
        'nash_2h', nash(ytrue(:,1), yhat(:,1)), ...
        'nash_4h', nash(ytrue(:,2), yhat(:,2)), ...
        'e95_2h', prctile(abs(ytrue(:,1)-yhat(:,1)), 95), ...
        'e95_4h', prctile(abs(ytrue(:,2)-yhat(:,2)), 95), ...
        'n', sum(mask));
end

outMat = fullfile(dataDir, sprintf('mimo_2h4h_stz_nh%d_matlab.mat', nh));
save(outMat, 'Wh', 'bh', 'Ws', 'bs', 'ae', 'be', 'au', 'bu', 'nh', 'nin', 'metrics', 'bestVal', '-v7');
fprintf('Salvo %s\n', outMat);
fprintf('TESTE 2h: NASH=%.4f E95=%.1f cm | 4h: NASH=%.4f E95=%.1f cm (n=%d)\n', ...
    metrics.teste.nash_2h, metrics.teste.e95_2h, metrics.teste.nash_4h, metrics.teste.e95_4h, metrics.teste.n);
fprintf('Referência .mat completo (teto): 2h NASH≈0.9962 · 4h NASH≈0.9926\n');
end

function [Xn, ae, be] = scale01(X)
be = min(X, [], 1);
ae = max(X, [], 1) - be;
ae(ae < 1e-9) = 1;
Xn = (X - be) ./ ae;
end

function Yn = forward(Pn, Wh, bh, Ws, bs)
H = logsig(Pn * Wh' + bh');
Yn = logsig(H * Ws' + bs');
end

function [Wh, bh, Ws, bs] = backprop_batch(Pn, Yn, Wh, bh, Ws, bs, lr)
H = logsig(Pn * Wh' + bh');
Yhat = logsig(H * Ws' + bs');
dYo = (Yhat - Yn) .* Yhat .* (1 - Yhat);
dWs = dYo' * H;
dbs = sum(dYo, 1)';
dH = (dYo * Ws) .* H .* (1 - H);
dWh = dH' * Pn;
dbh = sum(dH, 1)';
Ws = Ws - lr * dWs;
bs = bs - lr * dbs;
Wh = Wh - lr * dWh;
bh = bh - lr * dbh;
end

function y = logsig(z)
z = min(max(z, -60), 60);
y = 1 ./ (1 + exp(-z));
end

function v = nash(y, yhat)
den = sum((y - mean(y)).^2);
if den < 1e-12
    v = NaN;
else
    v = 1 - sum((y - yhat).^2) / den;
end
end
