"""Prepare optional manual demo uploads. No attachment is injected into applications."""

import json, shutil, os
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from .space import Space, ROOT
from .. import DATA


def prepare():
    space = Space()
    dest = ROOT / "materials"
    dest.mkdir(exist_ok=True)
    shutil.copyfile(DATA / "media/C0001/M02.jpg", dest / "product.jpg")
    with space.business() as c:
        o = dict(
            c.execute("SELECT * FROM orders WHERE order_id='QH1022001'").fetchone()
        )
        i = dict(
            c.execute(
                "SELECT * FROM order_items WHERE item_id='QH1022001-1'"
            ).fetchone()
        )
    image = Image.new("RGB", (850, 1040), "#fffef7")
    draw = ImageDraw.Draw(image)
    candidates = [os.getenv("DEMO_FONT_PATH", ""), "/System/Library/Fonts/STHeiti Light.ttc", "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"]
    font = next((f for f in candidates if f and Path(f).is_file()), None)
    if not font:
        raise RuntimeError("Install a CJK font or set DEMO_FONT_PATH to a Chinese TrueType/OpenType font")

    def text(y, value, size=31):
        draw.text((65, y), value, fill="#223a2c", font=ImageFont.truetype(font, size))

    text(55, "青禾鲜选 · 邻里店", 44)
    text(130, "演示小票 / 完全虚拟交易", 34)
    text(210, "仅用于面试演示，无真实资金流转", 25)
    draw.line((65, 275, 785, 275), fill="#687c69", width=2)
    for y, t in [
        (320, "订单：" + o["order_id"]),
        (385, "购买时间：2026-10-22 17:30"),
        (450, "支付方式：微信（模拟）"),
        (540, "商品：泰国金枕榴莲"),
        (605, "规格：整果称重"),
        (670, "数量：2784 克"),
        (735, "实付：194.90 元"),
        (800, "优惠：0.00 元"),
        (910, "本票据与模拟收银业务记录对应"),
    ]:
        text(y, t)
    image.save(dest / "receipt.png")
    (dest / "provenance.json").write_text(
        json.dumps(
            {
                "product_source": "code-generated public placeholder; not a real product photo or visual evidence",
                "receipt_source": "synthetic demo POS QH1022001",
                "auto_injected": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print("Demo prepared:", space.path.name)
    print("Optional upload files:", dest)


if __name__ == "__main__":
    prepare()
