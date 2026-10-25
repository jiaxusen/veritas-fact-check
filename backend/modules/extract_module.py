"""① 输入模块 · 附件提取：图片 OCR / 文档解析。

设计原则：
- 图片走 **Windows 系统 OCR**（WinRT Windows.Media.Ocr），不引入 Tesseract 之类的
  重型引擎，系统自带中文识别包即可用；失败时返回可读的降级提示。
- 文档解析全部使用纯 pip 的轻量库（python-docx / pypdf / openpyxl），
  任一依赖缺失都不影响其它类型，也不影响主流程。
- 提取出的文本最终仍要经过 input_module.validate_text 的长度校验。
"""
from __future__ import annotations
import asyncio
import csv
import io
import os
import re
import tempfile
from pathlib import Path

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"}
TEXT_EXT = {".txt", ".md", ".log", ".csv", ".json", ".xml", ".yml", ".yaml", ".ini"}
HTML_EXT = {".html", ".htm"}
DOCX_EXT = {".docx"}
PDF_EXT = {".pdf"}
SHEET_EXT = {".xlsx", ".xlsm"}
LEGACY_EXT = {".doc", ".xls", ".ppt", ".pptx"}

MAX_IMAGE = 12 * 1024 * 1024
MAX_FILE = 25 * 1024 * 1024
MAX_KEEP = 2000  # 与 input_module.MAX_LEN 保持一致

_OCR_LANGS = ["zh-Hans-CN", "zh-Hans", "zh-CN", "zh-Hant-TW", "en-US"]
_CJK = "\u4e00-\u9fff\u3400-\u4dbf"
_ENC = ("utf-8", "utf-8-sig", "gbk", "gb18030", "big5", "latin-1")


def _tidy(text: str, ocr: bool = False) -> str:
    """整理提取文本：归一化空白、丢弃空行。

    ocr=True 时额外去掉系统 OCR 在中文之间插入的冗余空格——
    Windows OCR 会把每个汉字当作独立「词」并用空格连接，
    数字序列也常被拆开（211 → "21 1"），这里只保留英文单词之间的空格。
    仅对 OCR 结果启用，避免误删 CSV / 表格里真实的分隔空格。
    """
    s = str(text or "").replace("\u3000", " ")
    if ocr:
        s = re.sub(rf"(?<=[{_CJK}]) +(?=[{_CJK}])", "", s)
        s = re.sub(rf"(?<=[{_CJK}]) +(?=[0-9A-Za-z])", "", s)
        s = re.sub(rf"(?<=[0-9A-Za-z]) +(?=[{_CJK}])", "", s)
        s = re.sub(r"(?<=[0-9]) +(?=[0-9])", "", s)
    s = re.sub(r"[ \t]+", " ", s)
    return "\n".join(line.strip() for line in s.splitlines() if line.strip())


def _decode(data: bytes) -> str:
    for enc in _ENC:
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", errors="replace")


def _normalize_image(data: bytes) -> bytes:
    """统一为 PNG，并把尺寸调整到 OCR 友好区间。

    过小（长边 < 900）放大 2 倍以提升识别率；过大（长边 > 3500）等比缩小，
    避免 Windows OCR 解码失败。
    """
    from PIL import Image

    img = Image.open(io.BytesIO(data))
    if img.mode in ("P", "LA"):
        img = img.convert("RGBA")
    elif img.mode not in ("RGB", "RGBA", "L"):
        img = img.convert("RGB")
    w, h = img.size
    longest = max(w, h)
    if longest < 900:
        scale = 2
    elif longest > 3500:
        scale = 3500 / longest
    else:
        scale = 1
    if scale != 1:
        img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _ocr_sync(png_bytes: bytes) -> tuple[str, str]:
    """调用 Windows 系统 OCR，返回 (文本, 引擎描述)。"""
    from winsdk.windows.globalization import Language
    from winsdk.windows.graphics.imaging import BitmapDecoder
    from winsdk.windows.media.ocr import OcrEngine
    from winsdk.windows.storage import FileAccessMode, StorageFile

    async def run() -> tuple[str, str]:
        engine = None
        for tag in _OCR_LANGS:
            try:
                lang = Language(tag)
                if OcrEngine.is_language_supported(lang):
                    engine = OcrEngine.try_create_from_language(lang)
                    if engine:
                        break
            except Exception:  # noqa: BLE001 - 语言包缺失时直接跳过
                continue
        if engine is None:
            engine = OcrEngine.try_create_from_user_profile_languages()
        if engine is None:
            return "", "unavailable"
        fd, path = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        try:
            Path(path).write_bytes(png_bytes)
            storage_file = await StorageFile.get_file_from_path_async(path)
            stream = await storage_file.open_async(FileAccessMode.READ)
            decoder = await BitmapDecoder.create_async(stream)
            bitmap = await decoder.get_software_bitmap_async()
            result = await engine.recognize_async(bitmap)
            # 优先按行拼接：result.text 会丢失换行，lines 能保留原文的段落结构
            lines = [line.text for line in result.lines]
            text = "\n".join(lines) if lines else (result.text or "")
            return text, f"Windows OCR · {engine.recognizer_language.language_tag}"
        finally:
            try:
                os.remove(path)
            except OSError:
                pass

    return asyncio.run(run())


def ocr_bytes(name: str, data: bytes) -> dict:
    """对图片二进制做 OCR。"""
    warnings: list[str] = []
    if len(data) > MAX_IMAGE:
        return {
            "ok": False, "kind": "image", "kind_label": "图片识别",
            "name": name, "size": len(data), "text": "",
            "error": f"图片过大（{len(data) // 1024 // 1024}MB），请控制在 12MB 以内",
        }
    try:
        png = _normalize_image(data)
    except Exception as exc:  # noqa: BLE001 - 图片无法解码时给出可读错误
        return {
            "ok": False, "kind": "image", "kind_label": "图片识别",
            "name": name, "size": len(data), "text": "",
            "error": f"图片无法解析（{exc}），请换一张或改用文字输入",
        }
    try:
        raw, engine = _ocr_sync(png)
    except Exception as exc:  # noqa: BLE001 - 系统 OCR 不可用时降级提示
        return {
            "ok": False, "kind": "image", "kind_label": "图片识别",
            "name": name, "size": len(data), "text": "",
            "error": f"系统 OCR 不可用（{exc}）。请确认 Windows 已安装中文 OCR 语言包，或改用文字输入",
        }
    if engine == "unavailable":
        return {
            "ok": False, "kind": "image", "kind_label": "图片识别",
            "name": name, "size": len(data), "text": "",
            "error": "未找到可用的 OCR 引擎。请在 Windows「设置 → 时间和语言 → 语言」中安装中文语言包",
        }
    text = _tidy(raw, ocr=True)
    if not text:
        return {
            "ok": False, "kind": "image", "kind_label": "图片识别",
            "name": name, "size": len(data), "text": "",
            "error": "未能从图片中识别出文字。请提高截图清晰度，或改用文字输入",
        }
    if len(text) > MAX_KEEP:
        warnings.append(f"识别内容超过 {MAX_KEEP} 字，已自动截取前 {MAX_KEEP} 字")
        text = text[:MAX_KEEP]
    return {
        "ok": True, "kind": "image", "kind_label": "图片识别",
        "name": name, "size": len(data), "text": text,
        "engine": engine, "warnings": warnings,
    }


def _from_docx(data: bytes, warnings: list[str]) -> str:
    try:
        import docx
    except ImportError:
        warnings.append("未安装 python-docx，无法解析 .docx，请改用文字输入")
        return ""
    try:
        doc = docx.Document(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001 - 非 docx / 文件损坏
        warnings.append(f"Word 文档无法解析（{exc}），请另存后再导入")
        return ""
    parts = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                parts.append(" ".join(cells))
    return "\n".join(parts)


def _from_pdf(data: bytes, warnings: list[str]) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        warnings.append("未安装 pypdf，无法解析 .pdf，请改用文字输入")
        return ""
    try:
        # 加密 / 损坏 / 缺 xref 的 PDF 会在这里就抛错，必须一并兜住
        reader = PdfReader(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"PDF 无法解析（{exc}），请直接截图或上传图片查证")
        return ""
    pages = reader.pages[:30]
    parts = []
    for p in pages:
        try:
            t = (p.extract_text() or "").strip()
        except Exception:  # noqa: BLE001
            t = ""
        if t:
            parts.append(t)
    if not parts:
        warnings.append("该 PDF 未提取到文字层（可能是扫描件），请直接截图或上传图片查证")
    elif len(reader.pages) > 30:
        warnings.append(f"PDF 共 {len(reader.pages)} 页，仅提取前 30 页")
    return "\n".join(parts)


def _from_sheet(data: bytes, warnings: list[str]) -> str:
    try:
        from openpyxl import load_workbook
    except ImportError:
        warnings.append("未安装 openpyxl，无法解析 .xlsx，请改用文字输入")
        return ""
    try:
        wb = load_workbook(io.BytesIO(data), data_only=True, read_only=True)
    except Exception as exc:  # noqa: BLE001 - 非 xlsx / 文件损坏
        warnings.append(f"表格文档无法解析（{exc}），请另存后再导入")
        return ""
    parts = []
    for ws in wb.worksheets:
        for row in ws.iter_rows(max_row=500, values_only=True):
            cells = [str(c).strip() for c in row if c is not None and str(c).strip()]
            if cells:
                parts.append(" ".join(cells))
        if len(parts) > 2000:
            break
    return "\n".join(parts)


def _from_html(data: bytes) -> str:
    text = _decode(data)
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return text


def _from_csv(data: bytes) -> str:
    text = _decode(data)
    try:
        rows = list(csv.reader(io.StringIO(text)))
        return "\n".join(" ".join(c.strip() for c in r if c.strip()) for r in rows if any(c.strip() for c in r))
    except csv.Error:
        return text


def extract(name: str, data: bytes) -> dict:
    """按扩展名分派提取器，统一返回结构。"""
    warnings: list[str] = []
    ext = Path(name or "").suffix.lower()
    if not data:
        return {"ok": False, "kind": "unknown", "kind_label": "附件", "name": name, "size": 0, "text": "", "error": "文件内容为空"}

    if ext in IMAGE_EXT:
        return ocr_bytes(name, data)

    if ext in DOCX_EXT:
        if len(data) > MAX_FILE:
            return {"ok": False, "kind": "docx", "kind_label": "Word 文档", "name": name, "size": len(data), "text": "", "error": "文件过大，请控制在 25MB 以内"}
        text = _tidy(_from_docx(data, warnings))
    elif ext in PDF_EXT:
        if len(data) > MAX_FILE:
            return {"ok": False, "kind": "pdf", "kind_label": "PDF 文档", "name": name, "size": len(data), "text": "", "error": "文件过大，请控制在 25MB 以内"}
        text = _tidy(_from_pdf(data, warnings))
    elif ext in SHEET_EXT:
        if len(data) > MAX_FILE:
            return {"ok": False, "kind": "sheet", "kind_label": "表格文档", "name": name, "size": len(data), "text": "", "error": "文件过大，请控制在 25MB 以内"}
        text = _tidy(_from_sheet(data, warnings))
    elif ext in HTML_EXT:
        text = _tidy(_from_html(data))
    elif ext in TEXT_EXT:
        text = _tidy(_from_csv(data) if ext == ".csv" else _decode(data))
    elif ext in LEGACY_EXT:
        return {
            "ok": False, "kind": "legacy", "kind_label": "旧版文档", "name": name, "size": len(data),
            "text": "", "error": f"暂不支持 {ext} 旧格式，请在 Office 中另存为 .docx / .xlsx 后再导入",
        }
    else:
        return {
            "ok": False, "kind": "unknown", "kind_label": "附件", "name": name, "size": len(data),
            "text": "", "error": f"暂不支持 {ext or '未知'} 格式，可导入图片 / TXT / MD / CSV / PDF / DOCX / XLSX",
        }

    if not text:
        return {
            "ok": False, "kind": ext.lstrip(".") or "unknown", "kind_label": "附件",
            "name": name, "size": len(data), "text": "",
            "error": "未能从文件中提取到文字内容" + ("；" + warnings[0] if warnings else ""),
        }
    if len(text) > MAX_KEEP:
        warnings.append(f"内容超过 {MAX_KEEP} 字，已自动截取前 {MAX_KEEP} 字")
        text = text[:MAX_KEEP]
    return {
        "ok": True,
        "kind": ext.lstrip(".") or "text",
        "kind_label": {
            "docx": "Word 文档", "pdf": "PDF 文档", "xlsx": "表格文档", "xlsm": "表格文档",
            "html": "网页文件", "htm": "网页文件", "csv": "表格文本",
        }.get(ext.lstrip("."), "文本文件"),
        "name": name, "size": len(data), "text": text,
        "engine": "本地解析", "warnings": warnings,
    }
