function net = rna_treina(Pt, Tt, Pv, Tv, par)
% RNA_TREINA  Treina a MLP 15-nh-1 (logsig/logsig) fiel a receita dos .mat
% do PREVINE (RNAPREV__SANTA_TEREZA__02h__ALT__15inputs_VFINAL_*).
%
% Recuperada de dentro do proprio .mat (function handles Ah/Dh/unisig/...):
%   ativacao   : logsig  a = 1./(1+exp(-n))
%   derivada   : max(a.*(1-a), 0.01)   (piso de 0.01, evita gradiente nulo)
%   otimizacao : gradiente descendente em lote, taxa adaptativa (estilo
%                traingda), momento Mom (0 no modelo entregue)
%   selecao    : nit reinicios aleatorios; fica o melhor pela VALIDACAO
%   parada     : paciencia sobre o erro de validacao
%
% Entradas JA NORMALIZADAS:
%   Pt (nin x Nt), Tt (1 x Nt)  -> treino
%   Pv (nin x Nv), Tv (1 x Nv)  -> validacao
%   par -> struct de config_rotacoes.m
%
% Saida: net.W1 (nh x nin) net.b1 (nh x 1) net.W2 (1 x nh) net.b2
%        net.ev_val  net.reinicio  net.hist(.EQ/.EV/.TX)
%
% Validado contra o modelo entregue: no split original reconstrutui
% teste MAE~5.0 / NASH~0.93 (entregue 4.55/0.948) -- receita fiel.
%
% >>> PLUGAR SEU TREINADOR ORIGINAL: para reproduzir EXATAMENTE os seus
% numeros, substitua o corpo desta funcao pela sua rotina, devolvendo os
% mesmos campos W1,b1,W2,b2. O restante do pipeline nao muda.

logsig = @(n) 1./(1+exp(-n));
dlog   = @(a) max(a.*(1-a), 0.01);

nin = size(Pt,1);  nh = par.nh;  Nt = size(Pt,2);
melhor_ev = inf;   net = struct();

for it = 1:par.nit
    rng(par.semente + it, 'twister');

    % --- inicializacao Nguyen-Widrow ---
    W1 = (rand(nh,nin)*2-1);
    W1 = W1 .* ((0.7*nh^(1/nin)) ./ sqrt(sum(W1.^2,2)));
    b1 = (rand(nh,1)*2-1) * 0.7 * nh^(1/nin);
    W2 = (rand(1,nh)-0.5);
    b2 = rand-0.5;

    lr = par.lr;
    dW1=zeros(nh,nin); db1=zeros(nh,1); dW2=zeros(1,nh); db2=0;

    % perf inicial no treino
    A1 = logsig(W1*Pt + b1);  A2 = logsig(W2*A1 + b2);  eq = mean((A2-Tt).^2);

    ev_best = inf;  sem_melhora = 0;  c_fim = 0;
    bW1=W1; bb1=b1; bW2=W2; bb2=b2;
    histEQ=zeros(par.Cic,1); histEV=zeros(par.Cic,1); histTX=zeros(par.Cic,1);

    for c = 1:par.Cic
        % --- gradiente no ponto atual (derivada com piso 0.01) ---
        E   = A2 - Tt;
        dO  = E .* dlog(A2);                 % 1 x Nt
        gW2 = (dO*A1')/Nt;   gb2 = mean(dO,2);
        dH  = (W2'*dO) .* dlog(A1);          % nh x Nt
        gW1 = (dH*Pt')/Nt;   gb1 = mean(dH,2);

        % --- passo de teste (momento + gradiente) ---
        dW1n = par.Mom*dW1 - lr*gW1;   dW2n = par.Mom*dW2 - lr*gW2;
        db1n = par.Mom*db1 - lr*gb1;   db2n = par.Mom*db2 - lr*gb2;
        W1t=W1+dW1n; b1t=b1+db1n; W2t=W2+dW2n; b2t=b2+db2n;

        % --- perf no passo de teste ---
        A1t = logsig(W1t*Pt + b1t);  A2t = logsig(W2t*A1t + b2t);
        eqt = mean((A2t-Tt).^2);

        if eqt > eq*1.04
            lr = lr*par.lr_dec;              % piorou: rejeita e reduz taxa
            dW1(:)=0; dW2(:)=0; db1(:)=0; db2=0;   % zera momento
        else
            W1=W1t; b1=b1t; W2=W2t; b2=b2t;  A1=A1t; A2=A2t;
            dW1=dW1n; db1=db1n; dW2=dW2n; db2=db2n;
            if eqt < eq, lr = lr*par.lr_inc; end
            eq = eqt;
        end
        lr = min(max(lr,1e-5),0.5);

        % --- validacao / parada antecipada ---
        A1v = logsig(W1*Pv + b1);  A2v = logsig(W2*A1v + b2);
        ev  = mean((A2v-Tv).^2);
        histEQ(c)=eq; histEV(c)=ev; histTX(c)=lr;  c_fim=c;

        if ev < ev_best*(1-par.Prc)
            ev_best = ev; sem_melhora = 0;
            bW1=W1; bb1=b1; bW2=W2; bb2=b2;
        else
            sem_melhora = sem_melhora + 1;
            if sem_melhora >= par.pac, break; end
        end
    end

    if ev_best < melhor_ev
        melhor_ev = ev_best;
        net.W1=bW1; net.b1=bb1; net.W2=bW2; net.b2=bb2;
        net.ev_val = ev_best;  net.reinicio = it;
        net.hist = struct('EQ',histEQ(1:c_fim),'EV',histEV(1:c_fim),'TX',histTX(1:c_fim));
    end
end
end
