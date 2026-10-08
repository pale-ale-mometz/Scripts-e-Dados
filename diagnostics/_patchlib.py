"""Utilitário comum dos patches do app.py: lê preservando BOM e o estilo de quebra de linha (CRLF),
normaliza para LF durante as substituições e grava de volta no estilo original."""
import pathlib

APP = pathlib.Path(__file__).resolve().parents[1] / "app.py"


def read_app():
    src = APP.read_bytes()
    bom = b"\xef\xbb\xbf" if src.startswith(b"\xef\xbb\xbf") else b""
    text = src[len(bom):].decode("utf-8")
    crlf = "\r\n" in text
    return text.replace("\r\n", "\n"), bom, crlf


def write_app(text, bom, crlf):
    if crlf:
        text = text.replace("\r\n", "\n").replace("\n", "\r\n")
    APP.write_bytes(bom + text.encode("utf-8"))
