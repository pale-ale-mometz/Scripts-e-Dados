"""Preview local da aba 🎯 sem digitar senha (só para desenvolvimento, nunca para deploy):
    .venv\\Scripts\\python.exe -m streamlit run diagnostics\\preview_r74.py --server.port 8507 [-- --perfil analista]
Abre o app.py já logado no perfil indicado (padrão gerencial)."""
import pathlib
import runpy
import sys

import streamlit as st

perfil = "gerencial"
if "--perfil" in sys.argv:
    perfil = sys.argv[sys.argv.index("--perfil") + 1]
st.session_state.setdefault("password_correct", True)
st.session_state.setdefault("perfil", perfil)
app = pathlib.Path(__file__).resolve().parents[1] / "app.py"
sys.path.insert(0, str(app.parent))
runpy.run_path(str(app), run_name="__main__")
