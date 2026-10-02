from io import BytesIO

from PIL import Image, ImageDraw


def receipt_image(marker: str = "fixture") -> bytes:
    image = Image.new("RGB", (300, 50), "white")
    ImageDraw.Draw(image).text((5, 10), marker, fill="black")
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()
