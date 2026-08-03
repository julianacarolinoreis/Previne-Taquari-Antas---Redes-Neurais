function y = rna_forward(net, norm, X)
% RNA_FORWARD  Passagem direta da rede em unidades fisicas (cm de variacao).
%   net  -> struct com W1,b1,W2,b2 (de rna_treina)
%   norm -> struct com be,ae (z-score dos inputs) e au,bu (desnorm da saida)
%   X    -> (N x nin) em unidades fisicas
% Devolve y (N x 1): variacao prevista em 2h (cm). Nivel previsto = nivel_atual + y.
%
% Reproduz EXATAMENTE o forward gravado nos .mat do PREVINE
% (verificado: RMSE Python x .mat = 3.6e-14).
logsig = @(n) 1./(1+exp(-n));
Pn = (X - norm.be) ./ norm.ae;          % z-score (N x nin)
A1 = logsig(Pn*net.W1' + net.b1');      % N x nh
A2 = logsig(A1*net.W2' + net.b2);       % N x 1
y  = A2*norm.au + norm.bu;              % desnormaliza -> cm
end
