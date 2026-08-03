function escreve_auditavel(caminho, cfg, nome, evento, serie, data6, X, alvo, ...
                           nivel_atual, observado, y, rna_nivel, M)
% ESCREVE_AUDITAVEL  Gera o Excel auditavel no MESMO layout de
% assets/audit_workbooks/*_AUDITAVEL_INPUTS_RNA.xlsx (6 abas).
%
% Abas: DADOS | INPUTS | METADADOS | COMPLETUDE_EVENTOS | METRICAS
% (LACUNAS_POR_COLUNA e omitida: a planilha VAR ja vem sem lacunas).

if exist(caminho,'file'), delete(caminho); end
rotulo = {'Treino','Validacao','Teste'};
N = numel(alvo);

% ------------------------------------------------------------- aba DADOS ----
erro     = y - alvo;                 % ALT_RNA - ALT_OBS (variacao)
e2_rna   = erro.^2;
e2_pers  = alvo.^2;                  % persistencia preve variacao 0
conj = reshape(rotulo(serie), N, 1); % rotulo textual por linha (coluna Nx1)

vN = arrayfun(@(k) sprintf('inp%02d',k), 1:cfg.n_input, 'uni',0);
Ddata = [ num2cell(evento) num2cell(serie) conj ...
          num2cell(data6) ...
          num2cell(X) ...
          num2cell(alvo) num2cell(nivel_atual) num2cell(observado) ...
          num2cell(rna_nivel) num2cell(alvo) num2cell(y) ...
          num2cell(erro) num2cell(abs(erro)) num2cell(e2_rna) ...
          num2cell(nivel_atual) num2cell(e2_pers) ...
          num2cell(serie) conj ];
cab = [{'EVENTO','SERIE','CONJUNTO','ANO','MES','DIA','HORA','MINUTO','COD_SEQUENCIAL'} ...
       vN {'saida_2h_alt_nivel_D2h','NIVEL_ATUAL_CM','OBSERVADO_CM_AUDITORIA', ...
       'RNA_CM','ALT_OBSERVADA_CM','ALT_RNA_CM','ERRO_RNA_CM','ERRO_ABS_CM', ...
       'E2_RNA','PERS_BASE_NIVEL_ATUAL_CM','E2_PERS','SERIE_AUDITORIA','CONJUNTO_AUDITORIA'}];
writecell([cab; Ddata], caminho, 'Sheet','DADOS');

% ------------------------------------------------------------ aba INPUTS ----
letras = arrayfun(@(k) col_letra(7+k), 1:cfg.n_input, 'uni',0);  % H,I,...
Inp = [{'seq','coluna','nome','base_persistencia'}];
for k=1:cfg.n_input
    Inp(end+1,:) = {k, letras{k}, cfg.nomes_input{k}, ternario(k==1,'SIM','')}; %#ok<AGROW>
end
writecell(Inp, caminho, 'Sheet','INPUTS');

% --------------------------------------------------------- aba METADADOS ----
Meta = {
  'campo','valor'
  'modelo', nome
  'combo_id','2H_ALT_15inputs'
  'target','2h_alt'
  'horizonte','2h'
  'tipo','alt'
  'n_inputs', cfg.n_input
  'neuronios', cfg.par.nh
  'nit', cfg.par.nit
  'ciclos', cfg.par.Cic
  'momento', cfg.par.Mom
  'taxa_lr', cfg.par.lr
  'folga_f', cfg.par.f
  'fonte_dados', cfg.xlsx
  'aba', cfg.plan
  'alvo_nome','saida_2h_alt_nivel_D2h_86472600'
  'base_persistencia','nivel atual (input_01)'
  'gerado_em', datestr(now,'yyyy-mm-dd HH:MM:SS')
};
writecell(Meta, caminho, 'Sheet','METADADOS');

% ------------------------------------------------- aba COMPLETUDE_EVENTOS ---
evs = unique(evento);
Comp = {'EVENTO','SERIE','CONJUNTO','linhas'};
for i=1:numel(evs)
    s = evento==evs(i);  sr = serie(find(s,1));
    Comp(end+1,:) = {evs(i), sr, rotulo{sr}, sum(s)}; %#ok<AGROW>
end
writecell(Comp, caminho, 'Sheet','COMPLETUDE_EVENTOS');

% ---------------------------------------------------------- aba METRICAS ----
Met = {
  'modelo', nome, '', '', '', '', ''
  'inputs', cfg.n_input, '', '', '', '', ''
  'neuronios', cfg.par.nh, '', '', '', '', ''
  'nit', cfg.par.nit, '', '', '', '', ''
  'ciclos', cfg.par.Cic, '', '', '', '', ''
  'base_persistencia','nivel atual / input 1','', '', '', '', ''
  '','','','','','',''
  'conjunto','N','PERS','MAE','E95','SOMA_E2_RNA','SOMA_E2_PERS'
};
for k=1:4
    Met(end+1,:) = {M(k).conjunto, M(k).N, M(k).PERS, M(k).MAE, M(k).E95, ...
                    M(k).SOMA_E2_RNA, M(k).SOMA_E2_PERS}; %#ok<AGROW>
end
Met(end+1,:) = {'NASH_teste', M(4).NASH, '', '', '', '', ''};
writecell(Met, caminho, 'Sheet','METRICAS');
end

% ------------------------------------------------------------- utilitarios --
function s = col_letra(n)
s='';
while n>0, r=mod(n-1,26); s=[char(65+r) s]; n=floor((n-1)/26); end
end
function o = ternario(c,a,b), if c, o=a; else, o=b; end, end
