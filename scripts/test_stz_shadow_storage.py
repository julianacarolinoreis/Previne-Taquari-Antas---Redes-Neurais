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
