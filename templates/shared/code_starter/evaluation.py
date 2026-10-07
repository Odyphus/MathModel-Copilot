"""
评价类 code starter — 对应论文 §5.x 综合评价
适用: AHP / 熵权法 / TOPSIS / 模糊综合评价

常见组合示例: AHP-熵权-TOPSIS。仅在主客观权重与距离排序都符合题意时使用。
"""

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path

np.random.seed(42)
Path("results").mkdir(exist_ok=True)
Path("figures").mkdir(exist_ok=True)


# ============================================================
# 1. AHP 层次分析 (主观赋权)
# ============================================================
def ahp_weights(judgment_matrix):
    """
    Args:
        judgment_matrix: (n, n) 判断矩阵, A[i,j] = i 相对 j 的重要性
                         A[i,j] * A[j,i] = 1, 对角线为 1
    Returns:
        dict with keys: weights, CR, lambda_max
    """
    n = judgment_matrix.shape[0]
    # 几何平均法
    geo_mean = np.prod(judgment_matrix, axis=1) ** (1.0 / n)
    weights = geo_mean / geo_mean.sum()
    # 一致性检验
    Aw = judgment_matrix @ weights
    lambda_max = (Aw / weights).mean()
    CI = (lambda_max - n) / (n - 1) if n > 1 else 0
    # RI 表 (n=1..15)
    RI_table = {1: 0, 2: 0, 3: 0.58, 4: 0.90, 5: 1.12, 6: 1.24, 7: 1.32,
                8: 1.41, 9: 1.45, 10: 1.49, 11: 1.51, 12: 1.48, 13: 1.56,
                14: 1.57, 15: 1.59}
    RI = RI_table.get(n, 1.59)
    CR = CI / RI if RI > 0 else 0
    return {"weights": weights, "CR": CR, "lambda_max": lambda_max,
            "consistent": CR < 0.1}


# ============================================================
# 2. 熵权法 (客观赋权)
# ============================================================
def entropy_weights(X, indicator_types=None):
    """
    Args:
        X: (m, n) 评价矩阵, m 个对象, n 个指标
        indicator_types: list of "+" or "-", 长度 n. 默认全 "+" (正向)
    """
    X = np.asarray(X, dtype=float)
    if X.ndim != 2 or X.shape[0] == 0 or X.shape[1] == 0:
        raise ValueError("X 必须是非空二维评价矩阵")
    if not np.all(np.isfinite(X)):
        raise ValueError("X 不能包含 NaN 或无穷大")

    m, n = X.shape
    if indicator_types is None:
        indicator_types = ["+" for _ in range(n)]
    if len(indicator_types) != n or any(t not in {"+", "-"} for t in indicator_types):
        raise ValueError("indicator_types 必须与指标数相同, 且只能包含 '+' 或 '-'")

    # 标准化
    X_norm = np.empty_like(X, dtype=float)
    col_min = X.min(axis=0)
    col_max = X.max(axis=0)
    spread = col_max - col_min
    constant_mask = np.isclose(col_max, col_min, rtol=1e-12, atol=1e-12)
    for j in range(n):
        if constant_mask[j]:
            # 常数列对所有对象的信息完全相同, 其比例应为均匀分布。
            X_norm[:, j] = 1.0
        elif indicator_types[j] == "+":
            X_norm[:, j] = (X[:, j] - col_min[j]) / spread[j]
        else:  # "-"
            X_norm[:, j] = (col_max[j] - X[:, j]) / spread[j]

    # 计算比例
    P = X_norm / X_norm.sum(axis=0, keepdims=True)
    # 熵
    if m == 1:
        e = np.ones(n)
    else:
        P_safe = np.where(P > 0, P, 1)
        e = -1 / np.log(m) * (P * np.log(P_safe)).sum(axis=0)
        e = np.clip(e, 0.0, 1.0)
    e[constant_mask] = 1.0
    # 差异系数
    d = np.maximum(0.0, 1 - e)
    d[constant_mask] = 0.0
    # 权重
    if d.sum() <= 1e-12:
        # 所有指标都无区分度时, 熵权本身无法区分它们;
        # 用均匀权重作为可解释的中性退化策略。
        weights = np.full(n, 1.0 / n)
    else:
        weights = d / d.sum()
    return {"weights": weights, "entropy": e, "constant_mask": constant_mask}


# ============================================================
# 3. TOPSIS (多属性决策)
# ============================================================
def topsis(X, weights, indicator_types=None):
    """
    与正负理想解的距离

    Args:
        X: (m, n) 评价矩阵
        weights: (n,) 权重
        indicator_types: list of "+" or "-"
    Returns:
        dict with keys: scores, rank, positive_ideal, negative_ideal
    """
    m, n = X.shape
    if indicator_types is None:
        indicator_types = ["+" for _ in range(n)]

    # 向量归一化
    X_norm = X / np.sqrt((X ** 2).sum(axis=0, keepdims=True) + 1e-12)
    # 加权
    V = X_norm * weights
    # 正负理想
    A_pos = np.array([V[:, j].max() if indicator_types[j] == "+" else V[:, j].min()
                       for j in range(n)])
    A_neg = np.array([V[:, j].min() if indicator_types[j] == "+" else V[:, j].max()
                       for j in range(n)])
    # 距离
    D_pos = np.sqrt(((V - A_pos) ** 2).sum(axis=1))
    D_neg = np.sqrt(((V - A_neg) ** 2).sum(axis=1))
    # 相对接近度
    C = D_neg / (D_pos + D_neg + 1e-12)
    rank = np.argsort(-C)  # 降序
    return {"scores": C, "rank": rank, "positive_ideal": A_pos, "negative_ideal": A_neg}


# ============================================================
# 4. AHP-熵权-TOPSIS 组合示例
# ============================================================
def ahp_entropy_topsis(X, judgment_matrix, indicator_types=None, alpha=0.5):
    """
    动态权重 AHP-熵权混合 + TOPSIS 综合评价

    Args:
        X: (m, n)
        judgment_matrix: (n, n) AHP 判断矩阵
        indicator_types: list
        alpha: 主客观权重融合比例, 0 = 全客观, 1 = 全主观
    """
    ahp = ahp_weights(judgment_matrix)
    if not ahp["consistent"]:
        print(f"⚠ AHP CR = {ahp['CR']:.3f} > 0.1, 一致性较差")
    ent = entropy_weights(X, indicator_types)
    # 组合权重
    combined_weights = alpha * ahp["weights"] + (1 - alpha) * ent["weights"]
    combined_weights = combined_weights / combined_weights.sum()
    # TOPSIS
    result = topsis(X, combined_weights, indicator_types)
    return {
        "ahp_weights": ahp["weights"],
        "entropy_weights": ent["weights"],
        "combined_weights": combined_weights,
        "topsis_scores": result["scores"],
        "rank": result["rank"],
    }


# ============================================================
# 5. 模糊综合评价 (FCE)
# ============================================================
def fuzzy_comprehensive_evaluation(R, weights, evaluation_grades=None):
    """
    Args:
        R: (n, k) 模糊关系矩阵, n 指标, k 评价等级
        weights: (n,) 指标权重
        evaluation_grades: (k,) 等级分值, 默认 [1, 0.8, 0.6, 0.4, 0.2]
    """
    if evaluation_grades is None:
        evaluation_grades = np.array([1.0, 0.8, 0.6, 0.4, 0.2])

    # B = w · R, M(·, +) 算子
    B = weights @ R
    B_norm = B / B.sum()
    score = np.dot(B_norm, evaluation_grades)
    return {"comprehensive_vector": B_norm, "score": score}


# ============================================================
# 6. 可视化辅助
# ============================================================
def plot_weights_comparison(ahp_w, entropy_w, combined_w, indicator_names=None):
    n = len(ahp_w)
    if indicator_names is None:
        indicator_names = [f"指标 {i+1}" for i in range(n)]
    x = np.arange(n)
    width = 0.25
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.bar(x - width, ahp_w, width, label="AHP", color="steelblue")
    ax.bar(x, entropy_w, width, label="熵权", color="seagreen")
    ax.bar(x + width, combined_w, width, label="组合", color="orangered")
    ax.set_xticks(x)
    ax.set_xticklabels(indicator_names, rotation=30)
    ax.set_ylabel("权重")
    ax.set_title("AHP-熵权-TOPSIS 权重对比")
    ax.legend()
    plt.tight_layout()
    return fig


# ============================================================
# 主流程示例 (对应论文 §5.x)
# ============================================================
if __name__ == "__main__":
    # 模拟数据: 5 个对象, 4 个指标
    X = np.array([
        [85, 90, 78, 92],
        [72, 88, 85, 80],
        [95, 75, 90, 85],
        [80, 82, 88, 78],
        [70, 95, 82, 88],
    ])
    indicator_types = ["+", "+", "+", "+"]

    # AHP 判断矩阵 (4x4)
    A = np.array([
        [1, 2, 3, 4],
        [1/2, 1, 2, 3],
        [1/3, 1/2, 1, 2],
        [1/4, 1/3, 1/2, 1],
    ])

    result = ahp_entropy_topsis(X, A, indicator_types, alpha=0.5)
    print(f"AHP 权重: {result['ahp_weights']}")
    print(f"熵权: {result['entropy_weights']}")
    print(f"组合权重: {result['combined_weights']}")
    print(f"TOPSIS 得分: {result['topsis_scores']}")
    print(f"排名: {result['rank'] + 1}")  # 转 1-based

    # 可视化
    fig = plot_weights_comparison(
        result["ahp_weights"], result["entropy_weights"],
        result["combined_weights"], ["指标A", "指标B", "指标C", "指标D"]
    )
    plt.savefig("figures/evaluation_weights.png", dpi=300)
    print("已保存 figures/evaluation_weights.png")
