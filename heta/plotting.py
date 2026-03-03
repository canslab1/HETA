# -*- coding: utf-8 -*-
"""
繪圖模組：使用 matplotlib 物件導向 API，每個函數回傳 Figure 物件
原始：HETA.py 的繪圖程式碼（lines 518-637, 690-743）

所有函數使用 Figure() 而非 plt.figure()，確保執行緒安全且可嵌入 GUI。
"""

import numpy as np
import networkx as nx
import scipy.cluster.hierarchy as hc
from matplotlib.figure import Figure
from matplotlib.lines import Line2D

from heta.constants import *
from heta.engine import network_clustering


def create_network_figure(result):
    """
    繪製目標網絡的連結分類結果
    原始：HETA.py:519-543
    """
    g = result.graph
    pos = result.pos
    path = result.path

    is_special = path.endswith(tuple(SPECIAL_NETWORKS))
    figsize = (4, 6) if is_special else (6, 6)
    fig = Figure(figsize=figsize, dpi=200, facecolor='white')
    ax = fig.add_subplot(111)

    if is_special:
        bb_width = [0.1 if g[s][t][EDGE_KEY_LAYER + str(result.layers)] == BOND else 0.5
                    for (s, t) in g.edges()]
        ns = [0.5 for _ in g.nodes()]
    else:
        bb_width = [g[s][t][EDGE_KEY_WIDTH] for (s, t) in g.edges()]
        ax.set_title(f'target network = {result.network_name}')
        ns = result.node_sizes

    bb_color = [g[s][t][EDGE_KEY_COLOR] for (s, t) in g.edges()]
    nc = result.node_colors

    ax.axis('off')

    if is_special:
        nx.draw_networkx(g, with_labels=False, pos=pos, node_size=ns,
                         linewidths=0.5, edge_color=bb_color, width=bb_width, ax=ax)
    else:
        nx.draw_networkx(g, pos=pos, linewidths=0, width=bb_width,
                         node_size=ns, node_color=nc, font_size=8,
                         edge_color=bb_color, ax=ax)

    # 邊類型圖例
    legend_items = [
        Line2D([0], [0], color=BOND_COLOR, lw=2, label=BOND),
        Line2D([0], [0], color=LOCAL_BRIDGE_COLOR, lw=2, label=LOCAL_BRIDGE),
        Line2D([0], [0], color=GLOBAL_BRIDGE_COLOR, lw=2, label=GLOBAL_BRIDGE),
        Line2D([0], [0], color=SINK_COLOR, lw=2, label=SINK),
    ]
    ax.legend(handles=legend_items, loc='lower center', ncol=4,
              fontsize=7, framealpha=0.8, fancybox=True)

    fig.set_tight_layout(True)
    return fig


def create_detail_layer_figure(result, layer_num):
    """
    繪製特定層級的詳細分析圖（含邊權重標籤）
    原始：HETA.py:546-559

    參數：
        result: LinkAnalysisResult
        layer_num: 層級編號（1-based）
    """
    g = result.graph
    pos = result.pos

    sub_edge_label = {}
    for s, t in g.edges():
        sub_edge_label[(s, t)] = round(g[s][t][-layer_num], 3)

    bb_width = [g[s][t][EDGE_KEY_WIDTH] for (s, t) in g.edges()]
    bb_color = [g[s][t][EDGE_KEY_COLOR] for (s, t) in g.edges()]

    fig = Figure(figsize=(12, 8), facecolor='white')
    ax = fig.add_subplot(111)

    r1 = round(result.thresholds_r1.get(str(layer_num), 0), 4)
    r2 = round(result.thresholds_r2.get(str(layer_num), 0), 4)
    ax.set_title(f'target network = {result.network_name} (layer {layer_num}, R1 = {r1}, R2 = {r2})')

    nx.draw_networkx(g, pos=pos, linewidths=0, width=bb_width,
                     node_size=result.node_sizes, node_color=result.node_colors,
                     font_size=8, edge_color=bb_color, ax=ax)
    nx.draw_networkx_edge_labels(g, pos=pos, edge_labels=sub_edge_label,
                                 font_size=6, ax=ax)

    fig.set_tight_layout(True)
    return fig


def create_betweenness_figure(result):
    """
    繪製邊介數中心性圖
    原始：HETA.py:562-573
    """
    g = result.graph
    pos = result.pos

    eb_raw = nx.edge_betweenness_centrality(g)
    # 建立雙向查詢表：(s,t) 和 (t,s) 都能查到同一個 betweenness 值
    # 避免 g.edges() 的 tuple 順序與 eb_raw 的 key 順序不一致導致 KeyError
    eb = {}
    for (s, t), val in eb_raw.items():
        rounded = round(val, 3)
        eb[(s, t)] = rounded
        eb[(t, s)] = rounded

    eb_values = [eb[(s, t)] for s, t in g.edges()]
    min_eb = min(eb_values)
    std_eb = np.std(eb_values)
    if std_eb == 0:
        std_eb = 1.0

    bn_width = [0.5 + ((eb[(s, t)] - min_eb) / std_eb) for (s, t) in g.edges()]

    fig = Figure(figsize=(12, 8), facecolor='white')
    ax = fig.add_subplot(111)
    ax.set_title(f'Target network = {result.network_name} (betweenness centrality for edges)')

    nx.draw_networkx(g, pos=pos, linewidths=0, width=bn_width,
                     node_size=result.node_sizes, node_color=result.node_colors,
                     font_size=8, ax=ax)
    eb_labels = {(s, t): eb[(s, t)] for s, t in g.edges()}
    nx.draw_networkx_edge_labels(g, pos=pos, edge_labels=eb_labels, font_size=6, ax=ax)

    fig.set_tight_layout(True)
    return fig


def create_pagerank_figure(result):
    """
    繪製 PageRank 權重圖
    原始：HETA.py:576-598
    """
    g = result.graph
    pos = result.pos

    # 建立 line graph：每條邊作為一個節點，共享端點的邊之間建立連結
    # 使用正規化 tuple（小端在前）避免 (a,b) 和 (b,a) 產生重複幽靈節點
    def _edge_key(u, v):
        return (u, v) if u <= v else (v, u)

    edge_keys = [_edge_key(s, t) for s, t in g.edges()]
    pg = nx.Graph()
    pg.add_nodes_from(edge_keys)
    for pair in edge_keys:
        for vertex in pair:
            for node in g.neighbors(vertex):
                neighbor_key = _edge_key(vertex, node)
                if neighbor_key in pg and pair != neighbor_key:
                    pg.add_edge(pair, neighbor_key)

    pr = nx.pagerank(pg, max_iter=2000)
    for key in list(pr.keys()):
        pr[key] = round(pr[key], 4)

    pr_values = list(pr.values())
    min_pr = min(pr_values)
    std_pr = np.std(pr_values)
    if std_pr == 0:
        std_pr = 1.0

    # 使用正規化的 key 查詢 PageRank 值
    pg_width = [(pr[_edge_key(s, t)] - min_pr) / std_pr for (s, t) in g.edges()]

    # 建立以原始 edge tuple 為 key 的 edge_labels（供 draw_networkx_edge_labels 使用）
    edge_pr_labels = {(s, t): pr[_edge_key(s, t)] for s, t in g.edges()}

    fig = Figure(figsize=(12, 8), facecolor='white')
    ax = fig.add_subplot(111)
    ax.set_title(f'Target network = {result.network_name} (pagerank-based weighting for edges)')

    nx.draw_networkx(g, pos=pos, linewidths=0, width=pg_width,
                     node_size=result.node_sizes, node_color=result.node_colors,
                     font_size=8, ax=ax)
    nx.draw_networkx_edge_labels(g, pos=pos, edge_labels=edge_pr_labels, font_size=6, ax=ax)

    fig.set_tight_layout(True)
    return fig


def create_degree_distribution_figure(result):
    """
    繪製度分佈圖：直方圖 + log-log 散佈圖（雙面板）

    左側：度數直方圖（線性座標），直觀呈現整體分佈形狀。
    右側：log-log 散佈圖，用於判斷是否符合冪律分佈（scale-free 特徵）。
    """
    g = result.graph
    degrees = [d for _, d in g.degree()]

    from collections import Counter
    deg_count = Counter(degrees)
    ks = sorted(deg_count.keys())
    pk = [deg_count[k] / len(degrees) for k in ks]

    fig = Figure(figsize=(12, 5), facecolor='white')

    # 左：直方圖
    ax1 = fig.add_subplot(121)
    max_deg = max(degrees)
    bins = range(0, max_deg + 2)
    ax1.hist(degrees, bins=bins, color='steelblue', edgecolor='white', align='left')
    ax1.set_xlabel('Degree (k)')
    ax1.set_ylabel('Count')
    ax1.set_title(f'{result.network_name} — Degree Distribution')

    # 右：log-log
    ax2 = fig.add_subplot(122)
    ax2.scatter(ks, pk, s=30, color='steelblue', edgecolors='navy', zorder=3)
    ax2.set_xscale('log')
    ax2.set_yscale('log')
    ax2.set_xlabel('Degree k (log)')
    ax2.set_ylabel('P(k) (log)')
    ax2.set_title(f'{result.network_name} — Log-Log Degree Distribution')
    ax2.grid(True, which='both', ls='--', alpha=0.4)

    fig.set_tight_layout(True)
    return fig


def create_clustering_figure(result):
    """
    繪製階層式社群分割結果
    原始：HETA.py:601-617
    """
    g = result.graph
    pos = result.pos

    network_clustering(g, result.layers)

    ncc_map = {}
    color_count = 1
    for v in g.nodes():
        if g.nodes[v][NODE_KEY_GROUP_NUMBER] not in ncc_map:
            ncc_map[g.nodes[v][NODE_KEY_GROUP_NUMBER]] = color_count
            color_count += 1
    ncc = [ncc_map[g.nodes[v][NODE_KEY_GROUP_NUMBER]] for v in g.nodes()]

    bb_width = [g[s][t][EDGE_KEY_WIDTH] for (s, t) in g.edges()]
    bb_color = [g[s][t][EDGE_KEY_COLOR] for (s, t) in g.edges()]

    fig = Figure(figsize=(12, 8), facecolor='white')
    ax = fig.add_subplot(111)
    ax.set_title(f'Target network = {result.network_name} (clustering result)')

    import matplotlib.pyplot as plt
    nx.draw_networkx(g, pos=pos, linewidths=0, width=bb_width,
                     node_color=ncc, vmin=min(ncc), vmax=max(ncc),
                     cmap=plt.cm.Dark2, font_size=8, edge_color=bb_color, ax=ax)

    fig.set_tight_layout(True)
    return fig


def create_fingerprint_chart(suite_result, suite_name=''):
    """
    繪製網絡指紋堆疊長條圖
    原始：HETA.py:690-705

    排序方式與 Correlation heatmap / Dendrogram 一致（階層聚類順序），
    便於三張圖表並列比較。
    """
    # 使用階層聚類排序，與 correlation heatmap 和 dendrogram 一致
    if suite_result.corr_index and len(suite_result.corr_index) == len(suite_result.labels):
        order = suite_result.corr_index
        labels = [suite_result.labels[i] for i in order]
        bar = {
            k: v[order] if hasattr(v, '__getitem__') and hasattr(v, 'dtype') else v
            for k, v in suite_result.bar_data.items()
        }
    else:
        labels = suite_result.labels
        bar = suite_result.bar_data
    index = np.arange(len(labels))
    width = 0.5

    fig = Figure(figsize=(12, 8), facecolor='white')
    ax = fig.add_subplot(111)

    if suite_name:
        ax.set_title(f'Network Fingerprints — {suite_name}', pad=40)

    p1 = ax.bar(index, bar[BOND], width, color=BOND_COLOR, edgecolor=BOND_COLOR)
    p2 = ax.bar(index, bar[LOCAL_BRIDGE], width, color=LOCAL_BRIDGE_COLOR,
                edgecolor=LOCAL_BRIDGE_COLOR, bottom=bar[BOND])
    p3 = ax.bar(index, bar[GLOBAL_BRIDGE], width, color=GLOBAL_BRIDGE_COLOR,
                edgecolor=GLOBAL_BRIDGE_COLOR, bottom=bar[BOND] + bar[LOCAL_BRIDGE])
    p4 = ax.bar(index, bar[SINK], width, color=SINK_COLOR,
                edgecolor=SINK_COLOR, bottom=bar[BOND] + bar[LOCAL_BRIDGE] + bar[GLOBAL_BRIDGE])

    ax.xaxis.tick_top()
    ax.set_xticks(index)
    ax.set_xticklabels(labels, rotation=90)
    ax.set_ylabel('Percentage')
    ax.set_yticks(np.arange(0, 1.01, 0.1))
    ax.set_ylim(0, 1.)
    ax.legend((p1[0], p2[0], p3[0], p4[0]),
              (BOND, LOCAL_BRIDGE, GLOBAL_BRIDGE, SINK),
              loc='lower center', fancybox=True, shadow=True, ncol=4)

    # 隱藏刻度線（取代已移除的 tick1On/tick2On）
    for t in ax.xaxis.get_major_ticks():
        t.tick1line.set_visible(False)
        t.tick2line.set_visible(False)
    for t in ax.yaxis.get_major_ticks():
        t.tick1line.set_visible(False)
        t.tick2line.set_visible(False)

    fig.set_tight_layout(True)
    return fig


def create_correlation_heatmap(suite_result, suite_name=''):
    """
    繪製相關係數矩陣熱力圖
    原始：HETA.py:707-735
    """
    corr_coef = np.array(suite_result.corr_matrix)
    corr_labels = suite_result.corr_labels

    fig = Figure(figsize=(11, 11))
    ax = fig.add_subplot(111)

    if suite_name:
        ax.set_title(f'Fingerprint Correlation — {suite_name}', pad=40)

    import matplotlib.pyplot as plt
    ccmap = ax.pcolor(corr_coef, vmin=-1.0, vmax=1.0, cmap=plt.cm.RdBu, alpha=0.8)
    fig.colorbar(ccmap, ax=ax)

    ax.set_frame_on(False)
    ax.set_xticks(np.arange(corr_coef.shape[0]) + 0.5, minor=False)
    ax.set_yticks(np.arange(corr_coef.shape[1]) + 0.5, minor=False)
    ax.invert_yaxis()
    ax.xaxis.tick_top()
    ax.set_xticklabels(corr_labels, minor=False, rotation=90)
    ax.set_yticklabels(corr_labels, minor=False)
    ax.grid(False)

    for t in ax.xaxis.get_major_ticks():
        t.tick1line.set_visible(False)
        t.tick2line.set_visible(False)
    for t in ax.yaxis.get_major_ticks():
        t.tick1line.set_visible(False)
        t.tick2line.set_visible(False)

    fig.set_tight_layout(True)
    return fig


def create_dendrogram_figure(suite_result, suite_name=''):
    """
    繪製階層聚類樹狀圖
    原始：HETA.py:737-742
    """
    labels = suite_result.labels

    # 重建相關矩陣（未排序版本）
    n = len(labels)

    # 階層聚類至少需要 2 個網絡
    if n < 2:
        fig = Figure(figsize=(12, 8), facecolor='white')
        ax = fig.add_subplot(111)
        ax.text(0.5, 0.5, 'Need at least 2 networks for dendrogram',
                ha='center', va='center', transform=ax.transAxes, fontsize=14)
        ax.set_axis_off()
        fig.set_tight_layout(True)
        return fig

    corr_matrix = suite_result.corr_matrix
    # 需要從原始 corr_table 重建未排序矩陣
    # 使用 bar_data 反推指紋向量做 linkage
    fingerprint_vectors = []
    for i in range(n):
        vec = [
            float(suite_result.bar_data[BOND][i]),
            float(suite_result.bar_data[LOCAL_BRIDGE][i]),
            float(suite_result.bar_data[GLOBAL_BRIDGE][i]),
            float(suite_result.bar_data[SINK][i]),
        ]
        fingerprint_vectors.append(vec)

    # 計算相關矩陣
    import warnings as _warnings
    corr_mat = []
    for i in range(n):
        row = []
        for j in range(n):
            with _warnings.catch_warnings():
                _warnings.simplefilter('ignore', RuntimeWarning)
                c = np.corrcoef(fingerprint_vectors[i], fingerprint_vectors[j])[0, 1]
            # 當向量為常數（標準差為 0）時，corrcoef 回傳 NaN，以 0.0 取代
            row.append(0.0 if np.isnan(c) else c)
        corr_mat.append(row)

    # 將相關矩陣轉換為距離矩陣（distance = 1 - correlation）
    # hc.linkage 要求壓縮格式（condensed form），用 squareform 轉換
    from scipy.spatial.distance import squareform
    dist_mat = np.array([[1.0 - corr_mat[i][j] for j in range(n)] for i in range(n)])
    dist_mat = (dist_mat + dist_mat.T) / 2  # 強制對稱（消除浮點誤差）
    np.fill_diagonal(dist_mat, 0)  # 確保對角線嚴格為 0（避免浮點誤差）
    dist_condensed = squareform(dist_mat)

    fig = Figure(figsize=(12, 8), facecolor='white')
    ax = fig.add_subplot(111)

    if suite_name:
        ax.set_title(f'Hierarchical Clustering — {suite_name}')

    hc.dendrogram(hc.linkage(dist_condensed, method='centroid'),
                  no_plot=False, labels=labels, ax=ax)

    ax.tick_params(axis='x', rotation=90)
    ax.set_yticks([])

    fig.set_tight_layout(True)
    return fig
