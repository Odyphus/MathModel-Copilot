"""
extract_diff.py — Section-level patch refinement 工具

功能: 把 L1 critique.issues 转换成"只修订有问题段落"的精修指令,
      缩小修改范围并保留已通过章节；实际节省量取决于 artifact 与 patch.

实现策略 (修复原 unified diff 实现的丢修订 bug):
- 优先模式: section-level patch (按 markdown ## 章节定位 + 全段替换)
- 备选模式: unified diff via unidiff 库 (健壮的 hunk parser)

用法:
    python scripts/extract_diff.py --artifact artifact_v0.md --critique critique_v0.json --mode section
    python scripts/extract_diff.py --artifact a.md --critique c.json --mode diff --apply patch.diff
"""

import json
import argparse
import re
import hashlib
from pathlib import Path


MAX_SECTION_PATCH_CHARS = 20_000


def source_hash(artifact: str) -> str:
    return hashlib.sha256(artifact.encode("utf-8")).hexdigest()


def verify_patch_source(artifact: str, patch: str) -> None:
    hashes = re.findall(r"^MATHMODEL_SOURCE_SHA256:\s*([0-9a-f]{64})\s*$", patch, re.MULTILINE)
    if len(hashes) != 1:
        raise ValueError("补丁必须携带唯一 MATHMODEL_SOURCE_SHA256 源版本哈希；请重新生成补丁")
    if hashes[0] != source_hash(artifact):
        raise ValueError("补丁源版本已过期（source hash 不匹配），拒绝覆盖；请读取最新原文后重新生成")


def load_artifact(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def load_critique(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def split_sections(artifact: str) -> list[tuple[str, int, int]]:
    """
    把 markdown 按 ## / ### 切片, 返回 [(heading, start_line, end_line), ...]
    """
    lines = artifact.splitlines()
    sections = []
    current_heading = "<前言>"
    current_start = 0
    fence_char, fence_length = None, 0
    for i, line in enumerate(lines):
        fence = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if fence_char:
            if fence and fence.group(1)[0] == fence_char and len(fence.group(1)) >= fence_length and not fence.group(2).strip():
                fence_char, fence_length = None, 0
            continue
        if fence and (fence.group(1)[0] == "~" or "`" not in fence.group(2)):
            fence_char, fence_length = fence.group(1)[0], len(fence.group(1))
            continue
        if re.match(r"^ {0,3}#{1,6}\s", line):
            if i > current_start:
                sections.append((current_heading, current_start, i - 1))
            current_heading = line.strip()
            current_start = i
    if current_start < len(lines):
        sections.append((current_heading, current_start, len(lines) - 1))
    return sections


def find_relevant_sections(artifact: str, issue_where: str) -> list[tuple[str, int, int]]:
    """
    根据 issue.where (e.g., '§5.1.2 公式 (5.3)' / '摘要 段 3') 找匹配的 section
    """
    sections = split_sections(artifact)
    tokens = re.findall(r"§?[\d.]+|[一-鿿]{2,}|[A-Za-z]+", issue_where)
    matched = []
    for heading, start, end in sections:
        if any(tok in heading for tok in tokens):
            matched.append((heading, start, end))
    return matched


def build_section_patch_prompt(artifact_path: str, critique: dict) -> str:
    """
    构造 section-level patch 模式精修 prompt
    """
    artifact = load_artifact(artifact_path)
    lines = artifact.splitlines()
    issues = critique.get("issues", [])

    grouped_targets = {}
    unmatched_targets = []
    for i, issue in enumerate(issues):
        where = issue.get("where", "")
        relevant = find_relevant_sections(artifact, where)
        if relevant:
            heading, start, end = relevant[0]
            section_text = "\n".join(lines[start:end + 1])
            if len(section_text) > MAX_SECTION_PATCH_CHARS:
                raise ValueError(
                    f"section {heading!r} 长度 {len(section_text)} 超过 "
                    f"{MAX_SECTION_PATCH_CHARS} 字符；请先增加更细的 Markdown heading，"
                    "或改用 --mode diff。为防止整节覆盖时丢失尾部内容，本工具不会截断。"
                )
            key = (heading, start, end)
            target = grouped_targets.setdefault(key, {
                "section_heading": heading,
                "section_lines": [start + 1, end + 1],
                "section_text": section_text,
                "issues": [],
            })
            target["issues"].append({
                "issue_id": f"issue_{i}",
                "where": where,
                "fix": issue.get("fix", ""),
                "anti_pattern_id": issue.get("anti_pattern_id"),
            })
        else:
            unmatched_targets.append({
                "patch_id": f"unmatched_{i}",
                "issue_id": f"issue_{i}",
                "where": where,
                "fix": issue.get("fix", ""),
                "anti_pattern_id": issue.get("anti_pattern_id"),
                "section_heading": "<未匹配, 全文级修订>",
                "section_text": "",
            })

    targets = []
    for index, target in enumerate(grouped_targets.values()):
        targets.append({"patch_id": f"section_{index}", **target})
    targets.extend(unmatched_targets)

    return f"""# 精修任务 (Section-Level Patch)

artifact 路径: `{artifact_path}` ({len(lines)} 行).

下列每个 issue 对应一个 section (按 markdown ## 章节定位)。请**只重写**列出的 section, 不动其他部分。

## Targets

{json.dumps(targets, ensure_ascii=False, indent=2)}

## Output Format

针对每个已匹配 target, 输出一个完整重写的 section；同一 section 的多个 issue 已合并为一个 target。使用 target 的 `patch_id` 分隔:

```
MATHMODEL_SOURCE_SHA256: {source_hash(artifact)}
<<< SECTION_PATCH section_0
<重写后的整段 markdown, 含原 heading>
>>>
<<< SECTION_PATCH section_1
...
>>>
```

要求:
- 每个 section_patch 必须以原 section 的 heading (e.g., `### 5.1.2 求解算法`) 开头
- `section_text` 是将被整体替换的完整原文，不会截断；必须在保留未涉问题内容的前提下定向修改
- 不要输出 `<前言>` 或 `<未匹配>` 类的 patch；无法精确定位时先补充 heading 或人工处理
- 不要修改未列出的 issue 涉及的 section
"""


def apply_section_patches(artifact: str, patches_text: str) -> str:
    """
    应用 section_patch 输出到 artifact (替代原错误的 zip+replace 实现).

    所有 patch 必须能唯一定位。未知 heading、重复 heading 或同一 heading
    被多个 patch 命中时直接失败，避免看似成功但实际丢修订。
    """
    verify_patch_source(artifact, patches_text)
    matches = []
    patch_id, payload, fence_char, fence_length = None, [], None, 0
    for line in patches_text.splitlines():
        opening = re.fullmatch(r"<<< SECTION_PATCH (\S+)", line.strip())
        if patch_id is None:
            if opening:
                patch_id, payload = opening.group(1), []
            continue
        fence = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if fence_char:
            if fence and fence.group(1)[0] == fence_char and len(fence.group(1)) >= fence_length and not fence.group(2).strip():
                fence_char, fence_length = None, 0
        elif fence and (fence.group(1)[0] == "~" or "`" not in fence.group(2)):
            fence_char, fence_length = fence.group(1)[0], len(fence.group(1))
        elif line.strip() == ">>>":
            matches.append((patch_id, "\n".join(payload)))
            patch_id, payload = None, []
            continue
        elif opening:
            raise ValueError(f"patch {patch_id} 未关闭")
        payload.append(line)
    if patch_id is not None:
        raise ValueError(f"patch {patch_id} 或代码围栏未关闭")
    if not matches:
        raise ValueError("没有找到有效的 SECTION_PATCH 块")

    patch_ids = [match[0] for match in matches]
    duplicate_ids = sorted({patch_id for patch_id in patch_ids if patch_ids.count(patch_id) > 1})
    if duplicate_ids:
        raise ValueError(f"重复的 patch id: {duplicate_ids}")

    lines = artifact.splitlines()
    sections = split_sections(artifact)

    # 同名 heading 不能用标题唯一定位，保留所有 range 以便显式报错。
    heading_to_ranges: dict[str, list[tuple[int, int]]] = {}
    for heading, start, end in sections:
        heading_to_ranges.setdefault(heading, []).append((start, end))

    # 应用补丁: 每个 patch 第一行应该是 heading, 用其定位
    new_lines = list(lines)
    edits = []  # (start, end, replacement_lines)
    targeted_headings = set()
    for issue_id, patch_text in matches:
        patch_lines = patch_text.splitlines()
        if not patch_lines:
            raise ValueError(f"patch {issue_id} 内容为空")
        first_line = patch_lines[0].strip()
        ranges = heading_to_ranges.get(first_line, [])
        if not ranges:
            raise ValueError(f"patch {issue_id} 的 heading 无法定位: {first_line!r}")
        if len(ranges) > 1:
            raise ValueError(
                f"patch {issue_id} 的 heading 在 artifact 中重复, 无法唯一定位: {first_line!r}"
            )
        if first_line in targeted_headings:
            raise ValueError(f"多个 patch 指向同一 heading: {first_line!r}")
        targeted_headings.add(first_line)
        start, end = ranges[0]
        edits.append((start, end, patch_lines))

    # 倒序应用避免行号偏移
    edits.sort(key=lambda x: x[0], reverse=True)
    for start, end, repl in edits:
        new_lines[start:end + 1] = repl

    result = "\n".join(new_lines)
    if artifact.endswith("\n"):
        result += "\n"
    return result


def build_unified_diff_prompt(artifact_path: str, critique: dict) -> str:
    """
    备选: 严格 unified diff 模式 (用 unidiff 库应用, 见 apply_unidiff)
    """
    artifact = load_artifact(artifact_path)
    issues = critique.get("issues", [])
    return f"""# 精修任务 (Unified Diff)

artifact: `{artifact_path}` ({len(artifact.splitlines())} 行).

issues:
{json.dumps(issues, ensure_ascii=False, indent=2)}

输出 git-style unified diff (含 file headers + hunk headers + 至少 3 行 context):

```diff
MATHMODEL_SOURCE_SHA256: {source_hash(artifact)}
--- {artifact_path}
+++ {artifact_path}
@@ -<old_start>,<old_count> +<new_start>,<new_count> @@
 context line
-removed line
+added line
 context line
```

可多个 hunk。**必须**:
1. 行号精确 (从 1 开始, 1-based)
2. context 行至少 3 行 (前后各一组)
3. 文件结尾若改动, 包含 EOF marker
"""


def apply_unidiff(artifact: str, diff_text: str) -> str:
    """
    用 unidiff 解析 patch，并以原 artifact 为唯一基准一次性重建结果。

    每个 context / removed 行都必须与原文逐字匹配；多个 hunk 按原始行号
    递增且不可重叠。这样前一个 hunk 改变行数时不会让后一个 hunk 偏移。
    """
    verify_patch_source(artifact, diff_text)
    try:
        from unidiff import PatchSet
    except ImportError:
        raise ImportError("需 pip install unidiff (见 templates/shared/requirements.txt)")

    try:
        patch = PatchSet.from_string(diff_text)
    except Exception as exc:
        raise ValueError(f"unified diff 无法解析: {exc}") from exc

    patched_files = list(patch)
    if len(patched_files) != 1:
        raise ValueError(f"unified diff 必须且只能修改一个文件，实际 {len(patched_files)}")
    patched_file = patched_files[0]
    if patched_file.is_added_file or patched_file.is_removed_file:
        raise ValueError("仅允许修改现有 artifact，不允许新增或删除文件")

    hunks = list(patched_file)
    if not hunks:
        raise ValueError("unified diff 不包含 hunk")

    original = artifact.splitlines()
    rebuilt = []
    cursor = 0
    for hunk_index, hunk in enumerate(hunks):
        start = max(hunk.source_start - 1, 0)
        if start < cursor:
            raise ValueError(f"hunk {hunk_index} 与前一 hunk 重叠或未按原始行号排序")
        if start > len(original):
            raise ValueError(f"hunk {hunk_index} 起始行超出 artifact")

        rebuilt.extend(original[cursor:start])
        source_cursor = start
        target_count = 0
        for patch_line in hunk:
            value = patch_line.value.rstrip("\r\n")
            if patch_line.is_context or patch_line.is_removed:
                if source_cursor >= len(original) or original[source_cursor] != value:
                    actual = "<EOF>" if source_cursor >= len(original) else original[source_cursor]
                    raise ValueError(
                        f"hunk {hunk_index} 原文校验失败于第 {source_cursor + 1} 行: "
                        f"expected={value!r}, actual={actual!r}"
                    )
                if patch_line.is_context:
                    rebuilt.append(original[source_cursor])
                    target_count += 1
                source_cursor += 1
            elif patch_line.is_added:
                rebuilt.append(value)
                target_count += 1

        consumed = source_cursor - start
        if consumed != hunk.source_length:
            raise ValueError(
                f"hunk {hunk_index} source_length 不一致: "
                f"header={hunk.source_length}, parsed={consumed}"
            )
        if target_count != hunk.target_length:
            raise ValueError(
                f"hunk {hunk_index} target_length 不一致: "
                f"header={hunk.target_length}, parsed={target_count}"
            )
        cursor = source_cursor

    rebuilt.extend(original[cursor:])
    result = "\n".join(rebuilt)
    if artifact.endswith("\n"):
        result += "\n"
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact", type=str, required=True)
    parser.add_argument("--critique", type=str, default=None,
                        help="生成 patch prompt 时必填; --apply 模式不需要")
    parser.add_argument("--mode", choices=["section", "diff"], default="section")
    parser.add_argument("--output", type=str, default=None,
                        help="输出 prompt 到文件 (不指定则 stdout)")
    parser.add_argument("--apply", type=str, default=None,
                        help="若给出, 把该文件 (LLM 返回的 patch/diff) 应用到 artifact, 输出到 stdout")
    args = parser.parse_args()

    if args.apply:
        artifact = load_artifact(args.artifact)
        patch_text = Path(args.apply).read_text(encoding="utf-8")
        try:
            if args.mode == "section":
                new_artifact = apply_section_patches(artifact, patch_text)
            else:
                new_artifact = apply_unidiff(artifact, patch_text)
        except (ImportError, ValueError) as exc:
            parser.exit(1, f"[FAIL] {exc}\n")
        print(new_artifact)
        return 0

    if not args.critique:
        parser.error("生成 patch prompt 时必须提供 --critique")

    critique = load_critique(args.critique)
    try:
        if args.mode == "section":
            prompt = build_section_patch_prompt(args.artifact, critique)
        else:
            prompt = build_unified_diff_prompt(args.artifact, critique)
    except ValueError as exc:
        parser.exit(1, f"[FAIL] {exc}\n")

    if args.output:
        Path(args.output).write_text(prompt, encoding="utf-8")
        print(f"✅ 精修 prompt 已写入 {args.output}")
        print(f"   (token 估算: ~{len(prompt) // 4} tokens)")
    else:
        print(prompt)
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
