"""R60b: o funil por fila só vale para períodos que começam em 30/09/2026 ou depois (a semana de 28/09 misturava os dois regimes e
passava no critério de 30 % de Triagem com 54 % 'chegaram à fila' — todos os tickets de 28–29/09 estavam na fila Televendas).
Idempotente (marker `_FILA_DESDE`)."""
import sys
from _patchlib import read_app, write_app

text, bom, crlf = read_app()
if "_FILA_DESDE" in text:
    print("  = R60b já aplicada"); sys.exit(0)
old = "        _fila_ok = bool(_r58 and tl_ftv is not None and tl and (tl_tri or 0) >= 0.3 * tl)   # fluxo com fila Triagem dominante no período\n"
new = ("        _FILA_DESDE = pd.Timestamp('2026-09-30')   # fila Triagem existe desde 30/09: o funil por fila só vale para períodos que começam depois\n"
       "        try:\n"
       "            _fila_ini_ok = pd.Timestamp(min(_tv_per)) >= _FILA_DESDE\n"
       "        except Exception:\n"
       "            _fila_ini_ok = False\n"
       "        _fila_ok = bool(_r58 and tl_ftv is not None and tl and _fila_ini_ok and (tl_tri or 0) >= 0.3 * tl)   # fluxo com fila Triagem dominante\n")
if text.count(old) != 1:
    print("ERRO: ancora", text.count(old)); sys.exit(1)
text = text.replace(old, new)
write_app(text, bom, crlf)
print("R60b aplicada")
