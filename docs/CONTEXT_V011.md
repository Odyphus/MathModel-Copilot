# Task Context v0.1.1：完整权威投影

本次修复对应独立复核报告 B。旧实现检查了源状态哈希与部分对象，却没有重建共同摘要、任务、对象全集、累计变化和下一步动作。修改者可以删掉阻断项、伪造完成度和 `ready`，重新计算普通哈希后仍被接收。

v0.1.1 接收时从对应 revision 的完整权威事实重建 Context，再严格比较所有字段、键集合、数组顺序和 JSON 类型。普通 `context_id` / `common_hash` 仍用于内容一致性检查；它们不是签名，也不再被当作事实真实的充分条件。

## 权威和存储

唯一权威仍是 `state/decision_log.json`，state schema 4.0 / copilot schema 0.1 保持兼容。Store 增加两个自己管理的字段：

- `copilot.context_projection`：本 revision 提交时，由原有 `project_status` 计算的完整派生状态，包含 `version`、`revision`、`observed_at` 和 `status`。复用 Requirement、对象可用性和交付检查，不实现另一套完成度判断。
- `copilot.context_history`：按 revision 保存此前权威状态的完整事实。每条仅省略 `context_history` 本身，另存当时存在的历史 revision 列表。重建时还原这些不可变旧条目，再核对原始 `state_hash` 和 journal 中的 `previous_state_hash`。

快照中的状态没有嵌套历史，当前状态哈希也不包含“当前状态自身的快照”，因此没有自引用或指数递归复制。完整事实和 journal 前缀会占用空间：事务越多，文件越大；本补丁没有引入数据库或历史裁剪。将来若采用压缩或分段存储，应保留同等的原始状态还原与哈希验证，不直接删除已用于 Context 的历史。

业务事务回调不能修改、删除或补写这些字段。Store 在原有锁、CAS 校验、不可变检查与原子提交路径中生成观测和归档；失败事务不写文件。提交时投影器只读取调用者提供的状态和关联文件，不重新读取 Store，不发起嵌套事务。

Windows 上，未共享删除权限的读句柄会暂时阻止原子替换。已有回归中出现一次 `WinError 5`，单独重跑正常，无法据此确定当时的占用者。后续用真实 Win32 句柄复现了同类拒绝：Store 因此只对 Windows 错误 5/32/33 在最长 0.75 秒窗口内重试替换，不重跑业务回调、不移除旧 authority。250 毫秒后释放的句柄可恢复；持续占用仍抛出错误，旧文件字节与 revision 不变，事务临时文件清理。其他错误直接抛出。

## Context 格式与完整比较

Context `schema_version` 与 `projection_version` 为 `0.1.1`。除原有字段外，增加：

- `selection.task`：`current` 表示源 revision 的当前任务，`explicit` 表示指定的真实任务。
- `selection.baseline`：`member_received` 表示该成员在源 revision 的累计接收基线；`origin` 表示从 0 开始；`explicit` 表示调用者明确指定的合法 `since`。
- `file_observation`：明确事实基于源 revision 提交时的文件观测，并提供该次观测时间。

完整比较覆盖角色、成员、源 revision/hash、选择语义、共同摘要、ProblemContract/ModelSpec/ParameterSet/已核验结果、current 指针、任务正文、任务输出和依赖、对象全集与递归依赖、全部对象字段与当时错误、累计 journal 变化、`next_action`。漏字段、加字段、少对象、删变化、修改状态或用整数替换布尔值，均不能只靠重封口通过。

默认 Task 和成员基线按源 revision 解释，之后切换当前任务或成员接收更新版本不会改变旧 Context 的含义。显式角色、Task、基线是允许的视图选择参数：必须在源 revision 合法，并产生完整准确的投影。它们不是账号权限或导出凭证；本地系统验证“这是该参数组合对应的真实权威投影”，不声称证明“某个已认证的人曾在某时导出此文件”。完全重建另一组合法选择参数的真实投影，等价于重新导出，不能因此获得不存在的事实或跳过当下采用检查。

每条 receipt 记录实际 `(changes_since, revision]` 区间、`scope` 和 `received_revision_after`。`received_revision` 只按从 0 开始连续收到的区间推进。合法显式 `since` 可只展示部分历史，但跨过未接收的间隙时记为 `partial_history`，不能冒充累计同步完成。以后接收缺失的前段，可以连接已接收后段并推进游标。将 `selection` 改为合法显式模式、同步删掉 `changes` 并重封口，只能得到真实的部分视图，不能跳过间隙推进累计游标。

## 文件漂移、接收与采用

`build_context` 仍是纯读取。它比较当前文件/校验结果与本 revision 已记录观测；若派生事实发生变化，明确报错并要求显式 `reconcile` 后重新导出。不会为了导出悄悄增加 revision、签发记录或外部 authority。无关的未登记文件不属于 Context；已知失效文件继续保持失效，不承诺保存其每一次无效字节变化。

历史 Context 的事实指向其提交时刻，而非保证今天的文件仍相同。因此：

1. 真实当前 Context 与有完整快照的真实历史 Context 都可以 `received`。
2. 源对象后来失效、文件漂移、任务切换，都不会把真实历史消息变成伪造消息。
3. `adopted` / `verified` 必须先收到该 Context，并重新检查当前权威对象、current 指针、递归依赖、文件哈希和当前校验算法。过期对象仍被拒绝。
4. 接收历史消息不会降低成员已经收到的较高 revision；也不会自动采用、核验对象或提升提交状态。
5. 文件变化发生在导出之后、接收之前时，接收仍只记录源版本事实；该次正式接收事务会记录新的当下观测，采用则按当下情况决定。

提交观测不是操作系统层面的文件快照或防篡改审计。文件可在观察后再次变化，所以采用和其他执行、交付入口仍必须进行各自的实时检查。拥有本机写权限并绕过 Store 同时重写整个 authority 与所有哈希的行为，不在本地普通哈希的认证保证内。

## 升级和投影算法版本

已有 v0.1 项目仍能读取。没有 `context_projection` 的旧 revision 不能在只读导出中补造历史观测，必须先明确执行 `reconcile` 或其他正常授权事务，建立新 revision 后导出 v0.1.1 Context。升级会保留可实际读取到的旧状态快照，但不会虚构升级前未保存的更早状态，也不会把没有观测的旧快照标成完整 Context 事实。旧格式 Context 要重新导出。

v0.1 receipt 没有变化区间，不能证实累计同步；新默认基线从有明确区间的连续覆盖计算，不盲信旧 `received_revision`。旧 receipt 保留，在首次新接收时另存 `legacy_received_revision` 以保留声明。成员收到新的完整历史后恢复推进，无须删除旧协作记录。

历史派生摘要直接取该 revision 保存的版本化结果，不用今天的文件或新算法去改写过去。当前算法若产生不同结论，当前导出要求显式 reconcile；历史接收仍保留旧事实含义，采用始终应用当前校验。未来改变 Context 投影结构/语义时必须分配新的 `projection_version` 并保留相应旧投影器，或明确报告旧版本不支持。未知投影版本不能猜测解释；当前项目可显式 reconcile 升级，历史 Context 需对应版本的投影器。

## 验证范围

`tests/test_context_v011.py` 覆盖复核报告 B 原始重封口路径、33 类当前/历史字段篡改，以及类型/角色/基线/观测字段邻近反例；同时覆盖真实当前和历史接收、历史采用当前有效对象、过期拒绝、角色共同摘要一致、只读导出、文件和校验算法漂移、任务与成员基线切换、快照原始哈希还原、禁止历史改写/删除、旧项目显式升级和未知投影版本升级。

继承的 `test_copilot_context.py`、`test_copilot_store.py` 继续验证接收/采用/核验区分、多人 CAS、真实多进程竞争、幂等、回调失败不写入以及旧状态迁移。最终实跑数量和原始日志位于交付目录的 `verification/context/`；开发中失败日志被保留，不能冒充最终结果。

本模块最终定向运行 39 项方法全部通过：新 Context/历史/文件共享检查 26 项、原 Context 6 项、原 Store 6 项，以及原先偶发失败的 Runtime 单例 1 项。两项 Win32 句柄测试在当前 Windows 主机真实执行；其他平台会明确跳过这两项，不宣称验证 Windows 共享行为。原始日志为 `11-final-context-store-and-windows.txt`。独立 Agent 的 14 项 Context 反例另行复验通过，证据在 `verification/redteam/context-after-owner-freeze/`。

单次本机体积观察：固定对象集下 revision 10/20/40 的状态文件分别为 309,385 / 758,030 / 1,922,620 bytes；快照条目数恰好等于 revision，快照内嵌套 history 数为 0，前一版原始哈希均能还原。对应只读 Context 导出约 0.019 / 0.026 / 0.056 秒。实际旧题 smoke 在 42 个 revision 后状态文件为 5,998,364 bytes，8/8 Requirement 通过，`ready=false`。测量时存在其他 Agent 并发工作，只运行一次，不能作性能保证；旧 v0.1 对照在 Q2 输入快照阶段遇到 `WinError 3`，未产生有效基线，因此不计算新旧耗时比值。完整原记录在 `07-size-and-smoke-observations.json` 与对应日志中。
