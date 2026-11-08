import numpy as np
from spelltrain.snap_only import RelativeBurstFeatures,SnapOnlyPredictor
from spelltrain.signals import DEFAULT_SIGNAL


class ConstantSnap:
    def window_scores(self,x):return np.full(len(x),.99)


def test_relative_burst_shape_is_invariant_to_uniform_signal_amplitude():
    x=np.arange(1,65,dtype=float).reshape(2,32)
    shape=RelativeBurstFeatures();np.testing.assert_allclose(shape.transform(x),shape.transform(x*10))
    augmented=RelativeBurstFeatures(True)
    assert augmented.transform(x).shape==(2,33)
    assert not np.allclose(augmented.transform(x)[:,-1],augmented.transform(x*10)[:,-1])


def test_standalone_predictor_uses_only_emg_and_clears_windows_on_sequence_loss():
    artifact={'task':'snap_only_emg','model':ConstantSnap(),'threshold':.9,'signal':dict(DEFAULT_SIGNAL)}
    a=SnapOnlyPredictor(artifact);b=SnapOnlyPredictor(artifact);events_a=[];events_b=[]
    rng=np.random.default_rng(10)
    for seq in range(100):
        packet={'source_seq':seq,'source_t':round((seq+1)*16/2048*1e6),'samples':rng.normal(30000,30,(16,8)).tolist()}
        events_a+=a.feed(packet)
        events_b+=b.feed({**packet,'hand_state':'fist','camera':'not consulted','received':999999})
    assert events_a==events_b
    assert all(r['kind'] in ('snap','snap_score') for r in events_a)
    assert len([r for r in events_a if r['kind']=='snap'])==1
    assert a.feed({**packet,'source_seq':1000})==[]
    assert not a.rearmed
