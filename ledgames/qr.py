"""QR codes as small, scalable SVGs (for phones and printed stickers)."""

import qrcode


def matrix(text: str, border: int = 2) -> list[list[bool]]:
    qr = qrcode.QRCode(border=border, error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(text)
    qr.make(fit=True)
    return qr.get_matrix()


def svg(text: str) -> str:
    return svg_from_matrix(matrix(text))


def svg_from_matrix(matrix: list[list[bool]], x: float = 0, y: float = 0, size: float | None = None) -> str:
    """A full SVG document, or (with size) a <g> to place inside another SVG."""
    n = len(matrix)
    path = "".join(f"M{c},{r}h1v1h-1z" for r, row in enumerate(matrix) for c, dark in enumerate(row) if dark)
    body = f'<rect width="{n}" height="{n}" fill="#fff"/><path d="{path}" fill="#000"/>'
    if size is not None:
        return f'<g transform="translate({x},{y}) scale({size / n})">{body}</g>'
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {n} {n}" '
        f'shape-rendering="crispEdges">{body}</svg>'
    )

