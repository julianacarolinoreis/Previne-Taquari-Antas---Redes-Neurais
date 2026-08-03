function salva_mat(caminho, net, norm, li, ls, f, cfg, X, alvo, serie, y, M, nome)
% SALVA_MAT  Grava o .mat no mesmo formato dos RNAPREV__* do PREVINE.
% Campos-chave (compativeis com o forward ja em producao):
%   wh (nh x nin)  bh (1 x nh)  ws (nh x 1)  bs
%   ae be (1 x nin)  au bu li ls f  input nh Cic nit Mom
%   DADOS/treina/valida/verifica  (n x nin+1, ultima coluna = alvo)
%   metricas NASH/PERS/e95/emed_abs + RESULTS + g/p (quantis do erro no teste)

wh = net.W1;            % nh x nin
bh = net.b1';           % 1 x nh
ws = net.W2';           % nh x 1
bs = net.b2;            % escalar
ae = norm.ae;  be = norm.be;  au = norm.au;  bu = norm.bu;
input = cfg.n_input;  nh = cfg.par.nh;
Cic = cfg.par.Cic;  nit = cfg.par.nit;  Mom = cfg.par.Mom;

D = [X alvo];
DADOS   = D';                       % (nin+1) x N   (orientacao MATLAB)
treina  = D(serie==1,:)';
valida  = D(serie==2,:)';
verifica= D(serie==3,:)';

% metricas do TESTE (M(4)) para o cabecalho, como nos .mat originais
NASH = M(4).NASH;  PERS = M(4).PERS;  e95 = M(4).E95;
emed_abs = M(4).MAE;  emed_abs_mean = M(2).MAE;
et = abs( y(serie==3) - alvo(serie==3) );
p = [50 80 90 95 99 100];  g = pctl(et,p)';
RESULTS = [NASH PERS 0 0 emed_abs e95];

EXCEL = cfg.xlsx;  PLAN = cfg.plan;  MODELO = nome;
hist = net.hist;   reinicio = net.reinicio;

save(caminho, 'wh','bh','ws','bs','ae','be','au','bu','li','ls','f', ...
     'input','nh','Cic','nit','Mom','DADOS','treina','valida','verifica', ...
     'NASH','PERS','e95','emed_abs','emed_abs_mean','g','p','RESULTS', ...
     'EXCEL','PLAN','MODELO','hist','reinicio','-v7.3');
end
