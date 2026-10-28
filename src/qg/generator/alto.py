# ALTO for a generated page, and the OCR text derived from it.
#
# The layout is composed once (blocks -> lines -> words, with pixel geometry that fits the print
# area) and both ALTO and TEXT_OCR are rendered from it, so the OCR is exactly the ALTO text.
# Every page has ALTO naming its producer (canonical specs).
#
# ALTO is written as text rather than through ElementTree: it is the bulk of the corpus bytes and
# ElementTree serialization dominated generation time. The element set (styles, positioned SP,
# STYLEREFS) mirrors production ALTO so the bytes per word match (~160, calibration/findings.md).

from dataclasses import dataclass
from xml.sax.saxutils import escape, quoteattr

from .sampling import Rng
from .spec import PagesSpec
from .text import ZipfPool
from .tree import Scan

ALTO_NAMESPACES = {
    "v2": "http://www.loc.gov/standards/alto/ns-v2#",
    "v3": "http://www.loc.gov/standards/alto/ns-v3#",
    "v4": "http://www.loc.gov/standards/alto/ns-v4#",
}
_MARGIN = 0.08  # of page width/height
_LINE_PITCH_INCHES = 0.2  # ~5 mm between baselines at body text size
_CHAR_WIDTH = 0.45  # of line pitch
_LINE_HEIGHT = 0.8  # of line pitch


@dataclass(frozen=True)
class Box:
    x: int
    y: int
    width: int
    height: int


@dataclass(frozen=True)
class Word:
    text: str
    box: Box
    confidence: str | None


@dataclass(frozen=True)
class Line:
    words: tuple[Word, ...]
    box: Box


@dataclass(frozen=True)
class Block:
    lines: tuple[Line, ...]
    box: Box


@dataclass(frozen=True)
class PageLayout:
    width: int
    height: int
    print_space: Box
    blocks: tuple[Block, ...]


def compose(
    rng: Rng, pages: PagesSpec, scan: Scan, vocabulary: ZipfPool, *, is_blank: bool
) -> PageLayout:
    """Lay out a page's text. `rng` is the page's own stream; draws within it are sequential."""
    margin_x, margin_y = round(scan.width * _MARGIN), round(scan.height * _MARGIN)
    print_space = Box(margin_x, margin_y, scan.width - 2 * margin_x, scan.height - 2 * margin_y)
    if is_blank:
        return PageLayout(scan.width, scan.height, print_space, ())

    texts = _draw_text(rng, pages, vocabulary)
    total_lines = sum(len(block) for block in texts)
    longest = max(sum(len(w) + 1 for w in line) for block in texts for line in block)
    pitch = min(scan.dpi * _LINE_PITCH_INCHES, print_space.height / (total_lines + len(texts)))
    char_width = min(pitch * _CHAR_WIDTH, print_space.width / longest)
    height = round(pitch * _LINE_HEIGHT)

    blocks = []
    y = float(print_space.y)
    for block_lines in texts:
        block_top = y
        lines = []
        for line_words in block_lines:
            words = []
            x = float(print_space.x)
            for text in line_words:
                width = len(text) * char_width
                confidence = f"{rng.between(0.6, 1.0):.2f}" if scan.has_word_confidence else None
                words.append(Word(text, Box(round(x), round(y), round(width), height), confidence))
                x += width + char_width
            line_width = round(x - char_width - print_space.x)
            lines.append(Line(tuple(words), Box(print_space.x, round(y), line_width, height)))
            y += pitch
        block_width = max(line.box.width for line in lines)
        block_box = Box(print_space.x, round(block_top), block_width, round(y - block_top))
        blocks.append(Block(tuple(lines), block_box))
        y += pitch  # gap between blocks
    return PageLayout(scan.width, scan.height, print_space, tuple(blocks))


def _draw_text(rng: Rng, pages: PagesSpec, vocabulary: ZipfPool) -> list[list[list[str]]]:
    """Blocks of lines of words; the line total is split into blocks of drawn sizes."""
    remaining = max(1, pages.lines.sample(rng))
    blocks: list[list[list[str]]] = []
    while remaining > 0:
        size = min(remaining, max(1, pages.lines_per_block.sample(rng)))
        block = []
        for _ in range(size):
            count = max(1, pages.words_per_line.sample(rng))
            block.append([vocabulary.draw(rng) for _ in range(count)])
        blocks.append(block)
        remaining -= size
    return blocks


def ocr_text(layout: PageLayout) -> str:
    blocks = (
        "\n".join(" ".join(w.text for w in line.words) for line in b.lines) for b in layout.blocks
    )
    return "\n\n".join(blocks) + ("\n" if layout.blocks else "")


def _box(box: Box) -> str:
    return f'HPOS="{box.x}" VPOS="{box.y}" WIDTH="{box.width}" HEIGHT="{box.height}"'


def _software(scan: Scan) -> str:
    producer = scan.producer
    software = (
        f"<processingSoftware><softwareCreator>{escape(producer.creator)}</softwareCreator>"
        f"<softwareName>{escape(producer.name)}</softwareName>"
        f"<softwareVersion>{escape(producer.version)}</softwareVersion></processingSoftware>"
    )
    if scan.alto_version == "v4":
        return f'<Processing ID="OCR_0">{software}</Processing>'
    return (
        f'<OCRProcessing ID="OCR_0"><ocrProcessingStep>{software}</ocrProcessingStep>'
        "</OCRProcessing>"
    )


def alto_xml(layout: PageLayout, scan: Scan, file_name: str) -> bytes:
    parts = [
        "<?xml version='1.0' encoding='utf-8'?>\n",
        f'<alto xmlns="{ALTO_NAMESPACES[scan.alto_version]}">',
        "<Description><MeasurementUnit>pixel</MeasurementUnit>",
        f"<sourceImageInformation><fileName>{escape(file_name)}</fileName>"
        "</sourceImageInformation>",
        _software(scan),
        "</Description>",
        '<Styles><TextStyle ID="TS_0" FONTSIZE="10" FONTFAMILY="Times New Roman"/>'
        '<ParagraphStyle ID="PS_0" ALIGN="Left" LEFT="0" RIGHT="0" FIRSTLINE="0"/></Styles>',
        "<Layout>",
        f'<Page ID="Page1" PHYSICAL_IMG_NR="1" WIDTH="{layout.width}" HEIGHT="{layout.height}">',
        f"<PrintSpace {_box(layout.print_space)}>",
    ]
    for b, block in enumerate(layout.blocks):
        parts.append(f'<TextBlock ID="TB_{b:04d}" {_box(block.box)} STYLEREFS="TS_0 PS_0">')
        for n, line in enumerate(block.lines):
            parts.append(f'<TextLine ID="TL_{b:04d}_{n:03d}" {_box(line.box)}>')
            previous: Word | None = None
            for word in line.words:
                if previous is not None:
                    right = previous.box.x + previous.box.width
                    gap = word.box.x - right
                    parts.append(f'<SP WIDTH="{gap}" VPOS="{word.box.y}" HPOS="{right}"/>')
                confidence = f' WC="{word.confidence}"' if word.confidence is not None else ""
                parts.append(
                    f"<String CONTENT={quoteattr(word.text)} {_box(word.box)}"
                    f' STYLEREFS="TS_0"{confidence}/>'
                )
                previous = word
            parts.append("</TextLine>")
        parts.append("</TextBlock>")
    parts.append("</PrintSpace></Page></Layout></alto>")
    return "".join(parts).encode()
