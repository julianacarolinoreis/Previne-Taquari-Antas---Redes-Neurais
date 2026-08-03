function q = pctl(x, p)
% PCTL  Percentil sem depender do Statistics Toolbox.
% Interpolacao linear no mesmo esquema do prctile do MATLAB.
%   x -> vetor de dados ; p -> escalar ou vetor de percentis (0..100)
x = sort(x(:));
n = numel(x);
if n==0, q = nan(size(p)); return; end
if n==1, q = repmat(x,size(p)); return; end
pos = (p(:)/100) * n + 0.5;          % posicoes (esquema do prctile)
pos = min(max(pos,1),n);
lo = floor(pos); hi = ceil(pos); fr = pos - lo;
q = x(lo).*(1-fr) + x(hi).*fr;
q = reshape(q, size(p));
end
