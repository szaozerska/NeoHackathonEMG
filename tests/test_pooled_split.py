import numpy as np

from spelltrain.neural import row_weights
from spelltrain.neural_data import assign_parts, drop_cross_split_overlaps
from spelltrain.training_selection import select


def test_assign_parts_holds_out_every_part_and_is_seeded():
    units = [(i, None) for i in range(20)]
    a = assign_parts(units, np.random.default_rng(1)); b = assign_parts(units, np.random.default_rng(1))
    assert a == b
    counts = {p: list(a.values()).count(p) for p in ('train', 'validation', 'test')}
    assert counts == {'train': 14, 'validation': 3, 'test': 3}
    assert set(assign_parts(units[:2], np.random.default_rng(0)).values()) == {'train'}


def test_windows_straddling_a_split_boundary_are_dropped():
    row = lambda s, part: {'session': 'x', 'part': part, 'start': s, 'end': s+.4, 'group': part, 'label': 'fist'}
    data = {'tasks': {'state': [row(0, 'train'), row(.5, 'train'), row(.7, 'test'), row(1.5, 'test')], 'snap': []}}
    drop_cross_split_overlaps(data)
    assert [(r['start'], r['part']) for r in data['tasks']['state']] == [(0, 'train'), (1.5, 'test')]


def test_row_weights_balance_people_within_each_class():
    rows = [{'group': f'm{i}', 'label': 'fist', 'wearing_session': 'micah'} for i in range(9)]
    rows += [{'group': 'k0', 'label': 'fist', 'wearing_session': 'ken'}]
    w = row_weights(rows)
    assert np.isclose(w[-1], w[:-1].sum())


def test_training_selection_drops_short_clipped_and_double_snaps():
    base = {'filter_kept': True, 'filter_reasons': [], 'effort': None, 'clipped_share': 0., 'median': 1.,
            'peak': 10., 'bursts': 1, 'pattern': [0, 1, 2, 3, 4, 5, 6, 7]}
    rows = [{**base, 'index': 0, 'motion': 'non_intended', 'start': 0, 'end': 1},
            {**base, 'index': 1, 'motion': 'snap', 'start': 1, 'end': 2},
            {**base, 'index': 2, 'motion': 'snap', 'start': 2, 'end': 2.5},
            {**base, 'index': 3, 'motion': 'snap', 'start': 3, 'end': 4, 'bursts': 2},
            {**base, 'index': 4, 'motion': 'sword_hold', 'start': 4, 'end': 5, 'clipped_share': .3},
            {**base, 'index': 5, 'motion': 'sword_hold', 'start': 5, 'end': 6},
            {**base, 'index': 6, 'motion': 'snap', 'start': 6, 'end': 7, 'filter_kept': False,
             'filter_reasons': ['no snap peak']}]
    out = {r['index']: r['train_eligible'] for r in select(rows)}
    assert out == {0: True, 1: True, 2: False, 3: False, 4: False, 5: True, 6: False}
