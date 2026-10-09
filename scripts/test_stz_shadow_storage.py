import copy
import datetime as dt
import gzip
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts import test_stz_shadow as baseline
from previne.robo import stz_shadow_common as C
from previne.robo import stz_shadow_storage as S
from previne.robo import gerar_sombra_stz_n5 as N

class StorageTest(unittest.TestCase):
    def setUp(self):
        setup=baseline.ShadowTest();setup.setUp()
        self.data=setup
        with patch.object(N.R,'prever',return_value=30):
            self.p=N.forecast(setup.levels,setup.rain,setup.now,setup.contract)
        self.empty={'schema_version':S.SCHEMA,'shadow_only':True,'registros':[]}
        self.hist=C.update_history(self.empty,[self.p],{},setup.now)

    def test_missing_and_wrong_schema_history_fail_closed(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'history.json'
            with self.assertRaises(FileNotFoundError):S.load(path)
            for invalid in (None,{},[],{'registros':[],'schema_version':'unknown'}):
                path.write_text(json.dumps(invalid),encoding='utf-8')
                with self.assertRaises(ValueError):S.load(path)

    def test_two_cycles_disk_reload_preserves_first_issue_and_exact_observation(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'history.json';C.write(path,self.hist)
            before=S.load(path)
            p=dict(self.p,nivel_previsto_cm=999)
            target=dt.datetime.fromisoformat(self.p['hora_alvo'])
            after=C.update_history(before,[p],{target:450},target+dt.timedelta(minutes=2))
            S.save(path,before,after)
            restored=S.load(path)
            self.assertEqual(len(restored['registros']),1)
            self.assertEqual(restored['registros'][0]['nivel_previsto_cm'],430)
            self.assertEqual(restored['registros'][0]['observado_cm'],450)
            self.assertIsNone(before['registros'][0]['observado_cm'])
            later=C.update_history(restored,[],{target:455},target+dt.timedelta(hours=1))
            S.preserve(restored,later)
            self.assertEqual(later['registros'][0]['observado_cm'],450)

    def test_destructive_history_and_duplicate_changes_are_rejected(self):
        for mode in ('delete','change','duplicate'):
            after=copy.deepcopy(self.hist)
            if mode=='delete':after['registros']=[]
            if mode=='change':after['registros'][0]['nivel_previsto_cm']=999
            if mode=='duplicate':after['registros']*=2
            with self.assertRaises(ValueError):S.preserve(self.hist,after)

    def test_invalid_observation_never_freezes_and_later_valid_one_can_score(self):
        target=dt.datetime.fromisoformat(self.p['hora_alvo']);now=target+dt.timedelta(minutes=1)
        for obs in (-332,0,3000):
            hist=C.update_history(self.hist,[],{target:obs},now)
            self.assertIsNone(hist['registros'][0]['observado_cm'])
        hist=C.update_history(self.hist,[],{target-dt.timedelta(hours=1):400,target:1500},now)
        self.assertIsNone(hist['registros'][0]['observado_cm'])
        hist=C.update_history(hist,[],{target:450},now)
        self.assertEqual(hist['registros'][0]['observado_cm'],450)

    def test_qc_blocks_post_jump_plateau_and_causal_flatline(self):
        t=self.data.base;limits=self.data.contract['limites_estacao_cm']
        raw={t:400,t+dt.timedelta(hours=1):1500,t+dt.timedelta(hours=2):1500,t+dt.timedelta(hours=3):410}
        clean=C.qc_levels({C.STZ:raw},limits)[C.STZ]
        self.assertNotIn(t+dt.timedelta(hours=2),clean)
        self.assertIn(t+dt.timedelta(hours=3),clean)
        raw={t+dt.timedelta(hours=i):400 for i in range(160)}
        clean=C.qc_levels({C.STZ:raw},limits)[C.STZ]
        self.assertIn(t+dt.timedelta(hours=72),clean)
        self.assertNotIn(t+dt.timedelta(hours=73),clean)

    def test_conflicting_duplicates_and_invalid_hourly_rain_are_not_partial_totals(self):
        rows=['<row><DataHora>2026-10-08T19:00:00</DataHora><Nivel>400</Nivel><Chuva>1</Chuva></row>',
              '<row><DataHora>2026-10-08T19:00:00</DataHora><Nivel>500</Nivel><Chuva>2</Chuva></row>']
        for ordered in (rows,rows[::-1]):
            levels,rain=C.parse_xml(('<root>'+''.join(ordered)+'</root>').encode())
            self.assertEqual(levels,{})
            self.assertEqual(rain,{})
        rows=[f'<row><DataHora>{t}</DataHora><Chuva>45</Chuva></row>' for t in ('2026-10-08T18:15:00','2026-10-08T18:30:00','2026-10-08T18:45:00','2026-10-08T19:00:00')]
        self.assertEqual(C.parse_xml(('<root>'+''.join(rows)+'</root>').encode())[1],{})
        rows[0]=rows[0].replace('45','101')
        self.assertEqual(C.parse_xml(('<root>'+''.join(rows)+'</root>').encode())[1],{})
        for invalid in ('NaN','inf','erro'):
            rows[0]=f'<row><DataHora>2026-10-08T18:15:00</DataHora><Chuva>{invalid}</Chuva></row>'
            self.assertEqual(C.parse_xml(('<root>'+''.join(rows)+'</root>').encode())[1],{})

    def test_archive_retains_unavailable_inputs_and_telemetry_and_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);now=self.data.now
            predictions=[self.p,dict(self.p,disponivel=False,status='ENTRADAS_INCOMPLETAS')]
            info=S.archive('n5',now,predictions,self.data.levels,self.data.rain,self.empty,self.hist,root)
            file=root/info['arquivo'].split('assets/data/stz_shadow_archive/')[1]
            original=file.read_bytes();saved=json.loads(gzip.decompress(original))
            self.assertEqual(len(saved['previsoes']),2)
            self.assertEqual(saved['previsoes'][0]['inputs'],self.p['inputs'])
            self.assertIn(C.STZ,saved['telemetria']['nivel'])
            self.assertEqual(saved['historico_inicial'],self.empty)
            S.archive('n5',now,predictions,self.data.levels,self.data.rain,self.empty,self.hist,root)
            self.assertEqual(file.read_bytes(),original)
            from scripts.recover_stz_shadow_history import recover
            self.assertEqual(recover(root,'n5'),self.hist)
            (root/'index.json').unlink()
            with self.assertRaises(ValueError):S.archive('n5',now+dt.timedelta(minutes=30),predictions,self.data.levels,self.data.rain,self.empty,self.hist,root)
            with self.assertRaises(ValueError):S.archive('n5',now,[],{},{},self.empty,self.hist,root)
            self.assertEqual(file.read_bytes(),original)

    def test_atomic_write_failure_leaves_original_history_bytes(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'history.json';C.write(path,self.hist);before=path.read_bytes()
            with patch.object(Path,'replace',side_effect=OSError('disk unavailable')):
                with self.assertRaises(OSError):C.write(path,self.empty)
            self.assertEqual(path.read_bytes(),before)

    def test_all_52_live_predictions_can_be_reproduced_from_saved_inputs(self):
        import numpy as np
        import joblib
        from previne.robo import gerar_sombra_stz_usuario as U
        from previne.robo.stz_model_architectures import predict_numpy
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);history=root/'history.json';out=root/'feed.json'
            C.write(history,self.empty)
            with patch.object(U,'HISTORY',history),patch.object(U,'OUT',out),patch.object(S,'ARCHIVE',root/'archive'):
                U.main((self.data.levels,self.data.rain),self.data.now)
            feed=C.read(out);stored=S.load(history)
            self.assertEqual(len(stored['registros']),52)
            models={m['id']:m for m in C.read(U.MANIFEST)['models']}
            for p in feed['modelos']:
                self.assertTrue(p['disponivel'])
                m=models[p['modelo_id']];x=np.asarray(p['inputs'],dtype=np.float32);path=C.ROOT/m['path']
                delta=float(predict_numpy(path,m['name'],x[None])[0]) if m['family']=='temporal' else float(joblib.load(path).predict(x[-1:])[0])
                self.assertAlmostEqual(p['nivel_previsto_cm'],p['nivel_base_cm']+delta,places=7)
                self.assertEqual(len(p['inputs_horas']),m['lookback_h'])
                self.assertEqual(len(p['inputs_nomes']),11)
            archive_path=root/'archive'/feed['arquivo_emissao']['arquivo'].split('assets/data/stz_shadow_archive/')[1]
            archived=json.loads(gzip.decompress(archive_path.read_bytes()))
            self.assertEqual(len(archived['alteracoes_historico']),52)

    def multi_month_history(self):
        rows=[]
        for i,issued in enumerate(('2026-10-31T23:47:00','2026-11-01T00:17:00','2026-11-01T01:17:00')):
            t=dt.datetime.fromisoformat(issued).replace(minute=0)
            rows.append(dict(self.p,emitida_em=issued,hora_modelo=C.stamp(t),hora_alvo=C.stamp(t+dt.timedelta(hours=4)),
                             nivel_previsto_cm=430+i,origem='emissao_prospectiva',observado_cm=None))
        return {'schema_version':S.SCHEMA,'shadow_only':True,'registros':rows,'atualizado_em':'2026-11-01T01:17:00'}

    def test_legacy_history_migrates_to_monthly_partitions_in_insertion_order(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);legacy=root/'historico.json';parts=root/'hist'
            hist=self.multi_month_history();C.write(legacy,hist)
            before=S.load(parts,legacy);self.assertEqual(before,hist)
            files=S.save(parts,before,before,legacy)
            self.assertEqual([f.name for f in files],['2026-10.json','2026-11.json'])
            self.assertFalse(legacy.exists())
            self.assertEqual(S.load(parts,legacy)['registros'],hist['registros'])
            lines=(parts/'2026-11.json').read_text(encoding='utf-8').splitlines()
            self.assertEqual(len(lines),4)  # cabecalho, dois registros, fechamento
            with self.assertRaises(FileNotFoundError):S.load(root/'vazio',root/'nao_existe.json')

    def test_partitions_never_drop_months_or_records(self):
        with tempfile.TemporaryDirectory() as d:
            parts=Path(d)/'hist';hist=self.multi_month_history()
            S.save(parts,hist,hist)
            fewer=copy.deepcopy(hist);fewer['registros']=fewer['registros'][1:]
            with self.assertRaises(ValueError):S.save(parts,hist,fewer)
            moved=copy.deepcopy(hist);moved['registros'][0]['emitida_em']='2026-11-01T00:00:00'
            (parts/'2026-10.json').write_text(S.render_partition('2026-10',moved['registros'][:1],'x'),encoding='utf-8')
            with self.assertRaises(ValueError):S.load(parts)

    def test_publication_validator_reads_committed_partitions_after_migration(self):
        import subprocess
        from scripts.validate_stz_shadow_storage import git_history
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);legacy=root/'historico.json';parts=root/'hist'
            git=lambda *a:subprocess.run(['git','-c','user.name=t','-c','user.email=t@t',*a],cwd=root,check=True,capture_output=True)
            git('init','-q')
            hist=self.multi_month_history();C.write(legacy,hist)
            git('add','-A');git('commit','-qm','legado')
            self.assertEqual(git_history(parts,legacy,root)['registros'],hist['registros'])
            S.save(parts,S.load(parts,legacy),S.load(parts,legacy),legacy)
            git('add','-A');git('commit','-qm','particoes')
            self.assertFalse(legacy.exists())
            before=git_history(parts,legacy,root)
            self.assertEqual(before['registros'],hist['registros'])
            S.preserve(before,S.load(parts,legacy))
            git('rm','-rq','hist');git('commit','-qm','apaga')
            with self.assertRaises(FileNotFoundError):git_history(parts,legacy,root)

    def test_user_feed_is_slim_and_only_charts_current_model_versions(self):
        from previne.robo import gerar_sombra_stz_usuario as U
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);history=root/'history.json';out=root/'feed.json'
            old=dict(self.p,modelo_id='h4_Ridge',modelo_sha256='0'*64,emitida_em=C.stamp(self.data.now-dt.timedelta(hours=1)))
            C.write(history,dict(self.empty,registros=[dict(old,origem='emissao_prospectiva',observado_cm=None)]))
            with patch.object(U,'HISTORY',history),patch.object(U,'OUT',out),patch.object(S,'ARCHIVE',root/'archive'):
                U.main((self.data.levels,self.data.rain),self.data.now)
            text=out.read_text(encoding='utf-8');feed=json.loads(text)
            self.assertNotIn('\n  ',text)
            self.assertEqual(len(feed['serie_recente']),52)
            self.assertTrue(all(set(r)=={'modelo_id','hora_alvo','nivel_previsto_cm','observado_cm'} for r in feed['serie_recente']))
            self.assertTrue(all('mae_cm' in p['teste_historico'] for p in feed['modelos']))
            self.assertNotIn('teste_historico',S.load(history)['registros'][-1])
            self.assertEqual(feed['historico_registros_n'],53)

    def test_partial_failure_isolated_and_one_shared_collection(self):
        from previne.robo import executar_sombra_stz as E
        data=(self.data.levels,self.data.rain)
        with patch.object(S,'load',return_value=self.empty),patch.object(C,'download',return_value=data) as download,patch.object(N,'main',side_effect=RuntimeError('failure')) as n5,patch.object(E.U,'main',return_value=0) as user:
            self.assertEqual(E.main(),1)
            self.assertEqual(download.call_count,1)
            self.assertEqual(n5.call_args.args,user.call_args.args)
        with patch.object(S,'load',side_effect=FileNotFoundError('history')),patch.object(C,'download') as download:
            with self.assertRaises(FileNotFoundError):E.main()
            download.assert_not_called()

if __name__=='__main__':unittest.main()
