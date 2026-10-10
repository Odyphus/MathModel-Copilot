# 方法卡：线性与混合整数优化

**适用：** 可明确写成线性目标与线性约束的配比、分配、采购、调度；整数标记用于需要整件选择的变量。储能、弃光、效率、承诺和边界是否正确是题目模型问题，通用求解器不会替你补上。

**入口：** `templates/shared/code_starter/optimization.py` 的 `solve_linear_program` 和 `check_linear_solution`；需要常见预算例时保留 `solve_milp_template`、`greedy_budget_baseline`。先锁定 ModelSpec、ParameterSet、DataContract、实际 CodeManifest 和独立 ValidationPlan，再通过现有 `run/validate` 执行。

```python
result = solve_linear_program(
    [1, 2], A_ub=[[-1, -1]], b_ub=[-4],
    bounds=[(0, None), (0, None)], maximize=False,
    tolerance=1e-7,
)
# 已知最小值为 4；约束是 x+y>=4，不是固定等式。
```

输入统一为 `A_ub*x<=b_ub`、`A_eq*x=b_eq`。每个变量各给一个 bounds；未给时为非负连续变量。`integer=[0,1,...]` 明确哪些为整数，不支持半连续或半整数。`maximize` 必须明确为布尔值；返回目标按原方向重新计算。

| 状态 | 能说明什么 |
|---|---|
| `optimal` | 求解器报告成功，返回向量重算约束通过；整数相对 gap 不超过声明容差 |
| `feasible_not_proven` | 有实际可行向量，但达到限制或 gap 尚未支持最优判断 |
| `limit_reached` | 达到求解限制，未取得可用可行向量 |
| `infeasible / unbounded` | 求解器报告不可行/无界，不产生可用结果数值 |
| `invalid_solution` | 取得向量但数值、约束或整数重检查失败 |
| `solver_unavailable / solver_error` | 后端缺失/运行失败，不等于模型不可行 |

返回实际 SciPy/HiGHS 入口、SciPy 版本、原始状态/信息、时间、选项、gap、约束残差、容差和证明范围。`feasibility_verified` 是内部线性向量检查标记，不是项目的 verified Result；项目核验仍需独立 checker。整数仅在整数容差内取整，取整后重算所有约束。

**验证基线：** 解析 LP、含等式与不等式的已知例、小整数范围穷举、故意不可行/无界和非法向量。等价最优解比较目标与可行性，不要求同一向量；贪心一般只给可行基线，不能冒充全局最优。

**容差与局限：** `1e-7` 是小例的默认绝对数值容差，不是所有物理单位的通用误差。先对系数/单位与量级作合理规范化，再在模型与 checker 中分别注明各约束容差及单位。求解器成功不能证明模型适合题意；复杂物理调度的专用 checker、因果约束和桥梁测试留待具体题目建立。

**依赖：** `analysis` extra 提供 SciPy、NumPy 等；CVXPY DSL 在 `advanced` extra。缺 CVXPY 时预算 MILP 可走 SciPy 路径，不要求为了 LP 额外安装 DSL。

接口与求解状态依据：[SciPy linprog](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.linprog.html)、[SciPy milp](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.milp.html)。核对日期：2026-10-09。模板是本项目增量实现，没有复制外部仓库代码。
