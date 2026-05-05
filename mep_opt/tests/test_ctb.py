import pytest
from mep_opt.solver.irc37 import AxleLoadGroup, ctb_fatigue_life, check_ctb_adequacy

def test_ctb_low_stress_is_finite_not_capped():
    # The low-SR branch is no longer fabricated as infinite life.
    # Stress remains finite and should still produce a large but bounded life.
    life = ctb_fatigue_life(0.5, 1.4)
    assert life != float('inf')
    assert life > 1e6

def test_ctb_finite_life():
    # SR = 1.0 (sigma_t = 1.4). N = 10^((0.972 - 1.0)/0.0825) = 10^(-0.339..) = 0.45
    life = ctb_fatigue_life(1.4, 1.4)
    assert life < 1.0  # Fails almost instantly if SR = 1.0

    # SR = 0.8. N = 10^((0.972-0.8)/0.0825) = 10^(2.08) = roughly 121
    life = ctb_fatigue_life(1.4 * 0.8, 1.4)
    assert 100 < life < 150

def test_ctb_spectrum_adequacy():
    spectrum = [
        AxleLoadGroup("single", 100.0, 50.0),
        AxleLoadGroup("tandem", 180.0, 10.0),
        AxleLoadGroup("tridem", 240.0, 0.0)
    ]
    
    # 0.5 -> SR=0.35 -> inf allowable -> damage = 0
    # 1.12 -> SR=0.8 -> N ~ 121 allowable. applied=10. damage = 10/121 = 0.08
    # whatever -> applied=0 -> damage=0
    computed = [0.5, 1.12, 1.2]
    
    res = check_ctb_adequacy(spectrum, computed, 1.4)
    assert res['ctb_adequate'] == True
    assert 0.08 < res['CDF_ctb'] < 0.09
    
def test_ctb_spectrum_failure():
    spectrum = [
        AxleLoadGroup("single", 100.0, 500.0), # apply 500 times
    ]
    # SR=0.8. N_allowable ~ 121. applied = 500. damage = 500/121 > 1.0
    computed = [1.12]
    
    res = check_ctb_adequacy(spectrum, computed, 1.4)
    assert res['ctb_adequate'] == False
    assert res['CDF_ctb'] > 1.0
