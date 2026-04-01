# -*- coding: utf-8 -*-
"""
HETA 核心分析引擎 — 階層式自我網絡邊類型分析
(Hierarchical Ego-network edge Type Analysis)

移植自 HETA.py (Python 2.7)，修正所有 Python 3 與現代函式庫 API 不相容問題。
所有函數以明確參數傳遞，無全域變數，支援 progress_callback 供 GUI 顯示進度。

設計哲學與方法論概覽
====================

本模組實現一種純拓撲、無參數假設的邊分類方法，將複雜網絡中的每一條邊
（連結）歸入以下四種類型之一：

    BOND（鍵結）      — 嵌入於緊密社群內部的冗餘連結，移除後不改變社群結構。
    SINK（絲絮）      — 一端節點分支度為 1 的懸掛連結，結構上不具橋接功能。
    LOCAL_BRIDGE（區域橋接） — 連接鄰近社群的跨群連結，移除後使局部連通性下降。
    GLOBAL_BRIDGE（全域橋接） — 連接遠距社群的長程連結，移除後可能使網路斷裂。

方法優勢
--------
1. 無需預設社群數量或邊權重：分類完全由拓撲結構驅動，避免人為參數偏差。
2. 多層解析度（multi-scale）：透過 ego network 半徑逐層擴展，同時捕捉局部
   與全域的結構資訊，而非僅看直接鄰居。
3. 統計自適應門檻：R1 門檻來自隨機 null model 的統計分佈（mean + 2σ），
   使判定準則自動適應不同規模與密度的網絡，無需人工調參。
4. 互斥完備分類：STOP/PASS 機制確保每條邊恰好歸入一類，不遺漏不重複。
5. 結構指紋（fingerprint）：四類邊的比例構成網絡的拓撲特徵向量，可用於
   跨網絡比較與分類。

核心流程
--------
    讀取網絡 → 分離連通分量
    → 建立多層 ego network → 計算邊兩端鄰域重疊度
    → 生成隨機網絡 null model → 導出 R1 門檻
    → Phase 1: SINK（degree-1）
    → Phase 2: BOND vs LOCAL_BRIDGE（R1 + R2 門檻，逐層精煉）
    → Phase 3: GLOBAL_BRIDGE（殘留未分類邊）
    → Phase 4: 節點資訊熵與重要性
    → Phase 5: 網絡指紋輸出
"""

import math
import multiprocessing as mp
import os
import pickle
import time
import warnings
from concurrent.futures import ProcessPoolExecutor, as_completed

import networkx as nx
import numpy as np
import scipy.cluster.hierarchy as hc
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Any

from heta.constants import *


@dataclass
class LinkAnalysisResult:
    """單一 component 的連結分析結果"""
    graph: Any  # nx.Graph, 含邊標註
    component_id: int
    network_name: str
    num_nodes: int
    num_edges: int
    avg_degree: float
    diameter: int
    avg_shortest_path: float
    avg_clustering_coeff: float
    degree_assortativity: float
    bond_count: int
    sink_count: int
    local_bridge_count: int
    global_bridge_count: int
    graph_entropy: float
    layers: int
    thresholds_r1: Dict[str, float] = field(default_factory=dict)
    thresholds_r2: Dict[str, float] = field(default_factory=dict)
    node_sizes: List[float] = field(default_factory=list)
    node_colors: List[str] = field(default_factory=list)
    node_info_avg: float = 0.0
    random_network_stats: List[Dict] = field(default_factory=list)
    fingerprint: Dict[int, float] = field(default_factory=dict)
    pos: Optional[Dict] = None
    path: str = ''


@dataclass
class SuiteExperimentResult:
    """批次實驗結果"""
    fingerprints: Dict[str, Dict[int, float]] = field(default_factory=dict)
    corr_table: Dict[str, Dict[str, float]] = field(default_factory=dict)
    labels: List[str] = field(default_factory=list)
    bar_data: Dict[str, Any] = field(default_factory=dict)
    corr_matrix: Any = None
    corr_index: List[int] = field(default_factory=list)
    corr_labels: List[str] = field(default_factory=list)
    network_stats: Dict[str, Dict[str, float]] = field(default_factory=dict)


def debugmsg(s, debug=False):
    """在除錯模式下顯示訊息"""
    if debug:
        print(s)


def _safe_degree_assortativity(g):
    """
    安全版本的 degree assortativity coefficient。
    當所有節點 degree 相同時（如正則格 regular lattice），
    NetworkX 會因 variance=0 而產生 NaN / RuntimeWarning，此函數以 0.0 取代。
    """
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', RuntimeWarning)
            r = nx.degree_assortativity_coefficient(g)
        return 0.0 if (r is None or np.isnan(r)) else r
    except (ValueError, ZeroDivisionError):
        return 0.0


def generate_ego_graph(g, sp):
    """
    為每個節點預先建立多層 ego network（r-hop 鄰域）集合。

    Ego network 是 HETA 分析的基礎資料結構：
    - r=0: {n}（僅節點自身）
    - r=1: {n} ∪ neighbors(n)（直接鄰居）
    - r=k: 所有距離 n 在 k 步以內可達的節點集合

    建構方式為 BFS 式逐層擴展：第 r 層 = 第 r-1 層 ∪ 所有鄰居的第 r-1 層。
    每層讀寫不同的 key（ego0, ego1, ...），因此節點的遍歷順序不影響結果。

    設計取捨：
    - 以空間換時間：預先計算所有節點的所有層 ego network 並存入節點屬性，
      後續 compute_link_property 可直接查表，避免對每條邊重複做 BFS。
    - 記憶體代價隨 sp（層數）和網絡規模增長，但 sp 通常 ≤ 5，可接受。

    原始：HETA.py:112-120
    """
    for r in range(sp):
        for n in g.nodes():
            if r == 0:
                g.nodes[n][EGO_NETWORK + str(r)] = {n}
            else:
                g.nodes[n][EGO_NETWORK + str(r)] = set(g.nodes[n][EGO_NETWORK + str(r - 1)])
                for ng in nx.neighbors(g, n):
                    g.nodes[n][EGO_NETWORK + str(r)] = (
                        g.nodes[n][EGO_NETWORK + str(r)] | g.nodes[ng][EGO_NETWORK + str(r - 1)]
                    )


def get_ego_graph(g, s, t, l):
    """
    取得節點 s 在半徑 l 的鄰域，但排除「經由直接邊 s-t」的第一步擴展。

    具體做法：取 s 的所有鄰居（排除 t）的 (l-1)-hop ego network 之聯集，
    再移除 s 自身。

    設計取捨 — 為何只排除 t 作為直接鄰居、而非完全排除 t 節點：
    - 我們的目標是衡量「s 的第 l 層鄰域」與「t 的第 l 層鄰域」之間的重疊，
      藉此判斷邊 s-t 是連接同一社群（高重疊 → BOND）還是橋接不同社群
      （低重疊 → bridge）。
    - 排除的是「s 經由 s→t 這條邊所到達的鄰居」，而非排除整個 t 節點。
      若存在替代路徑 s→u→...→t→v，那些節點仍會被納入，因為它們本來就屬於
      s 的拓撲鄰域。
    - 這確保了重疊度的計算反映「在不依賴 s-t 直連的情況下，s 和 t 的結構
      環境有多相似」——這正是區分 BOND 與 bridge 的核心判據。

    原始：HETA.py:123-128
    """
    index = EGO_NETWORK + str(l - 1)
    node_list = set()
    for ng in nx.neighbors(g, s):
        if ng != t:
            node_list = node_list | g.nodes[ng][index]
    return node_list - {s}


def compute_link_property(g, sp):
    """
    核心演算法：計算目標網絡中每一條邊兩端節點在不同半徑下的鄰域重疊程度。

    這是 HETA 方法的核心特徵提取步驟。對每條邊 (s, t)，在每個半徑 l 下
    計算一個 [0, 1] 之間的正規化重疊度，作為後續分類的依據。

    概念直覺：
    - 想像從邊 s-t 的兩端分別向外擴展 l 步，觀察雙方「看到」的節點有多少重疊。
    - 若高度重疊（如 0.8），表示 s 和 t 嵌入同一個緊密社群 → 傾向 BOND。
    - 若幾乎不重疊（如 0.05），表示 s 和 t 分屬不同結構區域 → 傾向 bridge。

    演算法細節：
    1. 環狀分層（ring decomposition）：
       c.nodes[s][0] 累積已處理過的節點，c.nodes[s][l] 僅包含第 l 層「新增」
       的節點（扣除所有內層與 s, t 本身），形成不重疊的同心環。
       這避免了內層的高重疊膨脹外層的數值，使每一層的重疊度反映該距離的
       獨立結構資訊。

    2. 交叉層重疊（cross-layer intersection）：
       common_nodes = (s[l] ∩ t[l]) ∪ (s[l] ∩ t[l-1]) ∪ (s[l-1] ∩ t[l])
       不僅比較同層，還比較相鄰層之間的重疊。這是因為在非對稱結構中，
       s 的第 3 層鄰居可能恰好是 t 的第 2 層鄰居，這種交叉重疊同樣反映
       兩節點的結構親近性。

    3. 正規化分母：
       denom = min(|s[l]|, |t[l]|) + min(|s[l]|, |t[l-1]|) + min(|s[l-1]|, |t[l]|)
       使用 min() 而非 max() 進行正規化，類似 Jaccard 的 overlap coefficient
       變體。好處是：不會因為一端的鄰域遠大於另一端而稀釋重疊度。
       數學上可證明 0 ≤ ratio ≤ 1：每組交集的大小 ≤ 對應的 min 值，
       而聯集的大小 ≤ 三組交集大小之和 ≤ 三個 min 值之和 = denom。

    4. 除零安全：
       當 common_nodes 為空時直接回傳 0，不執行除法。
       當 common_nodes 非空時，至少有一組交集非空，對應的 min 值 ≥ 1，
       故 denom ≥ 1，除法安全。

    時間複雜度：O(m × l)，其中 m = 邊數，l = 層數
    原始：HETA.py:131-174
    """
    c = g.copy()

    for i in range(sp):
        c.graph[GRAPH_KEY_COMMON_NODES_LIST + str(i + 1)] = []

    generate_ego_graph(c, sp)

    for s, t in g.edges():
        base_st_nodes = {s, t}
        # 每條邊獨立初始化「已處理節點」累積器，用於環狀分層
        c.nodes[s][0] = set()
        c.nodes[t][0] = set()

        for i in range(sp):
            l = i + 1

            # 取得第 l 層的「環」：排除直接連線的 ego 鄰域 - 內層累積 - s,t 自身
            c.nodes[s][l] = get_ego_graph(c, s, t, l) - c.nodes[s][0] - base_st_nodes
            c.nodes[t][l] = get_ego_graph(c, t, s, l) - c.nodes[t][0] - base_st_nodes

            # 交叉層重疊：同層 + 相鄰層之間的交集聯集
            common_nodes = (
                (c.nodes[s][l] & c.nodes[t][l]) |
                (c.nodes[s][l] & c.nodes[t][l - 1]) |
                (c.nodes[s][l - 1] & c.nodes[t][l])
            )

            # 正規化分母：三組 min 之和，保證 ratio ∈ [0, 1]
            denom = (
                min(len(c.nodes[s][l]), len(c.nodes[t][l])) +
                min(len(c.nodes[s][l]), len(c.nodes[t][l - 1])) +
                min(len(c.nodes[s][l - 1]), len(c.nodes[t][l]))
            )
            # 邊屬性以負數 key（-1, -2, ...）儲存各層的重疊度
            g[s][t][-l] = 0 if len(common_nodes) == 0 else float(len(common_nodes)) / denom

            c.graph[GRAPH_KEY_COMMON_NODES_LIST + str(l)].append(g[s][t][-l])

            # 將本層節點併入累積器，下一層將排除這些已計入的節點
            c.nodes[s][0] |= c.nodes[s][l]
            c.nodes[t][0] |= c.nodes[t][l]

    # 彙總每一層所有邊的重疊度的平均值與標準差，供後續門檻值比較使用
    for i in range(sp):
        l = str(i + 1)
        g.graph[GRAPH_KEY_AVG_COMMON_NODES + l] = np.mean(c.graph[GRAPH_KEY_COMMON_NODES_LIST + l])
        g.graph[GRAPH_KEY_STD_COMMON_NODES + l] = np.std(c.graph[GRAPH_KEY_COMMON_NODES_LIST + l])

    return g


def entropy(p):
    """
    計算 Shannon 資訊熵
    原始：HETA.py:177-184
    """
    e = 0
    t = sum(p)
    if t == 0:
        return 0
    for v in p:
        if v != 0:
            pi = float(v) / t
            e += -(pi * math.log(pi, 2))
    return e


def network_clustering(g, layer):
    """
    階層式社群切割：移除 global bridge 和 sink 連結，再遞迴移除 local bridge
    原始：HETA.py:187-211
    """
    snapshot_g = {GLOBAL_BRIDGE: [], EDGE_KEY_LAYER + str(layer): []}
    c = g.copy()

    for s, t in g.edges():
        if g[s][t][EDGE_KEY_LAYER + str(layer)].startswith(GLOBAL_BRIDGE):
            if c.has_edge(s, t):
                c.remove_edge(s, t)
        if g[s][t][EDGE_KEY_LAYER + str(layer)].startswith(SINK):
            if c.has_edge(s, t):
                c.remove_edge(s, t)
            tmpG = nx.Graph()
            if g.degree(s) == 1:
                if c.has_node(s):
                    c.remove_node(s)
                g.nodes[s][NODE_KEY_GROUP_NUMBER] = "-0.01"
                tmpG.add_node(s)
            elif g.degree(t) == 1:
                if c.has_node(t):
                    c.remove_node(t)
                g.nodes[t][NODE_KEY_GROUP_NUMBER] = "-0.01"
                tmpG.add_node(t)
            else:
                # 兩端 degree 都 > 1（不應出現在 SINK 邊），保守移除 t
                if c.has_node(t):
                    c.remove_node(t)
                g.nodes[t][NODE_KEY_GROUP_NUMBER] = "-0.01"
                tmpG.add_node(t)
            snapshot_g[GLOBAL_BRIDGE].append(tmpG)
            snapshot_g[EDGE_KEY_LAYER + str(layer)].append(tmpG)

    snapshot_g[GLOBAL_BRIDGE].append(c)
    no = 1
    for comp_nodes in nx.connected_components(c):
        sc = c.subgraph(comp_nodes).copy()
        component_clustering(g, snapshot_g, sc, layer, "0." + ("%02d" % no))
        no += 1
    return snapshot_g


def component_clustering(bigG, sg, g, layer, cno):
    """
    遞迴式社群切割：逐層移除 local bridge
    原始：HETA.py:214-231
    """
    if g.order() == 1 or g.size() == 0 or layer == 0:
        for v in g.nodes():
            bigG.nodes[v][NODE_KEY_GROUP_NUMBER] = cno
        if layer != 0:
            sg[EDGE_KEY_LAYER + str(layer)].append(g)
        return

    c = g.copy()
    for s, t in g.edges():
        if g[s][t][EDGE_KEY_LAYER + str(layer)] == LOCAL_BRIDGE + ' of layer ' + str(layer):
            if c.has_edge(s, t):
                c.remove_edge(s, t)

    sg[EDGE_KEY_LAYER + str(layer)].append(c)
    if layer > 1:
        sg[EDGE_KEY_LAYER + str(layer - 1)] = []

    no = 1
    for comp_nodes in nx.connected_components(c):
        sc = c.subgraph(comp_nodes).copy()
        component_clustering(bigG, sg, sc, layer - 1, cno + ("%02d" % no))
        no += 1


def _generate_random_network(g, layers, Q, cache_path=None):
    """
    產生單一隨機網絡（null model）並計算其連結屬性。

    Null model 的角色與設計
    ----------------------
    為了判斷一條邊的重疊度是「顯著地高」還是「隨機就會出現的背景值」，
    我們需要一個 null model 作為基準線。HETA 採用 degree-preserving
    randomization（保持分支度序列的隨機化）：

    - 方法：connected_double_edge_swap，隨機交換邊的端點但保持每個節點
      的分支度不變，同時確保圖仍為連通。
    - 交換次數：Q × m（m 為邊數），Q=100 確保充分打亂拓撲結構。
    - 保持分支度的理由：分支度是最基本的節點屬性，若不保持，隨機網絡
      的結構會與原始圖差異過大，門檻值會過度寬鬆。
    - 保持連通性的理由：斷裂的圖無法正確計算 ego network 和重疊度。

    容錯策略
    --------
    - 第一次嘗試全量 swap（Q × m 次）
    - 若因圖結構限制失敗（如接近完全圖或星狀圖），以半量重試
    - 若仍失敗，發出 RuntimeWarning 警告（隨機網絡與原圖相同，
      可能導致門檻值偏差），但不中斷流程
    - 對極小圖（edges ≤ 2），直接跳過 swap（無法執行有意義的交換）

    此函數為頂層函數（非巢狀），以支援 multiprocessing 的 pickle 序列化。

    參數：
        g: 原始圖的副本（會被 edge swap 修改）
        layers: 分析層數
        Q: 每條邊的 swap 倍數（預設 100）
        cache_path: 快取檔案路徑（若提供則存檔）

    回傳：包含 graph-level 統計量的字典（各層的 avg/std）
    """
    rg = g.copy()
    swap_ok = False

    if g.number_of_edges() > 2:
        nswap = Q * g.number_of_edges()
        try:
            nx.connected_double_edge_swap(rg, nswap=nswap, _window_threshold=3)
            swap_ok = True
        except (nx.NetworkXAlgorithmError, nx.NetworkXError):
            try:
                nx.connected_double_edge_swap(rg, nswap=nswap // 2, _window_threshold=3)
                swap_ok = True
            except (nx.NetworkXAlgorithmError, nx.NetworkXError):
                pass

    if not swap_ok:
        warnings.warn(
            f"Edge swap failed for random network generation "
            f"(edges={g.number_of_edges()}). "
            f"The random network is identical to the original graph, "
            f"which may bias threshold computation.",
            RuntimeWarning,
            stacklevel=2,
        )

    compute_link_property(rg, layers)

    rg_data = {'graph': {}}
    for i in range(layers):
        l = str(i + 1)
        rg_data['graph'][GRAPH_KEY_AVG_COMMON_NODES + l] = rg.graph[GRAPH_KEY_AVG_COMMON_NODES + l]
        rg_data['graph'][GRAPH_KEY_STD_COMMON_NODES + l] = rg.graph[GRAPH_KEY_STD_COMMON_NODES + l]

    if cache_path:
        try:
            with open(cache_path, 'wb') as f:
                pickle.dump(rg_data, f, protocol=pickle.HIGHEST_PROTOCOL)
        except OSError:
            pass  # 快取寫入失敗不影響分析結果

    return rg_data


# 支援的網絡檔案格式
SUPPORTED_FORMATS = {
    '.net': 'Pajek',
    '.gml': 'GML',
    '.graphml': 'GraphML',
    '.edgelist': 'Edge List',
    '.edges': 'Edge List',
    '.adjlist': 'Adjacency List',
}


def _read_network(path):
    """
    讀取網絡檔案，根據副檔名自動選擇對應的讀取器。

    支援格式：
        .net       — Pajek format
        .gml       — GML format
        .graphml   — GraphML format
        .edgelist  — Edge list (space/tab separated)
        .edges     — Edge list (同上)
        .adjlist   — Adjacency list

    參數：
        path: 網絡檔案路徑

    回傳：nx.Graph
    """
    _, ext = os.path.splitext(path)
    ext = ext.lower()

    with warnings.catch_warnings():
        warnings.filterwarnings('ignore', message='.*is not processed.*Non-string attribute.*',
                                category=UserWarning)
        if ext == '.net':
            G = nx.Graph(nx.read_pajek(path))
        elif ext == '.gml':
            G = nx.Graph(nx.read_gml(path))
        elif ext == '.graphml':
            G = nx.Graph(nx.read_graphml(path))
        elif ext in ('.edgelist', '.edges'):
            G = nx.read_edgelist(path)
        elif ext == '.adjlist':
            G = nx.read_adjlist(path)
        else:
            supported = ', '.join(SUPPORTED_FORMATS.keys())
            raise ValueError(
                f"Unsupported network file format: '{ext}'\n"
                f"Supported formats: {supported}"
            )

    return G


def run_link_analysis(
    path,
    times=1000,
    quick=False,
    separation=1,
    debug=False,
    parallel=False,
    workers=None,
    progress_callback=None,
):
    """
    主分析流程：讀取網絡 → 建立 null model → 分類所有邊 → 計算結構資訊量。

    這是 HETA 的頂層入口函數，整合了從檔案讀取到結果輸出的完整管線。
    每個連通分量獨立分析，回傳各分量的 LinkAnalysisResult。

    分析管線概覽：
        1. 讀取 Pajek 格式網絡，分離連通分量（跳過單節點或單邊的平凡分量）
        2. 根據平均最短路徑長度自動決定分析層數（layers = avg_sp / 2）
        3. 計算每條邊在各層的鄰域重疊度（compute_link_property）
        4. 生成 degree-preserving 隨機網絡（null model），導出 R1 門檻
        5. 五階段邊分類（詳見下方各 phase 的行內註解）
        6. 計算節點資訊熵與結構重要性
        7. 輸出網絡指紋與分析結果

    原始：HETA.py:234-641（link_analysis 函數）

    參數：
        path: 網絡檔案路徑（支援 .net, .gml, .graphml, .edgelist, .edges, .adjlist）
        times: 隨機網絡數量（預設 1000），越多門檻值越穩定
        quick: 是否啟用快速模式（限制分析層數以加速）
        separation: 快速模式下的層數上限
        debug: 除錯模式
        parallel: 是否使用多核心平行產生隨機網絡
        workers: 平行模式下的 worker 數量（None 表示自動偵測 CPU 核心數 - 1）
        progress_callback: 進度回報函數 callback(current, total, message)

    回傳：List[LinkAnalysisResult]
    """
    root, ext = os.path.splitext(path)
    head, tail = os.path.split(root)

    if not (os.path.exists(path) and os.path.isfile(path)):
        raise FileNotFoundError(f"Network file not found: {path}")

    results = []

    debugmsg('read and analyse the target network...', debug)
    G = _read_network(path)
    compNo = 0

    # 按節點數降序排列連通分量，確保 compNo=1 永遠是最大分量。
    # nx.connected_components 的迭代順序依賴內部 hash，不同環境可能不同；
    # 排序後 _1 = 最大分量，保證：
    #   (1) suite experiment 查詢 _1 時拿到的是最具代表性的主要分量
    #   (2) 跨平台、跨版本的結果一致且可重現
    for comp_nodes in sorted(nx.connected_components(G), key=len, reverse=True):
        g = G.subgraph(comp_nodes).copy()

        # 跳過平凡分量：單節點（無邊）或單邊（僅一條 SINK，無分類意義）
        if g.order() == 1 or g.size() == 1:
            continue

        g.graph[GRAPH_KEY_SHORTEST_PATH] = nx.average_shortest_path_length(g)
        g.name = compNo
        compNo += 1

        # ================================================================
        # 自動決定分析層數（layers）
        # ================================================================
        # layers = floor(avg_shortest_path / 2)，下限為 1。
        #
        # 設計理由：
        # - 平均最短路徑反映網絡的「直徑感」，除以 2 是因為邊的兩端各自向外
        #   擴展，合計覆蓋的距離約等於平均最短路徑。
        # - 層數太少：僅看直接鄰居，無法區分 local bridge 與 global bridge。
        # - 層數太多：超過網絡半徑後，所有 ego network 趨於覆蓋整個圖，
        #   重疊度趨近 1，失去鑑別力。
        # - max(1, ...) 確保至少分析一層，避免 layers=0 的退化情況。
        if quick:
            layers = max(1, int(min(g.graph[GRAPH_KEY_SHORTEST_PATH] / 2.0, separation)))
        else:
            layers = max(1, int(g.graph[GRAPH_KEY_SHORTEST_PATH] / 2.0))

        # 計算每條邊在各層的鄰域重疊度（核心特徵提取）
        compute_link_property(g, layers)

        t_start = time.time()
        Q = 100

        if progress_callback:
            progress_callback(0, times, f"Component {compNo}: generating random networks...")

        # 產生供比較用的隨機網絡
        cache_dir = os.path.join(head, '.heta_cache') if head else '.heta_cache'
        os.makedirs(cache_dir, exist_ok=True)

        # Phase 1: 載入已快取的隨機網絡
        rgs = [None] * times
        uncached_tasks = []
        cached_count = 0

        for c in range(times):
            cp = os.path.join(cache_dir, f'{tail}_{compNo}_{c}.pkl')
            if os.path.exists(cp):
                debugmsg(f'read random network #{c} from cache...', debug)
                try:
                    with open(cp, 'rb') as f:
                        rgs[c] = pickle.load(f)
                    cached_count += 1
                except (pickle.UnpicklingError, EOFError, OSError, Exception):
                    debugmsg(f'cache file #{c} corrupted, will regenerate', debug)
                    uncached_tasks.append((c, cp))
            else:
                uncached_tasks.append((c, cp))

        if cached_count > 0:
            debugmsg(f'loaded {cached_count} random networks from cache', debug)
            if progress_callback:
                progress_callback(cached_count, times,
                    f"Component {compNo}: loaded {cached_count} from cache")

        # Phase 2: 生成未快取的隨機網絡
        if uncached_tasks:
            if parallel and len(uncached_tasks) > 1:
                # === 平行模式 ===
                cpu_count = os.cpu_count() or 4
                actual_workers = workers or max(1, cpu_count - 1)
                actual_workers = min(actual_workers, len(uncached_tasks))
                debugmsg(f'generating {len(uncached_tasks)} random networks '
                         f'in parallel ({actual_workers} workers)...', debug)

                # 建立輕量級圖形副本：只保留節點和邊的結構
                # 去除 compute_link_property 計算的 ego network 等大量屬性，
                # 大幅減少 spawn 序列化開銷
                g_for_workers = nx.Graph()
                g_for_workers.add_nodes_from(g.nodes())
                g_for_workers.add_edges_from(g.edges())

                # 使用 spawn context 避免 fork + Qt/GUI 死鎖問題
                # fork 會繼承父程序的 Qt 內部執行緒鎖，導致子程序 deadlock
                # spawn 建立全新程序，安全且為 Python 3.14+ 預設方式
                try:
                    mp_ctx = mp.get_context('spawn')
                except ValueError:
                    mp_ctx = None
                with ProcessPoolExecutor(max_workers=actual_workers,
                                         mp_context=mp_ctx) as executor:
                    future_to_idx = {}
                    for idx, cp in uncached_tasks:
                        future = executor.submit(
                            _generate_random_network, g_for_workers,
                            layers, Q, cp)
                        future_to_idx[future] = idx

                    done_count = 0
                    for future in as_completed(future_to_idx):
                        idx = future_to_idx[future]
                        try:
                            rgs[idx] = future.result()
                        except Exception as e:
                            debugmsg(f'parallel worker error #{idx}: {e}, '
                                     f'falling back to serial...', debug)
                            cp = os.path.join(cache_dir,
                                f'{tail}_{compNo}_{idx}.pkl')
                            try:
                                rgs[idx] = _generate_random_network(
                                    g, layers, Q, cp)
                            except Exception as e2:
                                debugmsg(f'serial fallback also failed #{idx}: {e2}', debug)
                                rgs[idx] = None

                        done_count += 1
                        if progress_callback:
                            progress_callback(
                                cached_count + done_count, times,
                                f"Component {compNo}: network "
                                f"{cached_count + done_count}/{times} "
                                f"(parallel, {actual_workers} workers)")

                t_elapsed = time.time() - t_start
                debugmsg(f'parallel generation done in {t_elapsed:.2f}s '
                         f'({actual_workers} workers)', debug)
            else:
                # === 序列模式 ===
                for i, (idx, cp) in enumerate(uncached_tasks):
                    debugmsg(f'create and analyse random network #{idx}...',
                             debug)
                    rgs[idx] = _generate_random_network(g, layers, Q, cp)

                    if progress_callback:
                        progress_callback(
                            cached_count + i + 1, times,
                            f"Component {compNo}: random network "
                            f"{cached_count + i + 1}/{times}")

                    debugmsg(f'+--- * Time spent: '
                             f'{time.time() - t_start:.4f}s', debug)
                    t_start = time.time()

        rgs = [r for r in rgs if r is not None]
        actual_times = len(rgs)
        if actual_times == 0:
            raise RuntimeError(
                f"Component {compNo}: all random network generations failed, "
                f"cannot compute thresholds"
            )

        # ================================================================
        # R1 門檻值：從 null model 導出 BOND / bridge 的分界線
        # ================================================================
        # 對每一層 l，彙總所有隨機網絡在該層的 (avg, std) 統計量，計算：
        #
        #   R1(l) = mean(random_avg_l) + 2 × mean(random_std_l)
        #
        # 統計意義：
        # - 在隨機網絡中，邊的重疊度近似常態分佈。R1 相當於 μ + 2σ，
        #   即隨機期望的「上界」。
        # - 若一條邊的實際重疊度 ≥ R1，表示它的鄰域重疊「顯著高於隨機」，
        #   意味著兩端節點嵌入同一個結構緊密的社群 → 分類為 BOND。
        # - 若低於 R1，則該重疊度在隨機網絡中也可能出現 → 可能是 bridge。
        #
        # 設計取捨：
        # - 使用 2σ 而非 1σ 或 3σ：2σ 涵蓋約 95% 的隨機分佈，在靈敏度
        #   與特異度之間取得平衡。1σ 會將過多邊判為 BOND（假陽性高），
        #   3σ 則過於嚴格（許多明顯的社群內邊會被誤判為 bridge）。
        # - R1 上限 clamp 至 1.0：因為重疊度的理論上界為 1，超過 1 的門檻
        #   會使所有邊都無法通過，失去意義。
        # - 每一層有獨立的 R1：不同半徑下的隨機基準線不同，這使得多層
        #   分析能在每個尺度上自適應地判斷。
        debugmsg('generate a threshold for BOND/bridge link analysis...', debug)
        thresholds_r1 = {}
        thresholds_r2 = {}
        for i in range(layers):
            l = str(i + 1)
            g.graph[GRAPH_KEY_AVG_LIST + l] = []
            g.graph[GRAPH_KEY_STD_LIST + l] = []
            for j in range(actual_times):
                g.graph[GRAPH_KEY_AVG_LIST + l].append(rgs[j]['graph'][GRAPH_KEY_AVG_COMMON_NODES + l])
                g.graph[GRAPH_KEY_STD_LIST + l].append(rgs[j]['graph'][GRAPH_KEY_STD_COMMON_NODES + l])
            g.graph[GRAPH_KEY_THRESHOLD_R1 + l] = (
                np.mean(g.graph[GRAPH_KEY_AVG_LIST + l]) +
                2 * np.mean(g.graph[GRAPH_KEY_STD_LIST + l])
            )
            if g.graph[GRAPH_KEY_THRESHOLD_R1 + l] > 1:
                g.graph[GRAPH_KEY_THRESHOLD_R1 + l] = 1.0
            thresholds_r1[l] = g.graph[GRAPH_KEY_THRESHOLD_R1 + l]

        # ================================================================
        # 五階段邊分類（Phase 1 ~ Phase 5）
        # ================================================================
        # 分類使用 STOP/PASS 狀態機：
        # - STOP：該邊已確定類型，後續階段僅複製標籤，不再重新判斷。
        # - PASS：該邊尚未確定，繼續進入下一階段或下一層的判斷。
        # 此機制保證每條邊恰好被計數一次（互斥且完備）。
        debugmsg('assess the link property of every edge...', debug)

        # Phase 1: SINK — 懸掛邊識別
        # 任一端節點的分支度為 1，即為 SINK。
        # 這是充分必要條件，不需要統計門檻：degree-1 的節點只有一條邊，
        # 該邊不具備任何橋接或社群內連結的功能。
        # SINK 在最早期就排除，避免影響後續 BOND/bridge 的統計分佈。
        g.graph[SINK] = 0
        g.graph[BOND] = 0
        g.graph[LOCAL_BRIDGE] = 0
        g.graph[GLOBAL_BRIDGE] = 0

        for s, t in g.edges():
            if (g.degree(s) == 1) or (g.degree(t) == 1):
                g[s][t][EDGE_KEY_LAYER + '0'] = SINK
                g[s][t][EDGE_KEY_NEXT_STEP] = STOP
                g[s][t][EDGE_KEY_WIDTH] = SINK_BASIC_WIDTH
                g[s][t][EDGE_KEY_COLOR] = SINK_COLOR
                g.graph[SINK] += 1
            else:
                g[s][t][EDGE_KEY_NEXT_STEP] = PASS

        # Phase 2: BOND vs LOCAL_BRIDGE — 逐層精煉分類
        # --------------------------------------------------------
        # 對每一層 l（從第 1 層到第 layers 層），依序判斷尚未確定的邊：
        #
        # (a) 重疊度 ≥ R1(l) → BOND，設為 STOP
        #     在此層，邊的鄰域重疊顯著高於隨機基準線，確認為社群內的
        #     冗餘連結。BOND 在較淺層確認的，線寬設定較粗（反映「在較
        #     近的視角下就已經很明顯」）。
        #
        # (b) 重疊度 < R1(l) → 暫標為 LOCAL_BRIDGE of layer l
        #     這些邊在此層未通過 BOND 門檻，但尚不確定是 local 還是
        #     global bridge。它們的重疊度被收集起來，用於計算 R2 門檻。
        #
        # R2 門檻（LOCAL_BRIDGE vs GLOBAL_BRIDGE 的分界線）：
        #   R2(l) = mean(pass_values) - 1 × std(pass_values)
        #
        #   與 R1 不同，R2 不來自 null model，而是來自「當前層未通過 R1
        #   的邊」自身的分佈。R2 的目的是在 bridge 群體中進一步區分：
        #   - 重疊度 > R2 → LOCAL_BRIDGE（仍有一定的鄰域共享，是鄰近
        #     社群之間的橋接），設為 STOP
        #   - 重疊度 ≤ R2 → 繼續 PASS 到下一層，或最終成為 GLOBAL_BRIDGE
        #
        #   設計取捨：R2 使用 mean - 1σ（而非 R1 的 mean + 2σ），因為
        #   目的不同。R1 要找「顯著高於隨機」的邊；R2 要找「在 bridge
        #   群體中仍算相對高」的邊。mean - 1σ 篩出分佈中的下尾約 16%
        #   作為最弱的 bridge（潛在的 global bridge）。
        #   R2 下限 clamp 至 0.0：負值無意義（重疊度最小為 0）。
        #
        # 多層精煉的優勢：
        # - 一條邊在第 1 層可能低於 R1（看起來像 bridge），但在第 2 層
        #   的重疊度提高並超過 R1 → 最終被正確歸為 BOND。
        # - 這使分類能在多個尺度上驗證，避免單一尺度的誤判。
        n = '1'  # 預設值，如果 layers 為 0 不會進入迴圈
        for i in range(layers):
            l = -(i + 1)        # 邊屬性的 key：-1, -2, ...（對應第 1, 2, ... 層）
            n = str(i + 1)
            g.graph[GRAPH_KEY_PASS_TO_NEXT_LAYER + n] = []

            for s, t in g.edges():
                if g[s][t][EDGE_KEY_NEXT_STEP] == STOP:
                    # 已確定的邊：複製前一層的標籤，不重新判斷
                    g[s][t][EDGE_KEY_LAYER + n] = g[s][t][EDGE_KEY_LAYER + str(i)]
                elif g[s][t][l] > g.graph[GRAPH_KEY_THRESHOLD_R1 + n]:
                    # 重疊度 > R1 → BOND
                    g[s][t][EDGE_KEY_LAYER + n] = BOND
                    g[s][t][EDGE_KEY_NEXT_STEP] = STOP
                    g[s][t][EDGE_KEY_WIDTH] = (layers - i + 1) * BOND_BASIC_WIDTH
                    g[s][t][EDGE_KEY_COLOR] = BOND_COLOR
                    g.graph[BOND] += 1
                else:
                    # 重疊度 < R1 → 暫標為 local bridge，等待 R2 進一步篩選
                    g[s][t][EDGE_KEY_LAYER + n] = LOCAL_BRIDGE + ' of layer ' + n
                    g[s][t][EDGE_KEY_WIDTH] = (layers - i + 1) * BRIDGE_BASIC_WIDTH
                    g[s][t][EDGE_KEY_COLOR] = LOCAL_BRIDGE_COLOR
                    g.graph[GRAPH_KEY_PASS_TO_NEXT_LAYER + n].append(g[s][t][l])

            # 從當前層的 bridge 候選值動態計算 R2
            if len(g.graph[GRAPH_KEY_PASS_TO_NEXT_LAYER + n]) == 0:
                g.graph[GRAPH_KEY_THRESHOLD_R2 + n] = 0
            else:
                g.graph[GRAPH_KEY_THRESHOLD_R2 + n] = (
                    np.mean(g.graph[GRAPH_KEY_PASS_TO_NEXT_LAYER + n]) -
                    np.std(g.graph[GRAPH_KEY_PASS_TO_NEXT_LAYER + n])
                )
                if g.graph[GRAPH_KEY_THRESHOLD_R2 + n] < 0:
                    g.graph[GRAPH_KEY_THRESHOLD_R2 + n] = 0.0
                # 重疊度 > R2 的邊確認為 LOCAL_BRIDGE
                for s, t in g.edges():
                    if g[s][t][EDGE_KEY_NEXT_STEP] == PASS:
                        if g[s][t][l] > g.graph[GRAPH_KEY_THRESHOLD_R2 + n]:
                            g[s][t][EDGE_KEY_NEXT_STEP] = STOP
                            g.graph[LOCAL_BRIDGE] += 1

            thresholds_r2[n] = g.graph[GRAPH_KEY_THRESHOLD_R2 + n]

        # Phase 3: GLOBAL_BRIDGE — 收網
        # --------------------------------------------------------
        # 經過所有層的 R1 和 R2 篩選後，仍然處於 PASS 狀態的邊，
        # 其重疊度在每一層、每個尺度下都很低，表示兩端節點的結構環境
        # 幾乎完全不同 → 分類為 GLOBAL_BRIDGE。
        # 這些邊通常連接網絡中距離最遠的社群，是全域連通性的關鍵。
        for s, t in g.edges():
            if g[s][t][EDGE_KEY_NEXT_STEP] == PASS:
                g[s][t][EDGE_KEY_LAYER + n] = GLOBAL_BRIDGE
                g[s][t][EDGE_KEY_WIDTH] = BRIDGE_BASIC_WIDTH
                g[s][t][EDGE_KEY_COLOR] = GLOBAL_BRIDGE_COLOR
                g.graph[GLOBAL_BRIDGE] += 1

        # Phase 4: 節點資訊熵與結構重要性
        # --------------------------------------------------------
        # 利用 Shannon entropy 衡量每個節點對網絡邊類型分佈的影響。
        #
        # 概念：
        # - graph_entropy = H(BOND, LOCAL_BRIDGE, GLOBAL_BRIDGE) 反映整體
        #   網絡的邊類型多樣性。三類數量越均衡，熵越高（最大 log2(3) ≈ 1.585）。
        # - 對每個節點 s，假設移除 s 的所有非 SINK 邊後，重新計算邊類型分佈
        #   的熵（new_entropy）。
        # - information_gain = max(0, graph_entropy - new_entropy)
        #   表示該節點的邊「為網絡貢獻了多少結構多樣性」。
        #
        # 設計取捨：
        # - SINK 不參與熵計算：degree-1 的邊在結構上是確定性的（不可能是
        #   其他類型），不帶有結構資訊量。
        # - max(0, ...) 保護：理論上 new_entropy ≤ graph_entropy（移除邊
        #   只會降低或維持多樣性），但浮點精度可能導致微小負值。
        # - 顏色映射使用 ceil(information_gain) 並 clamp 到 [0, 2]：
        #   gain ≈ 0 → 普通節點，gain ≈ 1 → 重要節點，gain ≈ 1.585 → 超級節點。
        ns = []
        nc = []
        g.graph[GRAPH_KEY_EDGE_CLASS] = {
            BOND: g.graph[BOND],
            LOCAL_BRIDGE: g.graph[LOCAL_BRIDGE],
            GLOBAL_BRIDGE: g.graph[GLOBAL_BRIDGE],
        }
        g.graph[GRAPH_KEY_ENTROPY] = entropy(list(g.graph[GRAPH_KEY_EDGE_CLASS].values()))

        for s in g.nodes():
            # 複製全域邊類型計數，逐一扣除 s 的鄰邊貢獻
            g.nodes[s][NODE_KEY_EDGE_CLASS] = g.graph[GRAPH_KEY_EDGE_CLASS].copy()
            for t in nx.neighbors(g, s):
                for key in list(g.nodes[s][NODE_KEY_EDGE_CLASS].keys()):
                    # startswith 匹配：BOND 標籤為 'BOND'，LOCAL_BRIDGE 標籤為
                    # 'local bridge of layer N'，GLOBAL_BRIDGE 為 'global bridge'。
                    # SINK 標籤為 'sink'，不匹配任何 key，正確地被排除。
                    if g[s][t][EDGE_KEY_LAYER + str(layers)].startswith(key):
                        g.nodes[s][NODE_KEY_EDGE_CLASS][key] -= 1
            g.nodes[s][NODE_KEY_NEW_ENTROPY] = entropy(list(g.nodes[s][NODE_KEY_EDGE_CLASS].values()))
            g.nodes[s][NODE_KEY_INFORMATION_GAIN] = max(0, g.graph[GRAPH_KEY_ENTROPY] - g.nodes[s][NODE_KEY_NEW_ENTROPY])
            ns.append(g.nodes[s][NODE_KEY_INFORMATION_GAIN])
            _node_colors = [REGULAR_NODE_COLOR, IMPORTANT_NODE_COLOR, SUPER_NODE_COLOR]
            _color_idx = max(0, min(len(_node_colors) - 1,
                                    int(math.ceil(g.nodes[s][NODE_KEY_INFORMATION_GAIN]))))
            nc.append(_node_colors[_color_idx])

        # 節點大小正規化：以平均 information_gain 為基準，等比縮放
        ns_avg = np.mean(ns)
        if ns_avg != 0:
            ns = [NODE_SIZE_BASE + NODE_SIZE * (value / ns_avg) for value in ns]
        else:
            ns = [NODE_SIZE_BASE] * len(ns)

        # Phase 5: 網絡指紋（Network Fingerprint）
        # --------------------------------------------------------
        # 將四類邊的比例組成一個 4 維特徵向量：
        #   [BOND%, LOCAL_BRIDGE%, GLOBAL_BRIDGE%, SINK%]
        #
        # 指紋用途：
        # - 跨網絡比較：不同網絡的指紋可透過相關係數比較拓撲相似性。
        # - 網絡分類：例如小世界網絡的指紋會與隨機圖或無尺度網絡不同。
        # - 演化追蹤：同一網絡在不同時間點的指紋變化反映結構演化。
        d = float(g.graph[BOND] + g.graph[LOCAL_BRIDGE] + g.graph[GLOBAL_BRIDGE] + g.graph[SINK])
        if d == 0:
            fingerprint = {0: 0.0, 1: 0.0, 2: 0.0, 3: 0.0}
        else:
            fingerprint = {
                0: round(g.graph[BOND] / d, 4),
                1: round(g.graph[LOCAL_BRIDGE] / d, 4),
                2: round(g.graph[GLOBAL_BRIDGE] / d, 4),
                3: round(g.graph[SINK] / d, 4),
            }

        _save_fingerprint(root + '_' + str(compNo), fingerprint, stats={
            'nodes': g.number_of_nodes(),
            'edges': g.number_of_edges(),
            'avg_degree': round(g.number_of_edges() * 2.0 / g.number_of_nodes(), 4),
            'diameter': nx.diameter(g),
            'avg_shortest_path': round(g.graph[GRAPH_KEY_SHORTEST_PATH], 4),
            'avg_clustering_coeff': round(nx.average_clustering(g), 4),
            'degree_assortativity': round(_safe_degree_assortativity(g), 4),
            'entropy': round(g.graph[GRAPH_KEY_ENTROPY], 4),
        })

        # 寫出分析結果 Pajek 檔案
        ng = nx.Graph()
        ng.add_nodes_from(g.nodes())
        ng.add_edges_from(g.edges(data=True))
        ng.graph['name'] = root + '_' + str(compNo) + '_result' + ext
        try:
            with warnings.catch_warnings():
                warnings.filterwarnings('ignore', message='.*is not processed.*Non-string attribute.*',
                                        category=UserWarning)
                nx.write_pajek(ng, root + '_' + str(compNo) + '_result' + ext)
        except OSError:
            pass  # 結果檔寫入失敗不影響回傳的分析結果

        # 計算佈局
        if path.endswith(tuple(SPECIAL_NETWORKS)):
            try:
                pos = {seq_no: (float(g.nodes[seq_no]['posx']), float(g.nodes[seq_no]['posy'])) for seq_no in g.nodes()}
            except (KeyError, ValueError):
                pos = nx.spring_layout(g)
        else:
            pos = nx.spring_layout(g)

        # 收集隨機網絡統計資料
        rn_stats = []
        for j in range(actual_times):
            stat = {}
            for i in range(layers):
                l = str(i + 1)
                stat[GRAPH_KEY_AVG_COMMON_NODES + l] = rgs[j]['graph'][GRAPH_KEY_AVG_COMMON_NODES + l]
                stat[GRAPH_KEY_STD_COMMON_NODES + l] = rgs[j]['graph'][GRAPH_KEY_STD_COMMON_NODES + l]
            rn_stats.append(stat)

        result = LinkAnalysisResult(
            graph=g,
            component_id=compNo,
            network_name=tail,
            num_nodes=g.number_of_nodes(),
            num_edges=g.number_of_edges(),
            avg_degree=g.number_of_edges() * 2.0 / g.number_of_nodes(),
            diameter=nx.diameter(g),
            avg_shortest_path=round(g.graph[GRAPH_KEY_SHORTEST_PATH], 4),
            avg_clustering_coeff=round(nx.average_clustering(g), 4),
            degree_assortativity=round(_safe_degree_assortativity(g), 4),
            bond_count=g.graph[BOND],
            sink_count=g.graph[SINK],
            local_bridge_count=g.graph[LOCAL_BRIDGE],
            global_bridge_count=g.graph[GLOBAL_BRIDGE],
            graph_entropy=g.graph[GRAPH_KEY_ENTROPY],
            layers=layers,
            thresholds_r1=thresholds_r1,
            thresholds_r2=thresholds_r2,
            node_sizes=ns,
            node_colors=nc,
            node_info_avg=float(ns_avg),
            random_network_stats=rn_stats,
            fingerprint=fingerprint,
            pos=pos,
            path=path,
        )
        results.append(result)

    return results


def _save_fingerprint(network_name, fingerprint, stats=None):
    """儲存網絡指紋與基本統計量到 JSON 快取"""
    fp_path = 'network_fingerprints.json'
    finger_prints = {}
    corr_table = {}
    network_stats = {}

    if os.path.exists(fp_path):
        try:
            import json
            with open(fp_path, 'r') as f:
                data = json.load(f)
                finger_prints = data.get('finger_prints', {})
                network_stats = data.get('network_stats', {})
        except (json.JSONDecodeError, KeyError):
            pass

    finger_prints[network_name] = {str(k): v for k, v in fingerprint.items()}

    if stats:
        network_stats[network_name] = stats

    for net_name1, net_series1 in finger_prints.items():
        corr_table[net_name1] = {}
        vals1 = list(net_series1.values())
        for net_name2, net_series2 in finger_prints.items():
            vals2 = list(net_series2.values())
            with warnings.catch_warnings():
                warnings.simplefilter('ignore', RuntimeWarning)
                c = np.corrcoef(vals1, vals2)[0, 1]
            # 當向量為常數（標準差為 0）時，corrcoef 回傳 NaN，以 0.0 取代
            corr_table[net_name1][net_name2] = 0.0 if np.isnan(c) else float(c)

    import json
    try:
        with open(fp_path, 'w') as f:
            json.dump({
                'finger_prints': finger_prints,
                'corr_table': corr_table,
                'network_stats': network_stats,
            }, f, indent=2)
    except OSError:
        pass  # 指紋快取寫入失敗不影響分析結果


def _load_fingerprints():
    """載入已儲存的網絡指紋與統計量"""
    fp_path = 'network_fingerprints.json'
    if os.path.exists(fp_path):
        import json
        try:
            with open(fp_path, 'r') as f:
                data = json.load(f)
            return (data.get('finger_prints', {}),
                    data.get('corr_table', {}),
                    data.get('network_stats', {}))
        except (json.JSONDecodeError, KeyError, OSError):
            pass
    return {}, {}, {}


def run_suite_experiment(
    suite='DEMO',
    data_dir='.',
    run_analysis=False,
    times=1000,
    debug=False,
    progress_callback=None,
):
    """
    批次實驗：對一組網絡執行分析並產生指紋比較
    原始：HETA.py:644-744（suite_experiment 函數）

    參數：
        suite: 'WS_SWN', 'NWS_SWN', 或 'DEMO'
        data_dir: 網絡檔案所在目錄
        run_analysis: True=先執行分析，False=僅讀取已有結果
        times: 隨機網絡數量
        debug: 除錯模式
        progress_callback: 進度回報函數

    回傳：SuiteExperimentResult
    """
    dataset = SUITE_DATASETS.get(suite, SUITE_DATASETS['DEMO'])
    total = len(dataset)

    if run_analysis:
        for idx, data_file in enumerate(dataset):
            file_path = os.path.join(data_dir, data_file)
            if suite == 'WS_SWN':
                file_path = os.path.join(data_dir, 'ws_swn', data_file)
            elif suite == 'NWS_SWN':
                file_path = os.path.join(data_dir, 'nws_swn', data_file)

            if progress_callback:
                progress_callback(idx, total, f"Processing {data_file}...")

            print(f"Processing {data_file}...")
            run_link_analysis(
                path=file_path,
                times=times,
                debug=debug,
                progress_callback=None,
            )

        if progress_callback:
            progress_callback(total, total, "Analysis complete.")

    # 載入指紋資料
    finger_prints, corr_table, network_stats = _load_fingerprints()

    if not finger_prints:
        return SuiteExperimentResult()

    bar = {SINK: [], GLOBAL_BRIDGE: [], LOCAL_BRIDGE: [], BOND: []}
    labels = []

    for net_name in dataset:
        name_key = net_name[:-4] + '_1'
        if name_key not in finger_prints:
            # 嘗試搜尋含路徑的 key
            found = False
            for fp_key in finger_prints:
                if fp_key.endswith(net_name[:-4] + '_1'):
                    name_key = fp_key
                    found = True
                    break
            if not found:
                continue

        net_series = finger_prints[name_key]
        labels.append(net_name[:-4])
        bar[BOND].append(float(net_series.get('0', net_series.get(0, 0))))
        bar[LOCAL_BRIDGE].append(float(net_series.get('1', net_series.get(1, 0))))
        bar[GLOBAL_BRIDGE].append(float(net_series.get('2', net_series.get(2, 0))))
        bar[SINK].append(float(net_series.get('3', net_series.get(3, 0))))

    if not labels:
        return SuiteExperimentResult()

    bar[BOND] = np.array(bar[BOND])
    bar[LOCAL_BRIDGE] = np.array(bar[LOCAL_BRIDGE])
    bar[GLOBAL_BRIDGE] = np.array(bar[GLOBAL_BRIDGE])
    bar[SINK] = np.array(bar[SINK])

    # 只有 1 個網絡時，無法計算相關矩陣與階層聚類
    if len(labels) < 2:
        return SuiteExperimentResult(
            fingerprints=finger_prints,
            corr_table=corr_table,
            labels=labels,
            bar_data=bar,
            corr_matrix=np.array([[1.0]]),
            corr_index=[0],
            corr_labels=labels[:],
            network_stats=network_stats,
        )

    # 相關矩陣
    corr_matrix_list = []
    for net_name1 in labels:
        row = []
        key1 = net_name1 + '_1'
        # 搜尋對應 key
        actual_key1 = _find_fingerprint_key(corr_table, key1)
        for net_name2 in labels:
            key2 = net_name2 + '_1'
            actual_key2 = _find_fingerprint_key(
                corr_table.get(actual_key1, {}) if actual_key1 else {}, key2)
            if actual_key1 and actual_key2:
                row.append(corr_table[actual_key1][actual_key2])
            else:
                row.append(0.0)
        corr_matrix_list.append(row)

    # 將相關矩陣轉換為距離矩陣（distance = 1 - correlation）
    # hc.linkage 要求壓縮格式（condensed form），用 squareform 轉換
    from scipy.spatial.distance import squareform
    dist_matrix = np.array([[1.0 - corr_matrix_list[i][j] for j in range(len(labels))]
                            for i in range(len(labels))])
    dist_matrix = (dist_matrix + dist_matrix.T) / 2  # 強制對稱（消除浮點誤差）
    np.fill_diagonal(dist_matrix, 0)  # 確保對角線嚴格為 0（避免浮點誤差）
    dist_condensed = squareform(dist_matrix)
    corr_cluster = hc.dendrogram(hc.linkage(dist_condensed, method='centroid'), no_plot=True)
    corr_index = corr_cluster['leaves']
    corr_result = np.zeros([len(labels), len(labels)])
    for i in range(len(labels)):
        for j in range(len(labels)):
            corr_result[i, j] = corr_matrix_list[i][j]
    corr_result = corr_result[corr_index, :]
    corr_result = corr_result[:, corr_index]
    corr_labels = [labels[i] for i in corr_index]

    return SuiteExperimentResult(
        fingerprints=finger_prints,
        corr_table=corr_table,
        labels=labels,
        bar_data=bar,
        corr_matrix=corr_result,
        corr_index=corr_index,
        corr_labels=corr_labels,
        network_stats=network_stats,
    )


def _find_fingerprint_key(d, suffix):
    """在字典中搜尋以 suffix 結尾的 key，找不到時回傳 None"""
    if suffix in d:
        return suffix
    for k in d:
        if k.endswith(suffix):
            return k
    return None
