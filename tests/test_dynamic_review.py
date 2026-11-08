import importlib.util
from pathlib import Path

import numpy as np

spec=importlib.util.spec_from_file_location('dynamic_review',Path(__file__).resolve().parents[1]/'scripts/review_micah_dynamic.py')
review=importlib.util.module_from_spec(spec);spec.loader.exec_module(review)


def test_clock_fit_uses_lower_envelope_instead_of_python_delivery_bursts():
    native=np.arange(0,120,.01);offset=100+native*.00001
    delay=(np.arange(len(native))%100)/1000
    mapped,report=review.clock_fit(native,native+offset+delay)
    assert np.max(np.abs(mapped-(native+offset)))<.002
    assert not report['absolute_radio_latency_known']


def test_robust_reference_keeps_original_examples_but_quarantines_outlier():
    rng=np.random.default_rng(7);base=np.array([1.,2.,3.,2.,1.,0.])
    vectors=np.array([base+rng.normal(0,.03,6) for _ in range(30)]+[np.array([0.,0.,0.,0.,0.,10.])])
    vectors/=np.linalg.norm(vectors,axis=1)[:,None]
    core,agreement,threshold=review.consensus_templates(vectors)
    assert 30 not in core and len(agreement)==31
    assert len(core)>=20 and .65<=threshold<=1


def test_burst_descriptor_is_gain_invariant_and_rejects_incomplete_window():
    rms=np.zeros((30,8));rms[12:17]=np.array([1,2,3,2,1])[:,None]
    np.testing.assert_allclose(review.descriptor(rms,14),review.descriptor(rms*3,14))
    assert review.descriptor(rms,2) is None
