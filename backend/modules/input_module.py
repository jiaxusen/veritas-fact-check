"""① 输入模块：接收文本，做长度与空值校验，可选 OCR 识别。"""
from __future__ import annotations
import re
from dataclasses import dataclass
MIN_LEN = 4
MAX_LEN = 2000
class InputError(ValueError):
    """输入校验失败。"""
@dataclass
class ValidatedInput:
    text: str
    length: int
    has_entity: bool
    warnings: list[str]
_ENTITY_HINT = re.compile(r"[\u4e00-\u9fa5]{2,}|[A-Za-z]{2,}|\d+")
def validate_text(raw: str) -> ValidatedInput:
    """校验并归一化用户输入。"""
    if raw is None:
        raise InputError("请输入需要核实的内容")
    text = raw.replace("\u3000", " ").strip()
    text = re.sub(r"\s+", " ", text)
    if not text:
        raise InputError("请输入需要核实的内容")
    if len(text) < MIN_LEN:
        raise InputError(f"内容过短（{len(text)} 字），请补充完整后再查证")
    if len(text) > MAX_LEN:
        raise InputError(f"内容过长（{len(text)} 字），请控制在 {MAX_LEN} 字以内")
    entities = _ENTITY_HINT.findall(text)
    has_entity = len(entities) >= 1
    warnings: list[str] = []
    if not has_entity:
        warnings.append("未识别到有效实体，可能影响检索效果")
    if len(text) < 10:
        warnings.append("文本较短，可核验信息有限")
    return ValidatedInput(text=text, length=len(text), has_entity=has_entity, warnings=warnings)
def ocr_placeholder(image_name: str) -> str:
    """OCR 加分项占位：真实环境接入 OCR 服务后替换。"""
    return f"[OCR] 已接收图片 {image_name}，请在配置 OCR 服务后启用自动识别。"