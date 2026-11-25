"""UPI helpers: build the payment link and a QR code for it."""
from decimal import Decimal
from urllib.parse import quote


def upi_uri(vpa, payee, amount, note):
    """upi://pay link understood by GPay, PhonePe, Paytm, BHIM and every bank app."""
    params = {'pa': vpa, 'pn': payee, 'am': f"{Decimal(amount):.2f}", 'cu': 'INR', 'tn': note}
    return "upi://pay?" + "&".join(f"{k}={quote(str(v), safe='@')}" for k, v in params.items())


def qr_svg(data):
    """Inline SVG QR code, or '' if the optional 'segno' package isn't installed."""
    try:
        import segno
    except ImportError:
        return ''
    return segno.make(data, error='m').svg_inline(scale=5, border=2, dark='#101827')
