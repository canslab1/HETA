#!/usr/bin/env python3
"""Verify all nets/ networks match expected results."""
import sys, os, warnings
warnings.filterwarnings('ignore')
sys.path.insert(0, os.path.dirname(__file__))
from heta.engine import run_link_analysis

NETS_DIR = os.path.join(os.path.dirname(__file__), 'nets')

EXPECTED = {
    'Ragusa16':    {'BOND': 19, 'SINK': 5,  'LOCAL': 35,   'GLOBAL': 9},
    'ba_sfn':      {'BOND': 19, 'SINK': 0,  'LOCAL': 41,   'GLOBAL': 136},
    'camp92':      {'BOND': 18, 'SINK': 0,  'LOCAL': 12,   'GLOBAL': 5},
    'celegans':    {'BOND': 351,'SINK': 15, 'LOCAL': 1466,  'GLOBAL': 316},
    'dolphins':    {'BOND': 40, 'SINK': 9,  'LOCAL': 81,   'GLOBAL': 29},
    'florentine':  {'BOND': 1,  'SINK': 4,  'LOCAL': 7,    'GLOBAL': 8},
    'football':    {'BOND': 420,'SINK': 0,  'LOCAL': 97,   'GLOBAL': 96},
    'jazz':        {'BOND':1882,'SINK': 5,  'LOCAL': 728,  'GLOBAL': 127},
    'k-core':      {'BOND': 9,  'SINK': 14, 'LOCAL': 4,    'GLOBAL': 4},
    'karate':      {'BOND': 28, 'SINK': 1,  'LOCAL': 38,   'GLOBAL': 11},
    'leader':      {'BOND': 7,  'SINK': 0,  'LOCAL': 59,   'GLOBAL': 14},
    'lesmis':      {'BOND': 150,'SINK': 17, 'LOCAL': 68,   'GLOBAL': 19},
    'prisonInter': {'BOND': 63, 'SINK': 4,  'LOCAL': 25,   'GLOBAL': 50},
    'rdgam':       {'BOND': 22, 'SINK': 0,  'LOCAL': 5,    'GLOBAL': 1},
    's208':        {'BOND': 48, 'SINK': 9,  'LOCAL': 78,   'GLOBAL': 54},
    'women':       {'BOND': 38, 'SINK': 0,  'LOCAL': 9,    'GLOBAL': 3},
}

net_files = sorted([
    f for f in os.listdir(NETS_DIR)
    if f.endswith('.net') and '_result' not in f and f != 'test_tree.net'
])

all_match = True
for net in net_files:
    path = os.path.join(NETS_DIR, net)
    name = net.replace('.net', '')
    r = run_link_analysis(path, times=100, debug=False)[0]
    actual = {'BOND': r.bond_count, 'SINK': r.sink_count,
              'LOCAL': r.local_bridge_count, 'GLOBAL': r.global_bridge_count}
    exp = EXPECTED.get(name, {})
    ok = actual == exp
    if not ok:
        all_match = False
    status = '✅' if ok else '❌'
    print(f'{status} {name:20s}  BOND={r.bond_count:4d}  SINK={r.sink_count:3d}  '
          f'LOCAL={r.local_bridge_count:4d}  GLOBAL={r.global_bridge_count:4d}')
    if not ok:
        for k in ['BOND','SINK','LOCAL','GLOBAL']:
            if actual[k] != exp.get(k):
                print(f'     {k}: expected={exp.get(k)}, got={actual[k]}')

print()
r = run_link_analysis('nets/test_tree.net', times=10, debug=False)[0]
tree_ok = (r.bond_count == 0 and r.sink_count == 8 and
           r.local_bridge_count == 0 and r.global_bridge_count == 6)
status = '✅' if tree_ok else '❌'
print(f'{status} {"test_tree":20s}  BOND={r.bond_count:4d}  SINK={r.sink_count:3d}  '
      f'LOCAL={r.local_bridge_count:4d}  GLOBAL={r.global_bridge_count:4d}')

print()
if all_match and tree_ok:
    print('ALL 17 NETWORKS PASS')
else:
    print('SOME NETWORKS FAILED')
    sys.exit(1)
