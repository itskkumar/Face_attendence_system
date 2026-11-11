import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import pad_eval as P


def test_apcer_bpcer_hand_computed():
    live, spoof = [0.9, 0.8, 0.4, 0.95], [0.1, 0.75, 0.2, 0.3]
    a, b = P.apcer_bpcer(live, spoof, 0.7)
    assert a == 0.25 and b == 0.25


def test_empty_class_is_none_not_zero():
    assert P.apcer_bpcer([], [0.9], 0.5) == (1.0, None)
    assert P.apcer_bpcer([0.9], [], 0.5) == (None, 0.0)


def test_sweep_is_monotone():
    s = P.sweep([0.2, 0.6, 0.9], [0.1, 0.5, 0.8])
    apcers = [x[1] for x in s]; bpcers = [x[2] for x in s]
    assert apcers == sorted(apcers, reverse=True) and bpcers == sorted(bpcers)
