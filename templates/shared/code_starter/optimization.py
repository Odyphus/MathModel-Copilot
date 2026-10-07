"""
优化类 code starter — 对应论文 §5.x.2 求解算法
适用: 线性规划 (LP) / 整数规划 (IP/MILP) / 二次规划 (QP) / 凸优化

库依赖:
- cvxpy (DSL, 自动选择 solver)
- scipy.optimize (轻量级)
- pulp (MILP 备选)

国赛常见用法: 调度、配比、选址、组合优化
"""

import numpy as np
import pandas as pd
import cvxpy as cp
from scipy.optimize import linprog, minimize
import matplotlib.pyplot as plt
from pathlib import Path

# ---- 全局可复现性 ----
np.random.seed(42)

# ---- 输出目录自动创建 (P2-5 修复) ----
Path("results").mkdir(exist_ok=True)
Path("figures").mkdir(exist_ok=True)


# ============================================================
# 1. LP / MILP 模板 (cvxpy)
# ============================================================
def checked_integer_solution(values, lower=0, upper=None, costs=None, budget=None, tolerance=1e-6):
    """Round within integer tolerance, then recheck the actual returned plan."""
    if values is None:
        raise ValueError("求解器未返回可行解，不能转整数或生成正式结果")
    raw = np.asarray(values, dtype=float)
    if raw.ndim != 1 or not raw.size or not np.all(np.isfinite(raw)):
        raise ValueError("求解结果必须是一维有限数值数组")
    rounded = np.rint(raw)
    if np.any(np.abs(raw - rounded) > tolerance):
        raise ValueError("求解结果偏离整数容差，不能截断或强行取整")
    if np.any(np.abs(rounded) >= np.iinfo(np.int64).max):
        raise ValueError("整数解超出可表示范围")
    result = rounded.astype(np.int64)
    if np.any(result < np.asarray(lower) - tolerance):
        raise ValueError("取整后违反下界")
    if upper is not None and np.any(result > np.asarray(upper) + tolerance):
        raise ValueError("取整后违反上界")
    if costs is not None:
        coefficients = np.asarray(costs, dtype=float)
        if coefficients.shape != result.shape or not np.all(np.isfinite(coefficients)) or budget is None or not np.isfinite(budget):
            raise ValueError("预算约束参数不完整或无效")
        if coefficients @ result > budget + tolerance:
            raise ValueError("取整后违反预算约束")
    return result


def solve_milp_template(p, c, B, x_max=50, solver=None):
    """
    最大化 sum_i (p_i - c_i) * x_i
    s.t.  sum_i c_i * x_i <= B
          0 <= x_i <= x_max, integer

    Args:
        p: ndarray (n,) 单价
        c: ndarray (n,) 成本
        B: float 总预算
        x_max: int 单品上限

    Returns:
        dict with keys: x_star, obj, status, solve_time
    """
    p, c = np.asarray(p, dtype=float), np.asarray(c, dtype=float)
    # Reuse the baseline's domain checks before invoking a solver.
    greedy_budget_baseline(p, c, B, x_max)
    n = len(p)
    x = cp.Variable(n, integer=True)
    objective = cp.Maximize((p - c) @ x)
    constraints = [
        c @ x <= B,
        x >= 0,
        x <= x_max,
    ]
    prob = cp.Problem(objective, constraints)
    installed = cp.installed_solvers()
    selected = solver or next((name for name in ("HIGHS", "SCIPY", "GLPK_MI", "CBC", "SCIP") if name in installed), None)
    if selected is None or selected not in installed:
        return {"x_star": None, "obj": None, "status": "solver_unavailable", "solve_time_s": None}
    try:
        prob.solve(solver=selected)
    except cp.error.SolverError as exc:
        return {"x_star": None, "obj": None, "status": "solver_error", "solve_time_s": None, "error": str(exc)}
    result = {"x_star": None, "obj": None, "status": prob.status,
              "solve_time_s": getattr(prob.solver_stats, "solve_time", None), "solver": selected}
    if prob.status != "optimal":
        return result
    try:
        solution = checked_integer_solution(x.value, 0, x_max, c, B)
    except ValueError as exc:
        result.update(status="invalid_solution", error=str(exc))
        return result
    result.update(x_star=solution, obj=float((p - c) @ solution), feasibility_verified=True)
    return result


# ============================================================
# 2. 凸优化模板 (cvxpy)
# ============================================================
def solve_convex_template(A, b, lambda_reg=0.1):
    """
    Ridge 回归示例:
    minimize ||A x - b||_2^2 + lambda * ||x||_2^2
    """
    n = A.shape[1]
    x = cp.Variable(n)
    objective = cp.Minimize(cp.sum_squares(A @ x - b) + lambda_reg * cp.sum_squares(x))
    prob = cp.Problem(objective)
    prob.solve()
    return {"x_star": x.value, "obj": prob.value, "status": prob.status}


# ============================================================
# 3. 多目标 (加权法) 模板
# ============================================================
def solve_multiobjective_weighted(objs, constraints, weights):
    """
    minimize sum_k w_k * f_k(x)

    Args:
        objs: list of cvxpy expressions, 每个是一个目标
        constraints: list of cvxpy constraints
        weights: list of float, 加权 (∑=1)
    """
    weighted_obj = sum(w * o for w, o in zip(weights, objs))
    prob = cp.Problem(cp.Minimize(weighted_obj), constraints)
    prob.solve()
    return prob


# ============================================================
# 4. 启发式 (遗传算法 GA, 自实现简化版)
# ============================================================
def genetic_algorithm(fitness, n_vars, bounds, n_pop=100, n_gen=200,
                      crossover_rate=0.8, mutation_rate=0.1):
    """
    自适应交叉率 GA (winning_patterns §4 命名变体写法)
    """
    pop = np.random.uniform(bounds[0], bounds[1], (n_pop, n_vars))
    best_history = []

    for gen in range(n_gen):
        scores = np.array([fitness(ind) for ind in pop])
        # 轮盘赌选择
        probs = scores / scores.sum() if scores.sum() > 0 else np.ones(n_pop) / n_pop
        indices = np.random.choice(n_pop, n_pop, p=probs)
        new_pop = pop[indices].copy()
        # 交叉
        for i in range(0, n_pop - 1, 2):
            if np.random.random() < crossover_rate:
                point = np.random.randint(1, n_vars)
                new_pop[i, point:], new_pop[i+1, point:] = \
                    new_pop[i+1, point:].copy(), new_pop[i, point:].copy()
        # 变异
        mask = np.random.random((n_pop, n_vars)) < mutation_rate
        noise = np.random.normal(0, 0.1, (n_pop, n_vars))
        new_pop = np.where(mask, new_pop + noise, new_pop)
        new_pop = np.clip(new_pop, bounds[0], bounds[1])
        pop = new_pop
        best_history.append(scores.max())

    best_idx = np.argmax([fitness(ind) for ind in pop])
    return {"x_star": pop[best_idx], "obj": fitness(pop[best_idx]), "history": best_history}


# ============================================================
# 5. 可行贪心基线
# ============================================================
def greedy_budget_baseline(p, c, B, x_max=50):
    """按单位成本利润从高到低分配预算, 返回可行的整数基线。

    与“每个产品都单独使用整份预算”不同, 本基线在所有产品间
    共享同一个剩余预算, 因此始终满足 ``c @ x <= B``。
    """
    p = np.asarray(p, dtype=float)
    c = np.asarray(c, dtype=float)
    if p.ndim != 1 or c.ndim != 1 or p.shape != c.shape:
        raise ValueError("p 和 c 必须是形状相同的一维数组")
    if not np.all(np.isfinite(p)) or not np.all(np.isfinite(c)):
        raise ValueError("p 和 c 必须全部为有限数")
    if np.any(c < 0):
        raise ValueError("成本 c 不能为负数")
    if not np.isfinite(B) or B < 0:
        raise ValueError("预算 B 必须是非负有限数")

    if np.isscalar(x_max):
        caps = np.full(len(p), x_max, dtype=float)
    else:
        caps = np.asarray(x_max, dtype=float)
        if caps.shape != p.shape:
            raise ValueError("数组形式的 x_max 必须与 p 形状相同")
    if (not np.all(np.isfinite(caps)) or np.any(caps < 0)
            or not np.all(caps == np.floor(caps))):
        raise ValueError("x_max 必须是非负整数")
    caps = caps.astype(int)

    margin = p - c
    x = np.zeros(len(p), dtype=int)

    # 零成本且正利润的产品不消耗预算, 可直接取上限。
    free_profitable = (c == 0) & (margin > 0)
    x[free_profitable] = caps[free_profitable]

    candidates = np.flatnonzero((c > 0) & (margin > 0) & (caps > 0))
    ratios = margin[candidates] / c[candidates]
    # 先比单位成本利润, 同比率时先选单件利润更高者。
    order = candidates[np.lexsort((-margin[candidates], -ratios))]

    remaining = float(B)
    for i in order:
        affordable = int(np.floor(remaining / c[i] + 1e-12))
        quantity = min(caps[i], max(0, affordable))
        # 抵消浮点数据刚好在整数边界时可能的越界。
        while quantity > 0 and quantity * c[i] > remaining + 1e-10:
            quantity -= 1
        x[i] = quantity
        remaining -= quantity * c[i]

    budget_used = float(c @ x)
    if budget_used > B + 1e-8:
        raise RuntimeError("贪心基线产生了不可行解")
    return {
        "x_star": x,
        "obj": float(margin @ x),
        "budget_used": budget_used,
    }


# ============================================================
# 6. Sanity check 套件 (anti_pattern D2)
# ============================================================
def sanity_check(result, expected_range=None, baseline=None):
    """
    四步 sanity check:
    1. 状态正常?
    2. 数量级合理?
    3. 边界 case?
    4. 比 baseline 强?
    """
    checks = {}
    checks["status_ok"] = str(result.get("status", "")).lower() in ["optimal", "ok", "success"]
    x = result.get("x_star")
    obj = result.get("obj")
    valid = x is not None and np.all(np.isfinite(x)) and obj is not None and np.isfinite(obj)
    checks["finite_solution"] = bool(valid)
    if expected_range:
        x = np.asarray(x) if valid else None
        checks["range_ok"] = bool(valid and np.all((x >= expected_range[0]) & (x <= expected_range[1])))
    if baseline is not None:
        checks["beats_baseline"] = bool(valid and obj >= baseline - 1e-9)
    return checks


# ============================================================
# 7. 主流程示例 (Q1 求解, 对应论文 §5.1)
# ============================================================
if __name__ == "__main__":
    # 加载数据 (示例数据, 实际从附件读)
    n = 100
    p = np.random.uniform(50, 200, n)
    c = np.random.uniform(20, 100, n)
    B = 100000

    # 求解
    result = solve_milp_template(p, c, B, x_max=50)
    print(f"Q1 状态: {result['status']}")
    print(f"Q1 利润: {result['obj']} 元")
    print(f"Q1 求解时间: {result['solve_time_s']} s")

    # Sanity check
    baseline_result = greedy_budget_baseline(p, c, B, x_max=50)
    baseline_profit = baseline_result["obj"]
    checks = sanity_check(result, expected_range=(0, 50), baseline=baseline_profit)
    print(f"Sanity checks: {checks}")
    if not all(checks.values()):
        raise SystemExit("求解或校验未通过，未保存正式结果；请检查状态和约束")
    if abs(baseline_profit) > 1e-12:
        improvement = (result["obj"] - baseline_profit) / abs(baseline_profit) * 100
        print(f"相对贪心 baseline 提升: {improvement:.2f}%")
    else:
        print("相对贪心 baseline 提升: baseline 为 0, 不计算百分比")

    # 保存结果 (供 stage 6 灵敏度复用)
    np.save("results/Q1_x_star.npy", result["x_star"])

    # 可视化
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.bar(range(n), result["x_star"], color='steelblue')
    ax.set_xlabel("产品编号")
    ax.set_ylabel("最优产量 (件)")
    ax.set_title("Q1 最优生产计划")
    plt.tight_layout()
    plt.savefig("figures/Q1_x_star.png", dpi=300)
    print("已保存 figures/Q1_x_star.png")
