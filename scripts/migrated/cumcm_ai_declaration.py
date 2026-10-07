"""CUMCM declaration checker, selected only by a competition profile."""
import re
from .workflow_policy import mode_of
AI_DECLARATION_HEADING = "AI 工具使用声明"

AI_USED_DECLARATION_PREFIX = "本参赛队在竞赛过程中使用了AI工具，主要用于"

AI_USED_DECLARATION_SUFFIX = "，详细使用情况见支撑材料。"

AI_UNUSED_DECLARATION = "本参赛队在竞赛过程中未使用任何AI工具。"

def ai_section_positions(text: str) -> tuple[int, int]:
    """Locate standalone paragraph headings, excluding prose mentions."""
    paragraphs = [re.sub(r"\s+", "", line) for line in text.splitlines()]
    return tuple(next((i for i, line in enumerate(paragraphs) if line == title), -1)
                 for title in ("AI工具使用声明", "参考文献"))

def classify_ai_declaration(text: str, *, evaluation_mode: str = "formal_contest") -> tuple[str, str]:
    """Classify the official declaration as used, not_used, missing or conflict."""

    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"[^\S\n]+", "", normalized)
    if re.sub(r"\s+", "", AI_DECLARATION_HEADING) not in normalized:
        return "missing", f"缺少正式标题“{AI_DECLARATION_HEADING}”"
    mode = mode_of({"evaluation_mode": evaluation_mode})
    if mode != "formal_contest":
        start, refs = ai_section_positions(normalized)
        if not 0 <= start < refs:
            return "invalid", "评测披露须位于独立AI声明标题与参考文献标题之间"
        section = "\n".join(normalized.splitlines()[start + 1:refs])
        unused_pattern = r"(?:未|没有)使用(?:任何)?AI工具"
        unused_present = bool(re.search(unused_pattern, section))
        positive = re.sub(unused_pattern, "", section)
        used_present = bool(re.search(r"使用(?:了)?AI工具", positive))
        if unused_present and used_present:
            return "conflict", "历史/研究披露同时声称使用和未使用 AI"
        if used_present:
            return "used", section.strip()
        if unused_present:
            return "not_used", "明确记录未使用 AI 的评测披露"
        return "invalid", "评测披露须明确实际使用或未使用 AI；不能仅有标题"
    used_prefix = AI_USED_DECLARATION_PREFIX
    used_suffix = AI_USED_DECLARATION_SUFFIX
    unused = AI_UNUSED_DECLARATION
    used_match = re.search(
        re.escape(used_prefix) + r"(.+?)" + re.escape(used_suffix), normalized
    )
    unused_present = unused in normalized
    if used_match and unused_present:
        return "conflict", "同时出现“使用AI”和“未使用AI”声明"
    if used_match:
        purpose = used_match.group(1).strip("，,；;。.")
        placeholder_tokens = ("真实用途", "请填写", "待填写", "……", "...", "【", "[填")
        if not purpose or any(token in purpose for token in placeholder_tokens):
            return "invalid", "AI使用目的仍为空或含占位文本"
        return "used", purpose
    if unused_present:
        return "not_used", "采用官方未使用声明"
    return "invalid", "声明未采用 2026 官方二选一句式"
