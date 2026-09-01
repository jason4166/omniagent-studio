from pathlib import Path

from PIL import Image, ImageDraw
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas


def build_text_pdf(output_path: Path) -> None:
    pdf = canvas.Canvas(str(output_path), pagesize=letter, invariant=1)
    pdf.drawString(72, 720, "Synthetic Support Guide")
    pdf.drawString(72, 696, "Returns are accepted within 30 days.")
    pdf.showPage()
    pdf.drawString(72, 720, "Warranty requests require an order number.")
    pdf.save()


def build_scanned_pdf(output_path: Path) -> None:
    image = Image.new("RGB", (800, 1000), "white")
    drawing = ImageDraw.Draw(image)
    drawing.text((80, 100), "Synthetic scanned page without a text layer", fill="black")
    pdf = canvas.Canvas(str(output_path), pagesize=letter, invariant=1)
    pdf.drawImage(ImageReader(image), 0, 0, width=612, height=792)
    pdf.save()


def main() -> None:
    output_dir = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "documents"
    output_dir.mkdir(parents=True, exist_ok=True)
    build_text_pdf(output_dir / "synthetic-support-guide.pdf")
    build_scanned_pdf(output_dir / "synthetic-scanned-page.pdf")


if __name__ == "__main__":
    main()
