# -*- coding: utf-8 -*-
"""
常數項定義：保持程式高可讀性且易於修改及維護
"""

# 流程控制常數
STOP = 'stop'       # 停止下一階層的判斷
PASS = 'pass'       # 判斷尚未結束，下一階層繼續判斷

# 連結類型
BOND = 'BOND'                    # 鍵結連結（強連結）
SINK = 'sink'                    # 絲絮連結（一端節點分支度為 1）
LOCAL_BRIDGE = 'local bridge'    # 區域橋接連結
GLOBAL_BRIDGE = 'global bridge'  # 全域橋接連結

# 連結顏色
SINK_COLOR = 'yellow'
BOND_COLOR = 'lightblue'
LOCAL_BRIDGE_COLOR = 'red'
GLOBAL_BRIDGE_COLOR = 'green'

# 連結寬度
SINK_BASIC_WIDTH = 0.5
BOND_BASIC_WIDTH = 1.0
BRIDGE_BASIC_WIDTH = 0.5

# 節點大小
NODE_SIZE_BASE = 140
NODE_SIZE = 80

# 節點顏色
REGULAR_NODE_COLOR = 'magenta'
IMPORTANT_NODE_COLOR = 'pink'
SUPER_NODE_COLOR = 'red'

# Ego 網絡鍵名
EGO_NETWORK = 'ego'

# 特殊網絡
SPECIAL_NETWORKS = ['ERA_result.net']

# 演算法內部 Graph 層級鍵名
GRAPH_KEY_COMMON_NODES_LIST = 'list_'
GRAPH_KEY_AVG_COMMON_NODES = 'avg'
GRAPH_KEY_STD_COMMON_NODES = 'std'
GRAPH_KEY_AVG_LIST = 'all.avg'
GRAPH_KEY_STD_LIST = 'all.std'
GRAPH_KEY_PASS_TO_NEXT_LAYER = 'partial.w'
GRAPH_KEY_SHORTEST_PATH = 'sp'
GRAPH_KEY_THRESHOLD_R1 = 'threshold.R1'
GRAPH_KEY_THRESHOLD_R2 = 'threshold.R2'
GRAPH_KEY_ENTROPY = 'entropy'
GRAPH_KEY_EDGE_CLASS = 'edge_class'
GRAPH_KEY_NUMBER_OF_LAYER = 'number_of_layer'

# 演算法內部 Edge 層級鍵名
EDGE_KEY_LAYER = 'layer'
EDGE_KEY_COLOR = 'color'
EDGE_KEY_WIDTH = 'width'
EDGE_KEY_NEXT_STEP = 'next step'

# 演算法內部 Node 層級鍵名
NODE_KEY_EDGE_CLASS = 'edge_class'
NODE_KEY_NEW_ENTROPY = 'new_entropy'
NODE_KEY_INFORMATION_GAIN = 'information_gain'
NODE_KEY_GROUP_NUMBER = 'group'

# 套件實驗資料集定義
SUITE_DATASETS = {
    'NWS_SWN': [
        'nws_swn_0.0.net',   'nws_swn_0.001.net', 'nws_swn_0.002.net', 'nws_swn_0.004.net',
        'nws_swn_0.008.net', 'nws_swn_0.016.net', 'nws_swn_0.032.net', 'nws_swn_0.064.net',
        'nws_swn_0.128.net', 'nws_swn_0.256.net', 'nws_swn_0.384.net', 'nws_swn_0.512.net',
        'nws_swn_0.640.net', 'nws_swn_0.768.net', 'nws_swn_0.896.net', 'nws_swn_1.0.net',
    ],
    'WS_SWN': [
        'ws_swn_0.0.net',   'ws_swn_0.001.net', 'ws_swn_0.002.net', 'ws_swn_0.004.net',
        'ws_swn_0.008.net', 'ws_swn_0.016.net', 'ws_swn_0.032.net', 'ws_swn_0.064.net',
        'ws_swn_0.128.net', 'ws_swn_0.256.net', 'ws_swn_0.384.net', 'ws_swn_0.512.net',
        'ws_swn_0.640.net', 'ws_swn_0.768.net', 'ws_swn_0.896.net', 'ws_swn_1.0.net',
    ],
    'DEMO': [
        'ba_sfn.net',     'camp92.net',      'celegans.net',    'dolphins.net',
        'florentine.net', 'football.net',    'jazz.net',        'k-core.net',
        'karate.net',     'leader.net',      'lesmis.net',      'prisonInter.net',
        'Ragusa16.net',   'rdgam.net',       's208.net',        'women.net',
    ],
}
