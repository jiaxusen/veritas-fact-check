"""屏幕抓取模块。

为前端「手动截图」提供原始画面：服务端直接调用系统接口截全屏，
前端拿到图片后由用户拖拽框选，再把裁剪结果送 OCR。

相比浏览器自带的 getDisplayMedia，这条路子的好处是：
  * 不弹「选择共享内容」的系统弹窗；
  * 不要求 https / localhost 安全上下文，局域网也能用；
  * 不产生常驻的屏幕录制指示器。
代价是抓的永远是**服务端这台机器**的屏幕。
"""
from __future__ import annotations

import base64
import io
import platform

# 超过这个边长就等比缩小，兼顾传输体积与 OCR 精度
_MAX_EDGE = 2560


def supported() -> bool:
    """当前环境是否支持屏幕抓取。"""
    if platform.system() != "Windows":
        return False
    try:
        from PIL import ImageGrab  # noqa: F401
    except Exception:
        return False
    return True


def _shrink(img):
    """等比缩放到 _MAX_EDGE 以内，返回 (图片, 缩放比例)。"""
    from PIL import Image

    w, h = img.size
    edge = max(w, h)
    if edge <= _MAX_EDGE:
        return img, 1.0
    scale = _MAX_EDGE / edge
    try:
        resample = Image.Resampling.LANCZOS  # Pillow >= 9.1
    except AttributeError:  # Pillow < 9.1
        resample = Image.LANCZOS
    new_size = (max(1, round(w * scale)), max(1, round(h * scale)))
    return img.resize(new_size, resample), scale


def capture() -> dict:
    """截取全部屏幕，返回 data URL 与原始尺寸。"""
    if not supported():
        return {
            "ok": False,
            "error": "屏幕抓取仅支持 Windows 服务端，请改用「图片识别」导入截图",
        }
    try:
        from PIL import ImageGrab

        try:
            img = ImageGrab.grab(all_screens=True)
        except TypeError:  # Pillow < 8.3 没有该参数
            img = ImageGrab.grab()
        img = img.convert("RGB")
        img, scale = _shrink(img)

        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        raw = buf.getvalue()
        data_url = "data:image/png;base64," + base64.b64encode(raw).decode("ascii")

        return {
            "ok": True,
            "name": "screen.png",
            "width": img.size[0],
            "height": img.size[1],
            "scale": round(scale, 4),
            "bytes": len(raw),
            "data": data_url,
        }
    except Exception as e:  # 锁屏、远程桌面断开、无交互会话等
        return {"ok": False, "error": f"屏幕抓取失败：{e}"}
