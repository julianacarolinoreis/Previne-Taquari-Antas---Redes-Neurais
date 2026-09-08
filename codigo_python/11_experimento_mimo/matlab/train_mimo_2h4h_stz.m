% TRAIN_MIMO_2H4H_STZ  Treino MIMO nativo 2h+4h (Santa Tereza) — pesquisa
% ---------------------------------------------------------------------------
% Protocolo PREVINE (espelha fit_previne Python):
%   - ae/be = mean / std(ddof=1) no treino
%   - au/bu = liminf/limsup(f=0.05) no treino
%   - loss no espaço yn; dunisig = max(a.*(1-a), 0.01)
%   - GD full-batch; TX inicia 0.01, ×1.1 se EV melhora, senão restaura e TX=0.01
% Pré-requisito:
%   python3 .../export_matlab_mimo_package.py  (rótulos = observação Ttot1)
%
% NÃO promove ao vivo.
% Teto justo no alinhado ≈ Direct .mat vs obs (~0.996 / ~0.92 no teste alinhado).
% Teto operacional full-test: ~0.9962 / ~0.9926 (4h com 26 inputs).
% ---------------------------------------------------------------------------

function metrics = train_mimo_2h4h_stz(dataDir, nh, seed, maxCycles)
if nargin < 1 || isempty(dataDir)
    here = fileparts(mfilename('fullpath'));
    dataDir = fullfile(here, '..', '..', '..', 'assets', 'data', 'research_mimo_matlab_handoff');
end
if nargin < 2 || isempty(nh), nh = 40; end
if nargin < 3 || isempty(seed), seed = 42; end
if nargin < 4 || isempty(maxCycles), maxCycles = 40000; end

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

% PREVINE scales
be = mean(Xtr, 1);
ae = max(std(Xtr, 0, 1), 1e-6);  % MATLAB std default = ddof=1 (N-1)
f = 0.05;
ymin = min(Ytr, [], 1); ymax = max(Ytr, [], 1);
span = ymax - ymin;
bu = ymin - f * span;
au = max((ymax + f * span) - bu, 1e-6);

rng(seed);
Wh = 0.5 * randn(nh, nin);
bh = zeros(nh, 1);
Ws = 0.5 * randn(2, nh);
bs = zeros(2, 1);

lr0 = 0.01;
tx = lr0;
patience = 8000;
bestEv = inf;
stall = 0;
best = struct('Wh', Wh, 'bh', bh, 'Ws', Ws, 'bs', bs);

PnTr = (Xtr - be) ./ ae;
TnTr = (Ytr - bu) ./ au;
PnVa = (Xva - be) ./ ae;
TnVa = (Yva - bu) ./ au;

for cic = 1:maxCycles
    snap = struct('Wh', Wh, 'bh', bh, 'Ws', Ws, 'bs', bs);
    H = logsig(PnTr * Wh' + bh');
    Yn = logsig(H * Ws' + bs');
    dZo = (Yn - TnTr) .* dunisig(Yn);
    dWs = dZo' * H;
    dbs = sum(dZo, 1)';
    dH = (dZo * Ws) .* dunisig(H);
    dWh = dH' * PnTr;
    dbh = sum(dH, 1)';
    Ws = Ws - tx * dWs;
    bs = bs - tx * dbs;
    Wh = Wh - tx * dWh;
    bh = bh - tx * dbh;

    Hv = logsig(PnVa * Wh' + bh');
    Ynv = logsig(Hv * Ws' + bs');
    ev = mean((Ynv - TnVa).^2, 'all');
    if ev + 1e-12 < bestEv
        bestEv = ev;
        best = struct('Wh', Wh, 'bh', bh, 'Ws', Ws, 'bs', bs);
        stall = 0;
        tx = tx * 1.1;
    else
        Wh = snap.Wh; bh = snap.bh; Ws = snap.Ws; bs = snap.bs;
        tx = lr0;
        stall = stall + 1;
        if stall >= patience
            break
        end
    end
end

Wh = best.Wh; bh = best.bh; Ws = best.Ws; bs = best.bs;
metrics = struct();
sets = {tr, va, te}; names = {'treino','validacao','teste'};
for i = 1:3
    mask = sets{i};
    dhat = forward_delta(X(mask,:), Wh, bh, Ws, bs, be, ae, bu, au);
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
save(outMat, 'Wh', 'bh', 'Ws', 'bs', 'ae', 'be', 'au', 'bu', ...
    'nh', 'nin', 'seed', 'metrics', 'bestEv', 'cic', '-v7');
fprintf('Salvo %s\n', outMat);
fprintf('TESTE 2h: NASH=%.4f E95=%.1f | 4h: NASH=%.4f E95=%.1f (n=%d, cic=%d)\n', ...
    metrics.teste.nash_2h, metrics.teste.e95_2h, metrics.teste.nash_4h, metrics.teste.e95_4h, ...
    metrics.teste.n, cic);
fprintf('Teto alinhado (Direct vs obs): 2h≈0.996 · 4h≈0.920 | full-test 4h≈0.9926 (26in)\n');
end

function dhat = forward_delta(X, Wh, bh, Ws, bs, be, ae, bu, au)
Pn = (X - be) ./ ae;
H = logsig(Pn * Wh' + bh');
Yn = logsig(H * Ws' + bs');
dhat = Yn .* au + bu;
end

function d = dunisig(a)
d = max(a .* (1 - a), 0.01);
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
