import copy
import datetime as dt
import unittest
from unittest.mock import patch
import numpy as np
from scipy.io import loadmat
from scipy.special import expit
from previne.robo import stz_shadow_common as C
from previne.robo import gerar_sombra_stz_n5 as N

class ShadowTest(unittest.TestCase):
    def setUp(self):
        self.now=dt.datetime(2026,10,8,19,45)
        self.base=self.now.replace(hour=19,minute=0)
        self.levels={C.STZ:{self.base-dt.timedelta(hours=i):400-i for i in range(30)}}
        self.rain={c:{self.base-dt.timedelta(hours=i):1.0 for i in range(30)} for c in C.STATIONS}
        self.contract=C.read(N.CONTRACT)
        self.specs=self.contract['horizontes']['4h']['modelos'][0]['inputs']

    def test_n5_artifact_and_all_stored_outputs(self):
        m=self.contract['horizontes']['4h']['modelos'][0];p=C.ROOT/m['mat']
        self.assertEqual(C.sha(p),m['modelo_sha256'])
        data=loadmat(p,squeeze_me=True)
        x=np.loadtxt(C.ROOT/'assets/data/stz_user_models/training_n5.csv',delimiter=';',skiprows=1)[:,:11]
        pred=expit(expit(((x-data['be'])/data['ae'])@data['wh'].T+data['bh'])@data['ws']+data['bs'])*data['au']+data['bu']+x[:,0]
        self.assertLess(float(abs(pred-data['Tctot1']).max()),1e-5)

    def test_n5_has_no_castro_or_2h_model_dependency(self):
        m=self.contract['horizontes']['4h']['modelos'][0]
        self.assertNotIn('86298000',m['estacoes_nivel']+m['estacoes_chuva'])
        self.assertEqual(m['n_inputs'],11)
        with patch.object(N.R,'prever',return_value=30) as inference:
            p=N.forecast(self.levels,self.rain,self.now,self.contract)
        self.assertTrue(p['disponivel']);self.assertEqual(p['nivel_previsto_cm'],430)
        self.assertEqual(inference.call_count,1)
        self.assertIn('STZ_4H_N5',inference.call_args.args[0])

    def test_precipitation_is_right_labelled_and_duplicates_not_doubled(self):
        xml=b'<root><row><DataHora>2026-10-08T18:45:00</DataHora><Chuva>2</Chuva></row><row><DataHora>2026-10-08T19:00:00</DataHora><Chuva>3</Chuva></row><row><DataHora>2026-10-08T19:00:00</DataHora><Chuva>3</Chuva></row></root>'
        _,rain=C.parse_xml(xml)
        self.assertEqual(rain,{self.base:5})

    def test_rain_average_requires_complete_window_per_station(self):
        del self.rain['86472000'][self.base-dt.timedelta(hours=2)]
        self.rain[C.STZ][self.base]=7
        x,missing=C.inputs(self.specs,self.levels,self.rain,self.base)
        self.assertFalse(missing);self.assertEqual(x[-2],12)
        del self.rain[C.STZ][self.base-dt.timedelta(hours=2)]
        _,missing=C.inputs(self.specs,self.levels,self.rain,self.base)
        self.assertIn('chuvaG_LOCAL_acum_6h',missing)

    def test_missing_hour_is_not_replaced_with_neighbour(self):
        del self.levels[C.STZ][self.base-dt.timedelta(hours=12)]
        self.levels[C.STZ][self.base-dt.timedelta(hours=12,minutes=15)]=388
        _,missing=C.inputs(self.specs,self.levels,self.rain,self.base)
        self.assertIn('Acel-12h_86472600',missing)
        self.assertIsNone(C.recent_base(self.specs,self.levels,self.rain,self.now+dt.timedelta(hours=4))[0])

    def test_wrong_hash_blocks_inference(self):
        c=copy.deepcopy(self.contract);c['horizontes']['4h']['modelos'][0]['modelo_sha256']='0'*64
        with patch.object(N.R,'prever') as infer:
            p=N.forecast(self.levels,self.rain,self.now,c)
        self.assertFalse(p['disponivel']);infer.assert_not_called()
        self.assertEqual(C.update_history(None,[p],{},self.now)['registros'],[])

    def test_history_freezes_first_issue_and_scores_only_after_target(self):
        with patch.object(N.R,'prever',return_value=30):p=N.forecast(self.levels,self.rain,self.now,self.contract)
        hist=C.update_history(None,[p],{},self.now)
        other=dict(p,nivel_previsto_cm=999)
        hist=C.update_history(hist,[other],{},self.now)
        self.assertEqual(len(hist['registros']),1)
        self.assertEqual(hist['registros'][0]['nivel_previsto_cm'],430)
        target=dt.datetime.fromisoformat(p['hora_alvo'])
        hist=C.update_history(hist,[],{target:450},target-dt.timedelta(minutes=1))
        self.assertIsNone(hist['registros'][0]['observado_cm'])
        hist=C.update_history(hist,[],{target:450},target+dt.timedelta(minutes=1))
        self.assertEqual(hist['registros'][0]['erro_cm'],-20)
        self.assertEqual(C.metrics(hist['registros'],target+dt.timedelta(minutes=1))['mae_cm'],20)
        retro=dict(p,emitida_em=C.stamp(target),hora_modelo='2026-10-08T18:00:00')
        self.assertEqual(len(C.update_history(None,[retro],{},target)['registros']),0)

    def test_training_context_and_event_holdout_are_disjoint(self):
        from scripts.build_stz_user_shadow_models import dataset
        for h in (2,4,8,12):
            x,y,s,base,e,t=dataset(h)
            self.assertEqual(x.shape[1:],(4,11));self.assertGreater(len(y),1000)
            sets=[set(e[s==k]) for k in (1,2,3)]
            self.assertFalse(sets[0]&sets[1] or sets[0]&sets[2] or sets[1]&sets[2])

    def test_complete_frozen_model_inventory_and_hashes(self):
        m=C.read(C.ROOT/'assets/data/stz_user_models/manifest.json')
        self.assertEqual(len(m['models']),52)
        self.assertEqual(len({p['id'] for p in m['models']}),52)
        for h in (2,4,8,12):
            self.assertEqual(len([p for p in m['models'] if p['horizon_h']==h]),13)
        for p in m['models']:
            self.assertEqual(C.sha(C.ROOT/p['path']),p['sha256'])
            self.assertLess(p['export_max_error_cm'],0.002)
        self.assertEqual(C.sha(C.ROOT/'assets/data/stz_user_models/training_n5.csv'),m['source_sha256'])
        self.assertEqual(C.sha(C.ROOT/'assets/data/stz_user_models/training_n5_meta.csv'),m['source_meta_sha256'])

    def test_calibration_converged_and_svr_target_is_standardized(self):
        import joblib
        from sklearn.compose import TransformedTargetRegressor
        m=C.read(C.ROOT/'assets/data/stz_user_models/manifest.json')
        temporal=[p for p in m['models'] if p['family']=='temporal']
        self.assertEqual(len(temporal),24)
        for p in temporal:
            candidates=p['validation_mse_scaled_candidates']
            self.assertEqual(p['protocol'],min(candidates,key=candidates.get),p['id'])
            if p['protocol']=='r2_minibatch':
                self.assertTrue(p['stopped_by_validation'],p['id'])
                self.assertLess(p['best_epoch'],m['temporal_training']['max_epochs']-m['temporal_training']['patience_epochs']+1,p['id'])
        for p in m['models']:
            if p['name']=='SVR':
                self.assertIsInstance(joblib.load(C.ROOT/p['path']),TransformedTargetRegressor)
        ref=m['reference_n5_test']
        self.assertEqual(ref['n'],m['datasets']['4']['n_test'])
        self.assertEqual(ref['modelo_sha256'],self.contract['horizontes']['4h']['modelos'][0]['modelo_sha256'])

    def test_public_and_user_interfaces_have_separate_panels(self):
        public=(C.ROOT/'santa_tereza_previsao_inundacao.html').read_text(encoding='utf-8')
        user=(C.ROOT/'santa_tereza_previsao_inundacao_usuario.html').read_text(encoding='utf-8')
        self.assertNotIn('id="stz-shadow-v11"',public)
        self.assertNotIn('id="stz-shadow-n5"',public)
        self.assertNotIn('id="stz-shadow-user"',public)
        self.assertIn('id="stz-shadow-user"',user)
        self.assertNotIn('id="stz-shadow-n5"',user)

if __name__=='__main__':unittest.main()
