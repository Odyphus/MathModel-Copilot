> Copilot v0.1：状态更新、完成判据和交付状态按 [统一执行协议](copilot_runtime.md) 执行；本文 Stage / Critic 字段示例不是直接改写权威 JSON 的接口。

# 数学模型目录 (model_catalog)

> 常用数学建模方法的候选目录，按问题类型组织。它用于扩大候选集，不根据题目关键词自动选型。每个候选仍需检查输出形式、数据条件、假设、约束、计算预算和验证方法。

---

## 0. 问题类型 → 候选模型族（stage 3 生成候选时参考）

| 题目特征 | 可检查的候选模型族 |
|---------|----------|
| "求最优..." / "如何分配..." / "在约束下使...最大" | **优化类** (LP/IP/NLP/启发式) |
| "预测..." / "未来..." / "时间序列" | **预测类** (回归/ARIMA/灰色/LSTM) |
| "评价..." / "排名..." / "综合得分" | **评价类** (AHP/TOPSIS/熵权/模糊) |
| "判断..." / "归类..." / "识别..." | **分类类** (Logistic/SVM/决策树/NN) |
| "模拟..." / "如果...会怎样" / "随机..." | **仿真类** (蒙特卡罗/系统动力学/ABM) |
| "网络中..." / "路径..." / "流量..." | **图论类** (最短路/最大流/最小生成树) |
| "概率..." / "分布..." / "假设检验" | **统计类** (描述统计/检验/方差分析) |
| "动态..." / "随时间..." | **动力系统类** (ODE/PDE/差分方程) |

---

## 1. 优化类 (Optimization)

### 1.1 线性规划 LP
- **适用**: 目标 + 约束都线性
- **Python**: `scipy.optimize.linprog`, `cvxpy`, `pulp`
- **变体名**: "考虑动态权重的多目标线性规划", "鲁棒线性规划"
- **示例场景**: 调度、配送、资源分配；是否适用取决于线性关系与约束表达

### 1.2 整数规划 IP / 0-1 规划
- **适用**: 决策变量取整数 / 0-1
- **Python**: `cvxpy + GUROBI/CBC`, `pulp`
- **变体名**: "基于分支定界的混合整数规划", "Lagrangian 松弛 IP"
- **示例场景**: 选址、路径、组合；需核对整数变量规模与可用求解器

### 1.3 非线性规划 NLP
- **适用**: 目标或约束含非线性
- **Python**: `scipy.optimize.minimize` (SLSQP, trust-constr), `cvxpy` (DCP)
- **变体名**: "凸近似 NLP", "二阶锥规划 SOCP"

### 1.4 多目标规划
- **适用**: 多个相互冲突目标
- **方法**: 加权法 / ε-约束法 / NSGA-II
- **Python**: `pymoo`, `deap`
- **变体名**: "基于熵权的多目标规划", "Pareto-NSGA-II"
- **选型提醒**: 目标之间需存在真实权衡，并说明权重或 Pareto 方案的决策依据

### 1.5 动态规划 DP
- **适用**: 阶段决策、最优子结构
- **Python**: 自实现 (numpy + memoization)
- **变体名**: "状态压缩动态规划", "近似动态规划 ADP"

### 1.6 启发式算法
- **遗传算法 GA**: `deap`, `pygad` — "自适应交叉率 GA"
- **粒子群 PSO**: `pyswarms` — "改进惯性权重 PSO"
- **模拟退火 SA**: 自实现 — "自适应温度 SA"
- **蚁群 ACO**: 自实现 — "信息素改进 ACO"
- **示例场景**: 大规模组合优化、多峰目标；需报告停止条件、随机种子和与可解释基线的比较

### 1.7 鲁棒优化 / 随机规划
- **适用**: 参数不确定
- **Python**: `cvxpy` (robust constraints), `Pyomo`
- **变体名**: "基于场景的随机规划", "Wasserstein 鲁棒优化"
- **选型提醒**: 只有不确定性集合、概率或场景来源有依据时，才使用鲁棒优化或随机规划

---

## 2. 预测类 (Prediction)

### 2.1 回归
- 线性: `sklearn.linear_model.LinearRegression`
- 多项式: `PolynomialFeatures + LinearRegression`
- 岭回归 / Lasso: `Ridge`, `Lasso`
- **变体名**: "弹性网回归", "贝叶斯线性回归"

### 2.2 时间序列经典
- ARIMA: `statsmodels.tsa.arima.model.ARIMA`
- SARIMA: 季节性 ARIMA
- 指数平滑 (Holt-Winters): `statsmodels.tsa.holtwinters`
- **变体名**: "差分整合移动平均自回归模型 (ARIMA)", "Holt-Winters 三参数指数平滑"

### 2.3 灰色预测
- GM(1,1): 自实现；可作为小样本、近指数趋势数据的候选，需先检验适用条件并做留出验证
- **变体名**: "残差修正 GM(1,1)", "GM(1,N) 多变量灰色模型"
- **验证提醒**: 用滚动或留出验证与合适基线比较，不因组合方法名称而默认更优

### 2.4 机器学习预测
- 随机森林: `sklearn.ensemble.RandomForestRegressor`
- XGBoost: `xgboost`
- LSTM: `tensorflow.keras` / `torch`
- **变体名**: "改进 LSTM-Attention 时序预测", "XGBoost-LightGBM Stacking"

### 2.5 组合预测
- **核心思想**: 多模型加权 (权重由误差倒数 / 熵权 / AHP 给出)
- **变体名**: "基于熵权的 ARIMA-LSTM 组合预测"
- **选型提醒**: 组合模型只在子模型误差具有互补性且留出集结果支持时采用，并报告权重与消融结果

---

## 3. 评价类 (Evaluation)

### 3.1 层次分析 AHP
- **核心**: 主观赋权,构造判断矩阵
- **Python**: 自实现 (numpy: 几何平均 + 一致性检验)
- **变体名**: "群决策 AHP", "动态权重 AHP"
- **选型提醒**: AHP 适合有明确层级与可解释判断来源的场景；主观判断矩阵需做一致性和敏感性检查，不要求与其他方法拼接

### 3.2 熵权法
- **核心**: 客观赋权,基于指标方差
- **Python**: 自实现 (numpy)
- **变体名**: "改进熵权法 (考虑指标相关性)"

### 3.3 TOPSIS
- **核心**: 与正负理想解的距离
- **Python**: 自实现
- **变体名**: "灰色关联 TOPSIS", "熵权 TOPSIS"
- **组合提醒**: 若与 AHP 或熵权组合，需解释各权重来源、冲突处理和组合相对单一方法的实际作用

### 3.4 模糊综合评价
- **适用**: 评价对象边界模糊
- **Python**: 自实现 (隶属函数 + 模糊矩阵)
- **变体名**: "二级模糊综合评价"

### 3.5 主成分分析 PCA
- **Python**: `sklearn.decomposition.PCA`
- **作用**: 降维 / 因子提取
- **变体名**: "鲁棒 PCA", "稀疏 PCA"

### 3.6 因子分析 / 聚类评价
- **Python**: `sklearn.cluster.KMeans`, `factor_analyzer`
- **变体名**: "基于 K-Means++ 的聚类评价"

---

## 4. 分类类 (Classification)

### 4.1 Logistic 回归
- **Python**: `sklearn.linear_model.LogisticRegression`
- **变体名**: "L1 正则化 Logistic", "多项 Logit"

### 4.2 支持向量机 SVM
- **Python**: `sklearn.svm.SVC`
- **变体名**: "RBF 核 SVM", "多分类 OVR-SVM"

### 4.3 决策树 / 随机森林 / GBDT
- **Python**: `sklearn.tree`, `sklearn.ensemble`, `xgboost`, `lightgbm`
- **变体名**: "代价敏感随机森林"

### 4.4 神经网络
- **Python**: `tensorflow.keras`, `torch`
- **变体名**: "ResNet 改进结构", "BP-Adam 反向传播"

### 4.5 朴素贝叶斯 / KNN
- **Python**: `sklearn.naive_bayes`, `sklearn.neighbors`
- 简单但 sanity check 用得上

---

## 5. 仿真类 (Simulation)

### 5.1 蒙特卡罗 MC
- **核心**: 大量随机采样估计
- **Python**: `numpy.random` + `scipy.stats`
- **变体名**: "拉丁超立方蒙特卡罗", "马尔可夫链 MCMC"
- **选型提醒**: 可用于不确定性传播或仿真估计；采样分布、样本量和收敛诊断需要依据

### 5.2 系统动力学 SD
- **适用**: 反馈、库存、流速
- **Python**: 自实现 (ODE) 或 Vensim
- **变体名**: "因果回路图 + 库存流图 SD 模型"

### 5.3 元胞自动机 CA
- **适用**: 空间扩散、交通流
- **Python**: 自实现 (numpy 数组迭代)
- **变体名**: "Nagel-Schreckenberg 交通流 CA"

### 5.4 Agent-Based Modeling ABM
- **Python**: `mesa`
- **变体名**: "基于学习智能体的 ABM"

### 5.5 离散事件仿真 DES
- **Python**: `simpy`
- **变体名**: "基于排队论的 DES"

---

## 6. 图论类 (Graph)

### 6.1 最短路
- Dijkstra / Floyd / A*
- **Python**: `networkx.shortest_path`

### 6.2 最大流 / 最小费用流
- **Python**: `networkx.maximum_flow`, `networkx.min_cost_flow`

### 6.3 最小生成树 MST
- Kruskal / Prim
- **Python**: `networkx.minimum_spanning_tree`

### 6.4 网络中心性 / 社团检测
- PageRank / Betweenness
- **Python**: `networkx.pagerank`, `community-louvain`

### 6.5 旅行商 TSP / VRP
- **Python**: `networkx.approximation.traveling_salesman`, `OR-Tools`
- **变体名**: "考虑时间窗的 VRPTW", "蚁群 VRP"

---

## 7. 统计类 (Statistics)

### 7.1 描述性统计
- 均值、方差、偏度、峰度、相关性
- **Python**: `pandas.describe`, `scipy.stats`

### 7.2 假设检验
- t 检验 / χ² / F 检验 / 秩和
- **Python**: `scipy.stats.ttest_*`, `chisquare`

### 7.3 方差分析 ANOVA
- 单因素 / 双因素 / 协方差
- **Python**: `scipy.stats.f_oneway`, `statsmodels.stats.anova`

### 7.4 相关与回归
- Pearson / Spearman / Kendall
- **Python**: `scipy.stats.pearsonr`

### 7.5 分布拟合
- 用 KS 检验拟合优度
- **Python**: `scipy.stats.kstest`, `fitter`

---

## 8. 动力系统类

### 8.1 常微分方程 ODE
- **Python**: `scipy.integrate.solve_ivp`
- 经典: SIR/SEIR (传染病)、Lotka-Volterra (生态)
- **变体名**: "改进 SEIR 含潜伏期与隔离", "随机 SDE"

### 8.2 偏微分方程 PDE
- **Python**: `fipy`, `fenics`, 自实现有限差分
- **选型提醒**: 热扩散、流体等机理问题可能需要 PDE；应先确认边界条件、离散误差和计算资源

### 8.3 差分方程
- 自实现迭代

---

## 9. 信号处理 / 时频分析

### 9.1 傅里叶变换 FFT
- **Python**: `numpy.fft`, `scipy.fft`

### 9.2 小波分析
- **Python**: `pywt`

---

## 10. 决策类

### 10.1 博弈论
- 纳什均衡: `nashpy`
- 多人合作博弈
- **变体名**: "Stackelberg 博弈"

### 10.2 决策树 (决策分析,非 ML)
- 期望效用 / 风险敏感

### 10.3 马尔可夫决策过程 MDP
- **Python**: `mdptoolbox`
- 强化学习: `stable-baselines3`

---

## 模型组合候选（仅在机制互补且验证支持时使用）

下面的组合不是加分公式。每个连接号都意味着额外假设、接口和验证成本；如果单一模型已能回答题目，应优先保留更简单、可解释的方案。

```
评价类: AHP + 熵权 + TOPSIS = "AHP-熵权-TOPSIS 综合评价"
预测类: ARIMA + 灰色 + LSTM = "ARIMA-GM-LSTM 组合预测"
优化类: 启发式 + 鲁棒 = "鲁棒-NSGA-II 多目标优化"
分类类: Stacking 集成 = "RF-XGBoost-LightGBM Stacking 分类"
仿真类: 蒙特卡罗 + 灵敏度 = "LHS-蒙特卡罗稳健性仿真"
```

---

## stage 3 选型 checklist

对进入决策矩阵的候选记录:
- [ ] 来自哪个族 (1-10)
- [ ] 与题目输出、数据、约束和评价指标的对应关系
- [ ] 关键假设及其证据或可检验方式
- [ ] Python 实现路径 (库/自实现)
- [ ] 规模、复杂度、求解器与比赛时间预算
- [ ] 验证计划、基线和失败条件
- [ ] 不选候选及不选理由

候选数量和差异程度由实际决策不确定性决定。存在方法权衡时，应比较假设或求解机制不同的候选；没有合理替代方案时，不为凑数引入不适用模型。

---

## §11 历年类比的使用边界

仓库曾收集 91 份来源文档，但当前不随仓库分发 PDF；分位统计只来自 59 份可提取文本，且以 2023 年样本为主、另含 1 份 2025 年文本，没有可用于统计的 2024 年文本。因而不能从这批材料推出“某年份某题应使用某模型”的稳定映射。

使用历年题时应遵循以下证据链:

1. 先读取当届题面，写明输出、数据、约束和评价指标。
2. 若引用历年题作类比，保存可访问来源并指出相同与不同条件。
3. 从本目录生成候选族后，用当前数据做最小可运行验证和基线比较。
4. 只有模型机制、输入条件和验证结果都支持时，才保留该类比；题目动词相似本身不是选型证据。
