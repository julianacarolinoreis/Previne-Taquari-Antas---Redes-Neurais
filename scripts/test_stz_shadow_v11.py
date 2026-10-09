import copy
import datetime as dt
import unittest
from unittest.mock import patch
import h5py
import numpy as np
from scipy.special import expit
from previne.robo import gerar_sombra_stz_v11 as V
from previne.robo import stz_shadow_common as C
from previne.robo import stz_shadow_storage as S

class V11Test(unittest.TestCase):
    def setUp(self):
        self.contract=C.read(V.CONTRACT)
        self.base=dt.datetime(2026,10,8,20)
        self.now=self.base+dt.timedelta(minutes=90)
        self.levels={cod:{self.base-i*V.HOUR:500-i*2 for i in range(30)} for cod in C.STATIONS}
        self.rain={cod:{self.base-i*V.HOUR:1.0 for i in range(30)} for group in self.contract['chuvas'] for cod in group['estacoes']}

    def test_artifact_and_independent_historical_forward(self):
        path=C.ROOT/self.contract['mat']
        self.assertEqual(C.sha(path),self.contract['modelo_sha256'])
        with h5py.File(path) as f:
            x=np.asarray(f['Ptot'])
            ae=np.asarray(f['ae']).ravel();be=np.asarray(f['be']).ravel()
            wh=np.asarray(f['wh']);bh=np.asarray(f['bh']).ravel()
            ws=np.asarray(f['ws']).ravel();bs=float(np.asarray(f['bs']).ravel()[0])
            au=float(np.asarray(f['au']).ravel()[0]);bu=float(np.asarray(f['bu']).ravel()[0])
            ref=np.asarray(f['Tctot']).ravel()
        pred=expit(expit(((x-be)/ae)@wh+bh)@ws+bs)*au+bu
        self.assertEqual(x.shape,(2281,18))
        self.assertLess(float(abs(pred-ref).max()),1e-8)
        for i in (0,100,500,1000,1500,2000,2280):
            self.assertAlmostEqual(V.R.prever(str(path),x[i]),ref[i],places=8)

    def test_cascade_same_base_and_predicted_last_inputs(self):
        with patch.object(V.R,'prever',side_effect=[10,30]) as infer:
            p=V.forecast(self.levels,self.rain,self.now,self.contract)
        self.assertTrue(p['disponivel']);self.assertEqual(p['nivel_previsto_cm'],530)
        self.assertEqual(len(p['inputs']),18);self.assertEqual(p['inputs'][-2:],[10,510])
        self.assertEqual(len(infer.call_args_list[0].args[1]),15)
        self.assertEqual(p['cascata_2h']['hora_modelo'],p['hora_modelo'])
        self.assertLess(self.now,dt.datetime.fromisoformat(p['cascata_2h']['hora_alvo']))

    def test_future_observation_cannot_enter_cascade(self):
        a=V.forecast(self.levels,self.rain,self.now,self.contract)
        self.levels[C.STZ][self.base+2*V.HOUR]=2000
        b=V.forecast(self.levels,self.rain,self.now,self.contract)
        self.assertEqual(a['inputs'],b['inputs']);self.assertEqual(a['nivel_previsto_cm'],b['nivel_previsto_cm'])

    def test_missing_exact_level_and_expired_2h_target_block(self):
        del self.levels[C.STZ][self.base-12*V.HOUR]
        with patch.object(V.R,'prever') as infer:
            p=V.forecast(self.levels,self.rain,self.now,self.contract)
        self.assertFalse(p['disponivel']);infer.assert_not_called()
        self.assertFalse(V.forecast(self.levels,self.rain,self.base+2*V.HOUR,self.contract)['disponivel'])

    def test_hash_of_both_networks_is_checked(self):
        for key in ('modelo_sha256','cascata_2h'):
            c=copy.deepcopy(self.contract)
            if key=='cascata_2h':c[key]['modelo_sha256']='0'*64
            else:c[key]='0'*64
            with patch.object(V.R,'prever') as infer:p=V.forecast(self.levels,self.rain,self.now,c)
            self.assertEqual(p['status'],'BLOQUEADO_SHA256');infer.assert_not_called()

    def test_rain_hourly_average_partial_is_explicit_and_all_missing_blocks(self):
        self.rain['A894'].clear()
        p=V.forecast(self.levels,self.rain,self.now,self.contract)
        self.assertTrue(p['disponivel']);self.assertEqual(p['status'],'OK_SOMBRA_CHUVA_PARCIAL')
        self.assertEqual(p['inputs'][14:16],[12,15])
        self.assertEqual(p['cobertura_chuva'][1]['horas_por_posto']['A894'],0)
        for cod in self.contract['chuvas'][1]['estacoes']:self.rain[cod].pop(self.base,None)
        p=V.forecast(self.levels,self.rain,self.now,self.contract)
        self.assertFalse(p['disponivel']);self.assertIn(C.stamp(self.base),' '.join(p['inputs_faltantes']))

    def test_ana_quarter_hour_complete_and_duplicate_conflict(self):
        rows=[f'<row><DataHora>{C.stamp(self.base-dt.timedelta(minutes=i))}</DataHora><Chuva>1</Chuva></row>' for i in (0,15,30,45)]
        xml=lambda r:'<root>'+''.join(r)+'</root>'
        self.assertEqual(V.complete_ana_rain(xml(rows)),{self.base:4})
        self.assertEqual(V.complete_ana_rain(xml(rows[:-1])),{})
        self.assertEqual(V.complete_ana_rain(xml(rows+[rows[0].replace('<Chuva>1','<Chuva>2')])),{})

    def test_prospectively_frozen_cascade_and_scoring(self):
        p=V.forecast(self.levels,self.rain,self.now,self.contract)
        h=C.update_history(None,[p],{},self.now)
        altered=copy.deepcopy(h);altered['registros'][0]['cascata_2h']['delta_previsto_cm']+=1
        with self.assertRaises(ValueError):S.preserve(h,altered)
        target=self.base+4*V.HOUR
        h2=C.update_history(h,[],{target:550},target+dt.timedelta(minutes=1))
        S.preserve(h,h2);self.assertEqual(C.evaluate(h2['registros'],target)['total']['n'],1)

if __name__=='__main__':unittest.main()
