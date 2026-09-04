% TRAIN_MIMO_2H4H_STZ  Treino MIMO nativo 2h+4h (Santa Tereza) — pesquisa
% ---------------------------------------------------------------------------
% Espelha o MimoMLP Python (z-score + logsig + minibatch + early stopping).
% Pré-requisito:
%   python3 codigo_python/11_experimento_mimo/export_matlab_mimo_package.py
%
% NÃO promove ao vivo. Teto = mat_reference_metrics_teste (~0.9962 / ~0.9926).
% NÃO usar replay alinhado NASH≈1 como teto.
% ---------------------------------------------------------------------------

function metrics = train_mimo_2h4h_stz(dataDir, nh, seed)
if nargin < 1 || isempty(dataDir)
    here = fileparts(mfilename('fullpath'));
    dataDir = fullfile(here, '..', '..', '..', 'assets', 'data', 'research_mimo_matlab_handoff');
end
if nargin < 2 || isempty(nh), nh = 40; end
if nargin < 3 || isempty(seed), seed = 42; end

csvAll = fullfile(dataDir, 'mimo_aligned_2h4h_15in.csv');
assert(exist(csvAll, 'file') == 2, 'CSV ausente: %s (rode o export Python)', csvAll);

T = readtable(csvAll);
nin = 15;
X = table2array(T(:, 1:nin));
atual = T.atual_cm;
Ydelta = [T.delta_2h_cm, T.delta_4h_cm];
split = T.split;

tr = split == 1; va = split == 2; te = split == 3;
Xtr = X(tr,:); Ytr = Ydelta(tr,:);
Xva = X(va,:); Yva = Ydelta(va,:);

x_mean = mean(Xtr, 1); x_std = max(std(Xtr, 0, 1), 1e-6);
y_mean = mean(Ytr, 1); y_std = max(std(Ytr, 0, 1), 1e-6);

rng(seed);
Wh = 0.5 * randn(nh, nin);
bh = zeros(nh, 1);
Ws = 0.5 * randn(2, nh);
bs = zeros(2, 1);

lr = 0.015;
batch = 64;
maxEpochs = 500;
patience = 40;
bestVal = inf;
stall = 0;
best = struct('Wh', Wh, 'bh', bh, 'Ws', Ws, 'bs', bs);

nTr = size(Xtr, 1);
for ep = 1:maxEpochs
    ord = randperm(nTr);
    for s = 1:batch:nTr
        idx = ord(s:min(s+batch-1, nTr));
        [Wh, bh, Ws, bs] = train_batch(Xtr(idx,:), Ytr(idx,:), Wh, bh, Ws, bs, ...
            x_mean, x_std, y_mean, y_std, lr);
    end
    predVa = forward_delta(Xva, Wh, bh, Ws, bs, x_mean, x_std, y_mean, y_std);
    valMse = mean((predVa - Yva).^2, 'all');
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
sets = {tr, va, te}; names = {'treino','validacao','teste'};
for i = 1:3
    mask = sets{i};
    dhat = forward_delta(X(mask,:), Wh, bh, Ws, bs, x_mean, x_std, y_mean, y_std);
    yhat = atual(mask) + dhat;
    ytrue = atual(mask) + Ydelta(mask,:);
    metrics.(names{i}) = struct( ...
        'nash_2h', nash(ytrue(:,1), yhat(:,1)), ...
        'nash_4h', nash(ytrue(:,2), yhat(:,2)), ...
        'e95_2h', prctile(abs(ytrue(:,1)-yhat(:,1)), 95), ...
        'e95_4h', prctile(abs(ytrue(:,2)-yhat(:,2)), 95), ...
        'n', sum(mask));
end

outMat = fullfile(dataDir, sprintf('mimo_2h4h_stz_nh%d_seed%d_matlab.mat', nh, seed));
save(outMat, 'Wh', 'bh', 'Ws', 'bs', 'x_mean', 'x_std', 'y_mean', 'y_std', ...
    'nh', 'nin', 'seed', 'metrics', 'bestVal', '-v7');
fprintf('Salvo %s\n', outMat);
fprintf('TESTE 2h: NASH=%.4f E95=%.1f | 4h: NASH=%.4f E95=%.1f (n=%d, ep~%d)\n', ...
    metrics.teste.nash_2h, metrics.teste.e95_2h, metrics.teste.nash_4h, metrics.teste.e95_4h, ...
    metrics.teste.n, ep);
fprintf('Teto .mat completo: 2h≈0.9962 · 4h≈0.9926\n');
end

function dhat = forward_delta(X, Wh, bh, Ws, bs, x_mean, x_std, y_mean, y_std)
Pn = (X - x_mean) ./ x_std;
H = logsig(Pn * Wh' + bh');
Yn = logsig(H * Ws' + bs');
dhat = Yn .* y_std + y_mean;
end

function [Wh, bh, Ws, bs] = train_batch(X, Y, Wh, bh, Ws, bs, x_mean, x_std, y_mean, y_std, lr)
Pn = (X - x_mean) ./ x_std;
YnTrue = (Y - y_mean) ./ y_std;
Hraw = Pn * Wh' + bh';
H = logsig(Hraw);
Zraw = H * Ws' + bs';
Yn = logsig(Zraw);
% grad no espaço normalizado (alvo da saída logsig)
dZo = (Yn - YnTrue) .* Yn .* (1 - Yn);
dWs = dZo' * H;
dbs = sum(dZo, 1)';
dH = (dZo * Ws) .* H .* (1 - H);
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
