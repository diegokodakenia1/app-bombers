import streamlit as st
import pandas as pd
import datetime
import os
import json
import time
import re
import unicodedata
import io
from google import genai
from google.genai.errors import APIError
from supabase import create_client
import pypdf

# Configuración inicial de la página (DEBE SER LO PRIMERO)
st.set_page_config(
    page_title="Gestor Integral Bombers & Fitness",
    page_icon="🚒",
    layout="wide"
)
# ==============================================================================
# CONFIGURACIÓN DE SUPABASE Y RUTINAS POR DEFECTO
# ==============================================================================
RUTINAS_POR_DEFECTO = {}

# Lectura directa y estricta de secretos (sin respaldos falsos)
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]

@st.cache_resource
def init_supabase():
    try:
        return create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        st.error(f"Error en connectar amb Supabase: {e}")
        return None

supabase = init_supabase()

# Asegurarnos de que las rutinas NUNCA empiecen vacías
if "mis_rutinas" not in st.session_state:
    st.session_state.mis_rutinas = RUTINAS_POR_DEFECTO.copy()

# Cargar tu historial de marcas del gimnasio desde Supabase
if "historial_marcas" not in st.session_state:
    try:
        res_m = supabase.storage.from_("temarios").download("datos/historial_marcas.json")
        st.session_state.historial_marcas = json.loads(res_m.decode("utf-8"))
    except:
        st.session_state.historial_marcas = []

def guardar_marcas_nube():
    try:
        json_bytes = json.dumps(st.session_state.historial_marcas, ensure_ascii=False).encode("utf-8")
        try:
            supabase.storage.from_("temarios").remove(["datos/historial_marcas.json"])
        except:
            pass
        supabase.storage.from_("temarios").upload(
            path="datos/historial_marcas.json",
            file=json_bytes,
            file_options={"content-type": "application/json"}
        )
    except Exception as e:
        st.error(f"Error en desar les marques al núvol: {e}")

# Cargar historial de carreras desde Supabase al iniciar
if "historial_carreras" not in st.session_state:
    try:
        res_hc = supabase.storage.from_("temarios").download("datos/historial_carreras.json")
        st.session_state.historial_carreras = json.loads(res_hc.decode("utf-8"))
    except:
        st.session_state.historial_carreras = []

def guardar_carreras_nube():
    try:
        json_bytes = json.dumps(st.session_state.historial_carreras, ensure_ascii=False).encode("utf-8")
        try:
            supabase.storage.from_("temarios").remove(["datos/historial_carreras.json"])
        except:
            pass
        supabase.storage.from_("temarios").upload(
            path="datos/historial_carreras.json",
            file=json_bytes,
            file_options={"content-type": "application/json"}
        )
    except Exception as e:
        st.error(f"Error en desar l'historial de curses al núvol: {e}")

# Cargar y extraer automáticamente los PDFs del temario desde Supabase al iniciar
if "textos_pdfs_temario" not in st.session_state:
    st.session_state.textos_pdfs_temario = {}
    try:
        archivos_nube = supabase.storage.from_("temarios").list()
        
        if archivos_nube:
            for archivo in archivos_nube:
                nombre_archivo = archivo.get("name") if isinstance(archivo, dict) else getattr(archivo, "name", None)
                
                if nombre_archivo and nombre_archivo.endswith(".pdf"):
                    pdf_bytes = supabase.storage.from_("temarios").download(nombre_archivo)
                    lector = pypdf.PdfReader(io.BytesIO(pdf_bytes))
                    texto_completo = ""
                    for pagina in lector.pages:
                        texto_extraido = pagina.extract_text()
                        if texto_extraido:
                            texto_completo += texto_extraido + "\n"
                    st.session_state.textos_pdfs_temario[nombre_archivo] = texto_completo
    except Exception as e:
        st.error(f"Error en connectar amb el bucket per als PDF: {e}")

# Carga de la API Key de Gemini
api_key = None
try:
    if "GEMINI_API_KEY" in st.secrets:
        api_key = st.secrets["GEMINI_API_KEY"]
except Exception:
    pass

if not api_key:
    api_key = os.environ.get("GEMINI_API_KEY")

if not api_key:
    st.sidebar.warning("⚠️ No s'ha trobat la clau API de Gemini al sistema.")
    api_key_input = st.sidebar.text_input("Introdueix la teva clau API de Gemini:", type="password")
    if api_key_input:
        api_key = api_key_input

client = genai.Client(api_key=api_key) if api_key else None
MODELO_IA = "gemini-3.8-flash"

# Archivos locales de respaldo
CSV_SIMULACROS = "historial_simulacros.csv"
CSV_TEST_TEMAS = "historial_test_temas.csv"
CSV_FALLOS_REPASO = "banco_fallos_repaso.csv"
CSV_FLASHCARDS = "flashcards_guardadas.csv"

LISTA_EJERCICIOS_HEAVY = [
    "Press de banca plano con barra", "Press de banca plano con mancuernas",
    "Press de banca inclinado con barra", "Press de banca inclinado con mancuernas",
    "Dominadas pronas lastradas", "Dominadas libres (Pull-ups)", "Dominadas supinas (Chin-ups)",
    "Press militar con barra de pie (Standing Overhead Press)", "Elevaciones laterales con mancuernas",
    "Curl de bíceps con barra recta", "Press francés con barra Z en banco plano (Skull Crushers)",
    "Sentadilla trasera con barra (Back Squat)", "Prensa de piernas inclinada 45º",
    "Peso muerto convencional con barra", "Peso muerto rumano (Romanian Deadlift con barra o mancuernas)",
    "Elevación de talones de pie en máquina (Standing Calf Raise)", "Plancha abdominal isométrica"
]

def generar_con_reintento(prompt_texto, intentos=6, espera=5):
    if client is None:
        return None
    global MODELO_IA
    for intento in range(intentos):
        try:
            resp = client.models.generate_content(model=MODELO_IA, contents=prompt_texto)
            return resp
        except Exception as e:
            str_e = str(e)
            if ("503" in str_e or "UNAVAILABLE" in str_e or "RESOURCE_EXHAUSTED" in str_e) and intento < intentos - 1:
                time.sleep(espera)
                continue
            st.error(f"Detall exacte de l'error de Google: {e}")
            return None
    return None

def sincronizar_desde_supabase():
    if not supabase:
        return
    try:
        res_bytes = supabase.storage.from_("temarios").download("datos/mis_rutinas.json")
        if res_bytes:
            rutinas_nube = json.loads(res_bytes.decode("utf-8"))
            if isinstance(rutinas_nube, dict) and rutinas_nube:
                st.session_state.mis_rutinas.update(rutinas_nube)
    except Exception:
        pass

def guardar_rutinas_nube():
    if supabase and "mis_rutinas" in st.session_state:
        try:
            json_bytes = json.dumps(st.session_state.mis_rutinas).encode("utf-8")
            supabase.storage.from_("temarios").upload(
                path="datos/mis_rutinas.json",
                file=json_bytes,
                file_options={"content-type": "application/json", "upsert": "true"}
            )
        except Exception:
            try:
                json_bytes = json.dumps(st.session_state.mis_rutinas).encode("utf-8")
                supabase.storage.from_("temarios").update(
                    path="datos/mis_rutinas.json",
                    file=json_bytes,
                    file_options={"content-type": "application/json"}
                )
            except Exception:
                pass

def inicializar_estados():
    if supabase:
        try:
            res_bytes = supabase.storage.from_("temarios").download("datos/plan_estudio.json")
            if res_bytes:
                datos_nube = json.loads(res_bytes.decode("utf-8"))
                if "plan_estudio_json" not in st.session_state:
                    st.session_state.plan_estudio_json = datos_nube.get("plan_json", [])
                if "progreso_estudio" not in st.session_state:
                    st.session_state.progreso_estudio = datos_nube.get("progreso", {})
                    
                for k, v in st.session_state.progreso_estudio.items():
                    st.session_state[k] = v
        except Exception:
            pass

    sincronizar_desde_supabase()
    
    if "mis_rutinas" not in st.session_state:
        if supabase:
            try:
                res_rutinas = supabase.storage.from_("temarios").download("datos/mis_rutinas.json")
                if res_rutinas:
                    st.session_state.mis_rutinas = json.loads(res_rutinas.decode("utf-8"))
                else:
                    st.session_state.mis_rutinas = {}
            except Exception:
                st.session_state.mis_rutinas = {}
        else:
            st.session_state.mis_rutinas = {}

    if "historico" not in st.session_state:
        st.session_state.historico = pd.read_csv(CSV_SIMULACROS).to_dict("records") if os.path.exists(CSV_SIMULACROS) else []
    if "historico_test_temas" not in st.session_state:
        st.session_state.historico_test_temas = pd.read_csv(CSV_TEST_TEMAS).to_dict("records") if os.path.exists(CSV_TEST_TEMAS) else []
    if "banco_fallos" not in st.session_state:
        st.session_state.banco_fallos = pd.read_csv(CSV_FALLOS_REPASO).to_dict("records") if os.path.exists(CSV_FALLOS_REPASO) else []
    if "flashcards" not in st.session_state:
        st.session_state.flashcards = pd.read_csv(CSV_FLASHCARDS).to_dict("records") if os.path.exists(CSV_FLASHCARDS) else []
    if "historial_marcas" not in st.session_state:
        st.session_state.historial_marcas = []

inicializar_estados()

if st.sidebar.button("🔄 Sincronitzar amb el Núvol"):
    if "mis_rutinas" in st.session_state:
        del st.session_state.mis_rutinas
    sincronizar_desde_supabase()
    st.rerun()

def guardar_simulacros_disco():
    if st.session_state.historico:
        df = pd.DataFrame(st.session_state.historico)
        df.to_csv(CSV_SIMULACROS, index=False)
        if supabase:
            try:
                json_bytes = df.to_json(orient="records").encode("utf-8")
                supabase.storage.from_("temarios").upload(
                    path="datos/historico_simulacros.json", file=json_bytes,
                    file_options={"content-type": "application/json", "upsert": "true"}
                )
            except Exception:
                pass

def guardar_test_temas_disco():
    if st.session_state.historico_test_temas:
        df = pd.DataFrame(st.session_state.historico_test_temas)
        df.to_csv(CSV_TEST_TEMAS, index=False)
        if supabase:
            try:
                json_bytes = df.to_json(orient="records").encode("utf-8")
                supabase.storage.from_("temarios").upload(
                    path="datos/historico_test_temas.json", file=json_bytes,
                    file_options={"content-type": "application/json", "upsert": "true"}
                )
            except Exception:
                pass

def guardar_banco_fallos_disco():
    if st.session_state.banco_fallos:
        df = pd.DataFrame(st.session_state.banco_fallos)
        df.to_csv(CSV_FALLOS_REPASO, index=False)
        if supabase:
            try:
                json_bytes = df.to_json(orient="records").encode("utf-8")
                supabase.storage.from_("temarios").upload(
                    path="datos/banco_fallos.json", file=json_bytes,
                    file_options={"content-type": "application/json", "upsert": "true"}
                )
            except Exception:
                pass

def guardar_plan_nube():
    if supabase:
        try:
            datos_plan = {
                "plan_json": st.session_state.get("plan_estudio_json", []),
                "progreso": st.session_state.get("progreso_estudio", {})
            }
            json_bytes = json.dumps(datos_plan).encode("utf-8")
            supabase.storage.from_("temarios").upload(
                path="datos/plan_estudio.json", 
                file=json_bytes,
                file_options={"content-type": "application/json", "upsert": "true"}
            )
        except Exception:
            try:
                json_bytes = json.dumps(datos_plan).encode("utf-8")
                supabase.storage.from_("temarios").update(
                    path="datos/plan_estudio.json", 
                    file=json_bytes,
                    file_options={"content-type": "application/json"}
                )
            except Exception as e:
                st.error(f"Error en desar al núvol: {e}")

def guardar_flashcards_disco():
    if st.session_state.flashcards:
        df = pd.DataFrame(st.session_state.flashcards)
        df.to_csv(CSV_FLASHCARDS, index=False)
        if supabase:
            try:
                json_bytes = df.to_json(orient="records").encode("utf-8")
                supabase.storage.from_("temarios").upload(
                    path="datos/flashcards.json", file=json_bytes,
                    file_options={"content-type": "application/json", "upsert": "true"}
                )
            except Exception:
                pass

# ------------------------------------------------------------------------------
# PARSER Y RENDERIZADOR DE TEST INTERACTIVO
# ------------------------------------------------------------------------------
def parsear_test_a_objetos(texto_ia):
    preguntas_limpias = []
    bloques = re.split(r'\n\s*(?=Pregunta\s*\d+|\d+[\.\-\)]\s)', texto_ia, flags=re.IGNORECASE)
    for bloque in bloques:
        if not bloque.strip(): continue
        lineas = [l.strip() for l in bloque.split('\n') if l.strip()]
        if not lineas: continue
        enunciado = lineas[0]
        opciones, correcta_idx, explicacion = [], 0, ""
        for linea in lineas[1:]:
            match_op = re.match(r'^([A-D])[\.\-\)]\s*(.*)', linea, re.IGNORECASE)
            if match_op: opciones.append((match_op.group(1).upper(), match_op.group(2)))
            if re.search(r'correcta\s*[:\-]?\s*([A-D])', linea, re.IGNORECASE):
                m_corr = re.search(r'correcta\s*[:\-]?\s*([A-D])', linea, re.IGNORECASE)
                letra_corr = m_corr.group(1).upper()
                for i, (l_op, _) in enumerate(opciones):
                    if l_op == letra_corr: correcta_idx = i
            if "explicación" in linea.lower() or "justificación" in linea.lower():
                explicacion = linea
        if len(opciones) >= 2:
            preguntas_limpias.append({
                "enunciado": enunciado,
                "opciones": [op[1] for op in opciones],
                "letras": [op[0] for op in opciones],
                "correcta": correcta_idx,
                "explicacion": explicacion if explicacion else "Resposta oficial validada."
            })
    return preguntas_limpias

def renderizar_test_interactivo(texto_ia, clave_sesion, nombre_tema="General"):
    if f"parsed_{clave_sesion}" not in st.session_state:
        st.session_state[f"parsed_{clave_sesion}"] = parsear_test_a_objetos(texto_ia)
    
    preguntas = st.session_state[f"parsed_{clave_sesion}"]
    if not preguntas:
        st.markdown(texto_ia)
        return

    st.info("💡 **Mode Interactiu:** Selecciona una opció a cada pregunta.")
    respuestas_usuario = {}
    total_preguntas = len(preguntas)
    
    for idx, p in enumerate(preguntas):
        st.markdown(f"**Pregunta {idx + 1}:** {p['enunciado']}")
        opciones_texto = [f"{p['letras'][i]}) {op}" for i, op in enumerate(p['opciones'])]
        seleccion = st.radio(f"Tria opció (P{idx+1}):", options=opciones_texto, key=f"test_q_{clave_sesion}_{idx}", index=None)
        if seleccion:
            letra_elegida = seleccion[0]
            idx_elegido = p['letras'].index(letra_elegida) if letra_elegida in p['letras'] else -1
            respuestas_usuario[idx] = idx_elegido
            if idx_elegido == p['correcta']: st.success("✅ ¡Correcte!")
            else: st.error(f"❌ Incorrecte. La bona era la **{p['letras'][p['correcta']]}) {p['opciones'][p['correcta']]}**")
            if p['explicacion']: st.markdown(f"> 📖 *{p['explicacion']}*")
        st.markdown("---")

    if st.button("💾 Finalitzar i Desar Resultats", key=f"btn_guardar_{clave_sesion}"):
        aciertos, fallos, nuevos_fallos = 0, 0, []
        for idx, p in enumerate(preguntas):
            if idx in respuestas_usuario and respuestas_usuario[idx] == p['correcta']: aciertos += 1
            else:
                fallos += 1
                nuevos_fallos.append({
                    "tema": nombre_tema, "enunciado": p['enunciado'],
                    "correcta": f"{p['letras'][p['correcta']]}) {p['opciones'][p['correcta']]}",
                    "explicacion": p['explicacion'], "fecha": str(datetime.date.today())
                })
        nota_calc = round((aciertos / total_preguntas) * 10, 2) if total_preguntas > 0 else 0.0
        st.session_state.historico_test_temas.append({"fecha": datetime.date.today(), "tema": nombre_tema, "nota": nota_calc, "aciertos": aciertos, "fallos": fallos, "total": total_preguntas})
        guardar_test_temas_disco()
        for nf in nuevos_fallos:
            if not any(f["enunciado"] == nf["enunciado"] for f in st.session_state.banco_fallos):
                st.session_state.banco_fallos.append(nf)
        guardar_banco_fallos_disco()
        st.success(f"🎉 Desat! Nota: {nota_calc}/10")

# ------------------------------------------------------------------------------
# PANEL DE NAVEGACIÓN LATERAL Y DEFINICIÓN DE OPCIÓN (Títulos originales con emojis)
# ------------------------------------------------------------------------------
st.sidebar.title("🚒 Panell de Navegació")
opcion = st.sidebar.radio(
    "Selecciona un mòdul:",
    [
        "📚 Biblioteca del Temari",
        "📝 Simulacre d'Examen",
        "🎯 Test per Temes",
        "💡 Preguntes de Repàs",
        "🏋️‍♂️ Preparació Física",
        "📅 Pla d'Estudi Personalitzat",
        "🎴 Flashcards de Memorització",
        "📄 Esquemes i Taules Tècniques",
        "🏛️ Preguntes Exàmens Oficials",
        "📊 Estadístiques i Progressos",
        "💬 Tutor IA 24/7"
    ]
)

opcion_str = str(opcion)

# ------------------------------------------------------------------------------
# FUNCIÓN AUXILIAR PARA LIMPIAR NOMBRES DE ARCHIVOS
# ------------------------------------------------------------------------------
def limpiar_nombre_archivo(nombre):
    nfkd_form = unicodedata.normalize('NFKD', nombre)
    solo_ascii = nfkd_form.encode('ASCII', 'ignore').decode('ASCII')
    nombre_limpio = re.sub(r'[^\w\s.-]', '', solo_ascii)
    nombre_limpio = nombre_limpio.replace(' ', '_')
    return nombre_limpio

def obtener_texto_acumulado():
    return "".join(st.session_state.textos_pdfs_temario.values())

# ------------------------------------------------------------------------------
# 1. BIBLIOTECA DEL TEMARIO (SINCRONIZADA CON SUPABASE)
# ------------------------------------------------------------------------------
if opcion == "📚 Biblioteca del Temari":
    st.header("📚 Biblioteca del Temari Oficial (Núvol)")
    st.write("Puja els teus PDF. Els noms s'adaptaran automàticament per desar-se sense errors a Supabase.")

    archivos_subidos = st.file_uploader("Puja fitxers PDF:", type=["pdf"], accept_multiple_files=True, key="up_temario")

    if archivos_subidos and supabase:
        for archivo in archivos_subidos:
            nombre_limpio = limpiar_nombre_archivo(archivo.name)
            try:
                supabase.storage.from_("temarios").upload(
                    path=f"temarios/{nombre_limpio}",
                    file=archivo.getvalue(),
                    file_options={"content-type": "application/pdf", "upsert": "true"}
                )
                
                archivo.seek(0)
                texto = "".join([p.extract_text() + "\n" for p in pypdf.PdfReader(archivo).pages if p.extract_text()])
                if texto.strip():
                    st.session_state.textos_pdfs_temario[nombre_limpio] = texto
                    st.success(f"📄 '{nombre_limpio}' pujat i desat al núvol amb èxit.")
            except Exception as e:
                st.error(f"Error en pujar {archivo.name}: {e}")

    if supabase:
        try:
            archivos_nube = supabase.storage.from_("temarios").list("temarios")
            nombres_nube = [f['name'] for f in archivos_nube if f['name'] != '']
        except Exception:
            nombres_nube = []
    else:
        nombres_nube = list(st.session_state.textos_pdfs_temario.keys())

    if nombres_nube:
        st.subheader("📁 Documents al Núvol")
        for doc in nombres_nube:
            c1, c2 = st.columns([0.8, 0.2])
            with c1: st.write(f"• **{doc}**")
            with c2:
                if st.button("Eliminar", key=f"del_doc_{doc}"):
                    if doc in st.session_state.textos_pdfs_temario:
                        del st.session_state.textos_pdfs_temario[doc]
                    try: 
                        supabase.storage.from_("temarios").remove([f"temarios/{doc}"])
                    except Exception: 
                        pass
                    st.rerun()

        st.markdown("---")
        st.subheader("👀 Visor de Documents")
        
        pdf_seleccionado = st.selectbox("Selecciona el temari que vols visualizar:", nombres_nube, key="visor_temario_select")
        
        if pdf_seleccionado:
            if st.button("📖 Carregar i Veure Document", key="btn_cargar_visor"):
                with st.spinner("Descarregant document des del núvol..."):
                    try:
                        ruta_archivo = f"temarios/{pdf_seleccionado}" if not pdf_seleccionado.startswith("temarios/") else pdf_seleccionado
                        response_bytes = supabase.storage.from_("temarios").download(ruta_archivo)
                        
                        if response_bytes:
                            import base64
                            base64_pdf = base64.b64encode(response_bytes).decode('utf-8')
                            altura_visor = st.slider("Ajustar alçada del visor (px):", 400, 1000, 700, 50, key="slider_altura_visor")
                            
                            pdf_display = f'<iframe src="data:application/pdf;base64,{base64_pdf}" width="100%" height="{altura_visor}px" type="application/pdf"></iframe>'
                            st.markdown(pdf_display, unsafe_allow_html=True)
                            
                            st.markdown("---")
                            st.download_button(
                                label=f"📥 Descarregar {pdf_seleccionado}",
                                data=response_bytes,
                                file_name=pdf_seleccionado,
                                mime="application/pdf",
                                key="btn_descarga_visor"
                            )
                    except Exception as e:
                        st.error(f"Error en descarregar el PDF per a la visualització: {e}")

# ------------------------------------------------------------------------------
# 2. SIMULACRE D'EXAMEN
# ------------------------------------------------------------------------------
elif opcion == "📝 Simulacre d'Examen":
    st.header("📝 Simulacre d'Examen Oficial")
    c1, c2 = st.columns(2)
    with c1: 
        num_preguntas = st.slider("Nombre de preguntes:", 10, 120, 50, 10)
    with c2: 
        tiempo_limite = st.slider("Temps límit (minuts):", 15, 180, 90, 15)

    if st.button("🚀 Generar Simulacre"):
        if client is not None:
            txt_ref = obtener_texto_acumulado()
            prompt = (
                f"Genera un examen tipus test oficial de {num_preguntas} preguntes amb 4 opcions (A, B, C, D), "
                f"resposta correcta i explicació. "
                f"Les preguntes s'han de generar estrictament sobre el temari dels PDF pujats a la biblioteca del temari i RESPON EN CATALÀ:\n\n"
                f"{txt_ref[:15000]}"
            )
            with st.spinner("Generant simulacre amb el temari de la biblioteca..."):
                resp = generar_con_reintento(prompt)
                if resp: 
                    st.session_state.simulacro_activo = resp.text

    if "simulacro_activo" in st.session_state:
        st.markdown("---")
        renderizar_test_interactivo(st.session_state.simulacro_activo, "simulacre_gen", nombre_tema="Simulacre Oficial")

# ------------------------------------------------------------------------------
# 3. TEST PER TEMES
# ------------------------------------------------------------------------------
elif opcion == "🎯 Test per Temes":
    st.header("🎯 Test per Temes")
    
    if "textos_pdfs_temario" not in st.session_state:
        st.session_state.textos_pdfs_temario = {}

    # Botó de sincronització manual per a la carpeta 'temarios'
    if st.button("🔄 Sincronitzar PDFs des de Supabase"):
        try:
            archivos_nube = supabase.storage.from_("temarios").list("temarios")
            
            contador = 0
            for archivo in archivos_nube:
                nombre_archivo = archivo.get("name") if isinstance(archivo, dict) else getattr(archivo, "name", None)
                
                if nombre_archivo and nombre_archivo.endswith(".pdf"):
                    ruta_archivo = f"temarios/{nombre_archivo}"
                    pdf_bytes = supabase.storage.from_("temarios").download(ruta_archivo)
                    lector = pypdf.PdfReader(io.BytesIO(pdf_bytes))
                    texto_completo = ""
                    for pagina in lector.pages:
                        texto_extraido = pagina.extract_text()
                        if texto_extraido:
                            texto_completo += texto_extraido + "\n"
                    st.session_state.textos_pdfs_temario[nombre_archivo] = texto_completo
                    contador += 1
            
            if contador > 0:
                st.success(f"¡S'han carregat {contador} PDFs correctament des de la carpeta 'temarios'!")
                st.rerun()
            else:
                st.warning("No s'han trobat arxius PDF dins de la carpeta 'temarios'.")
        except Exception as e:
            st.error(f"Error en sincronitzar amb Supabase: {e}")

    docs = list(st.session_state.textos_pdfs_temario.keys())

    if not docs:
        st.warning("Puja PDFs a la Biblioteca o prem el botó de dalt per sincronitzar amb el núvol.")
    else:
        tema_sel = st.selectbox("Selecciona un document/tema:", docs)
        num_preguntas = st.slider("Nombre de preguntes:", 5, 20, 10)
        
        if st.button("🚀 Generar Test del Tema"):
            texto_base = st.session_state.textos_pdfs_temario[tema_sel]
            prompt = (
                f"A partir del següent text, genera un test tipus test de {num_preguntas} preguntes "
                f"amb 4 opcions (A, B, C, D) i marca la resposta correcta. RESPON EN CATALÀ.\n\nText:\n{texto_base}"
            )
            resp = generar_con_reintento(prompt)
            if resp:
                st.session_state[f"test_{tema_sel}"] = resp.text
        
        key_test = f"test_{tema_sel}"
        if key_test in st.session_state:
            renderizar_test_interactivo(st.session_state[key_test], key_test, nombre_tema=tema_sel)

# ------------------------------------------------------------------------------
# 4. PREGUNTES DE REPÀS
# ------------------------------------------------------------------------------
elif opcion == "💡 Preguntes de Repàs":
    st.header("💡 Preguntes de Repàs Ràpid")
    modo = st.radio("Mode:", ["🎯 Repàs dels meus Errors", "🎲 Repàs Aleatori"])
    
    if "Errors" in modo or "Fallos" in modo:
        if not st.session_state.banco_fallos: 
            st.info("No hi ha errors registrats encara.")
        else:
            st.success(f"Tens {len(st.session_state.banco_fallos)} preguntes guardades dels teus errors anteriors.")
            if st.button("🚀 Carregar Repàs dels Meus Errors"):
                texto_banco_local = ""
                for i, f in enumerate(st.session_state.banco_fallos, 1):
                    texto_banco_local += f"\nPregunta {i}: {f.get('enunciado')}\n"
                    for opcion_letra in ['A', 'B', 'C', 'D']:
                        if f.get(opcion_letra):
                            texto_banco_local += f"- {opcion_letra}) {f[opcion_letra]}\n"
                    texto_banco_local += f"Resposta Correcta: {f.get('correcta')}\n"
                
                st.session_state.repaso_fallos_activo = texto_banco_local

            if "repaso_fallos_activo" in st.session_state:
                renderizar_test_interactivo(st.session_state.repaso_fallos_activo, "repaso_fallos", nombre_tema="Repàs dels Meus Errors")
                
    else:
        if st.button("🚀 Generar Repàs Aleatori"):
            resp = generar_con_reintento("Genera 10 preguntes de repàs general tipus test per a Bombers. RESPON EN CATALÀ.")
            if resp: 
                st.session_state.repaso_aleatorio = resp.text
        if "repaso_aleatorio" in st.session_state:
            renderizar_test_interactivo(st.session_state.repaso_aleatorio, "repaso_rand", nombre_tema="Repàs Aleatori")
# ------------------------------------------------------------------------------
# 5. PREPARACIÓ FÍSICA (ESTIL HEVY INTEGRAT)
# ------------------------------------------------------------------------------
elif "Preparación Física" in opcion or "Preparació Física" in opcion:
    st.header("🏋️‍♂️ Preparación Física & Progreso")
    
    # Assegurar variables per evitar fallades en blanc
    if "mis_rutinas" not in st.session_state:
        st.session_state.mis_rutinas = {}
    if "historial_marcas" not in st.session_state:
        st.session_state.historial_marcas = []
    if "historial_carreras" not in st.session_state:
        st.session_state.historial_carreras = []
    
    lista_ej_disponibles = globals().get("LISTA_EJERCICIOS_HEAVY", ["Press Banca", "Dominades", "Sentadilla", "Peso Muerto", "Cursa"])

    t1, t2, t3, t4 = st.tabs(["🏋️‍♂️ Entrenar Rutina", "➕ Crear / Gestionar Rutinas", "📈 Gráficas de Progreso", "🏃‍♂️ Entrenamientos de Carrera"])
    
    with t1:
        if not st.session_state.mis_rutinas:
            st.info("No tienes ninguna rutina creada todavía. Ve a la pestaña 'Crear / Gestionar Rutinas' para añadir una.")
        else:
            rutina_sel = st.selectbox("Selecciona tu rutina de hoy:", list(st.session_state.mis_rutinas.keys()), key="select_rutina_hoy")
            fecha_entreno = st.date_input("Fecha del entrenamiento:", value=datetime.date.today(), key="fecha_entreno_hoy")
            
            st.markdown(f"### Ejercicios de: {rutina_sel}")
            ejercicios_rutina = st.session_state.mis_rutinas[rutina_sel]
            
            nuevos_registros = []
            
            for ej in ejercicios_rutina:
                st.markdown(f"#### 🔹 {ej}")
                num_series = st.number_input(f"Número de series para {ej}:", 1, 6, 3, key=f"ns_{ej}")
                
                for s in range(1, int(num_series) + 1):
                    peso_anterior_s = 0.0
                    reps_anterior_s = 10
                    if st.session_state.historial_marcas:
                        df_h = pd.DataFrame(st.session_state.historial_marcas)
                        if "Ejercicio" in df_h.columns and "Serie" in df_h.columns:
                            df_ej = df_h[(df_h["Ejercicio"] == ej) & (df_h["Serie"] == s)]
                            if not df_ej.empty:
                                ultimo_reg_s = df_ej.iloc[-1]
                                peso_anterior_s = float(ultimo_reg_s.get("Peso (kg)", 0.0))
                                reps_anterior_s = int(ultimo_reg_s.get("Reps", 10))
                            else:
                                df_ej_gen = df_h[df_h["Ejercicio"] == ej]
                                if not df_ej_gen.empty:
                                    ultimo_reg_gen = df_ej_gen.iloc[-1]
                                    peso_anterior_s = float(ultimo_reg_gen.get("Peso (kg)", 0.0))
                                    reps_anterior_s = int(ultimo_reg_gen.get("Reps", 10))

                    col_prev, col_s1, col_s2, col_s3 = st.columns([1.2, 0.8, 1, 1])
                    
                    with col_prev:
                        if peso_anterior_s > 0:
                            st.markdown(f"🕒 *Ant: {peso_anterior_s}kg × {reps_anterior_s}r*")
                        else:
                            st.markdown("🕒 *Ant: Sin datos*")
                            
                    with col_s1: st.text(f"Serie {s}")
                    with col_s2: 
                        peso_s = st.number_input(f"Peso (kg) - {ej} S{s}", min_value=0.0, value=peso_anterior_s, step=0.5, key=f"peso_{ej}_{s}")
                    with col_s3: 
                        reps_s = st.number_input(f"Reps - {ej} S{s}", min_value=1, max_value=100, value=reps_anterior_s, step=1, key=f"reps_{ej}_{s}")
                    
                    if peso_anterior_s > 0 and (peso_s > peso_anterior_s or (peso_s == peso_anterior_s and reps_s > reps_anterior_s)):
                        st.success(f"🏆 ¡Récord superado en {ej} (Serie {s})! 🥇")
                    
                    nuevos_registros.append({
                        "Fecha": str(fecha_entreno),
                        "Rutina": rutina_sel,
                        "Ejercicio": ej,
                        "Serie": s,
                        "Peso (kg)": peso_s,
                        "Reps": reps_s
                    })
                st.markdown("---")
            
            if st.button("💾 Guardar Entrenamiento y Actualizar Progreso", key="btn_guardar_entreno_fuerza"):
                st.session_state.historial_marcas.extend(nuevos_registros)
                if "guardar_marcas_nube" in globals():
                    guardar_marcas_nube()
                st.success("🎉 ¡Entrenamiento guardado con éxito en la nube!")

    with t2:
        st.subheader("Crea y gestiona tus rutinas de entrenamiento")
        
        if "editando_rutina" not in st.session_state:
            st.session_state.editando_rutina = None
        if "form_nombre_rutina" not in st.session_state:
            st.session_state.form_nombre_rutina = ""
        if "form_ejs_rutina" not in st.session_state:
            st.session_state.form_ejs_rutina = []

        rutina_en_edicion = st.session_state.editando_rutina

        if rutina_en_edicion:
            st.info(f"✏️ Estás editando la rutina: **{rutina_en_edicion}**.")

        nombre_nueva_rutina = st.text_input("Nombre de la rutina:", value=st.session_state.form_nombre_rutina, key="input_nombre_rutina_t2")
        lista_ejercicios = st.multiselect("Selecciona o deselecciona ejercicios:", lista_ej_disponibles, default=st.session_state.form_ejs_rutina, key="multiselect_ejercicios_t2")
        
        col_b1, col_b2 = st.columns([0.8, 0.2])
        with col_b1:
            btn_texto = "💾 Guardar Cambios de la Rutina" if rutina_en_edicion else "➕ Guardar Nueva Rutina"
            if st.button(btn_texto, key="btn_guardar_rutina_accion_t2"):
                if nombre_nueva_rutina and lista_ejercicios:
                    if rutina_en_edicion and rutina_en_edicion != nombre_nueva_rutina:
                        if rutina_en_edicion in st.session_state.mis_rutinas:
                            del st.session_state.mis_rutinas[rutina_en_edicion]

                    st.session_state.mis_rutinas[nombre_nueva_rutina] = lista_ejercicios
                    st.session_state.editando_rutina = None
                    st.session_state.form_nombre_rutina = ""
                    st.session_state.form_ejs_rutina = []
                    st.success(f"¡Rutina '{nombre_nueva_rutina}' guardada con éxito!")
                    st.rerun()
                else:
                    st.warning("Introduce un nombre y selecciona al menos un ejercicio.")
        
        with col_b2:
            if rutina_en_edicion:
                if st.button("❌ Cancelar", key="cancelar_edicion_rutina_t2"):
                    st.session_state.editando_rutina = None
                    st.session_state.form_nombre_rutina = ""
                    st.session_state.form_ejs_rutina = []
                    st.rerun()

        if st.session_state.mis_rutinas:
            st.markdown("---")
            st.markdown("### TUS RUTINAS ACTUALES:")
            for i, r_nombre in enumerate(list(st.session_state.mis_rutinas.keys())):
                r_ejs = st.session_state.mis_rutinas[r_nombre]
                c_r1, c_r2, c_r3 = st.columns([0.65, 0.17, 0.18])
                with c_r1: st.write(f"• **{r_nombre}**: {', '.join(r_ejs)}")
                with c_r2:
                    if st.button("✏️", key=f"edit_rutina_idx_{i}"):
                        st.session_state.editando_rutina = r_nombre
                        st.session_state.form_nombre_rutina = r_nombre
                        st.session_state.form_ejs_rutina = r_ejs
                        st.rerun()
                with c_r3:
                    if st.button("🗑️", key=f"del_rutina_idx_{i}"):
                        if r_nombre in st.session_state.mis_rutinas:
                            del st.session_state.mis_rutinas[r_nombre]
                        st.rerun()

    with t3:
        st.subheader("📈 Gráficas de Progreso")
        tipo_progreso = st.radio("Selecciona el tipo de progreso a visualizar:", ["🏋️‍♂️ Fuerza (Gym)", "🏃‍♂️ Carrera"], horizontal=True, key="radio_tipo_progreso")
        
        if "Fuerza" in tipo_progreso:
            if st.session_state.historial_marcas and st.session_state.mis_rutinas:
                df_marcas = pd.DataFrame(st.session_state.historial_marcas)
                rutina_grafico = st.selectbox("Selecciona la rutina para ver el desglose de sus ejercicios:", list(st.session_state.mis_rutinas.keys()), key="select_rutina_grafico")
                if rutina_grafico:
                    for ej in st.session_state.mis_rutinas[rutina_grafico]:
                        st.markdown(f"#### 📊 {ej}")
                        df_filtrado = df_marcas[df_marcas["Ejercicio"] == ej]
                        if not df_filtrado.empty:
                            max_peso = df_filtrado["Peso (kg)"].max()
                            st.metric(label=f"🏆 Récord Personal (PR) en {ej}", value=f"{max_peso} kg")
                            st.line_chart(df_filtrado.set_index("Fecha")[["Peso (kg)"]])
                        else:
                            st.info(f"Todavía no hay registros guardados para {ej}.")
            else:
                st.info("Todavía no hay registros de entrenamientos de fuerza o rutinas guardadas.")
        else:
            if st.session_state.historial_carreras:
                df_carreras = pd.DataFrame(st.session_state.historial_carreras)
                st.markdown("#### 📊 Evolución de Kilómetros por Sesión")
                st.line_chart(df_carreras.set_index("Fecha")[["Kilómetros (km)"]])
                st.markdown("#### 📋 Historial Completo de Carrera")
                st.dataframe(df_carreras, use_container_width=True)
            else:
                st.info("Todavía no hay registros de entrenamientos de carrera guardados.")

    with t4:
        st.subheader("🏃‍♂️ Registrar Entrenamiento de Carrera")
        fecha_carrera = st.date_input("Fecha de la carrera:", value=datetime.date.today(), key="fecha_carrera_input_t4")
        col_c1, col_c2 = st.columns(2)
        with col_c1:
            tipo_carrera = st.text_input("Tipo de entreno / Nombre (ej: Series 400m, Rodaje Suave):", value="Rodaje Suave", key="input_tipo_carrera_t4")
            n_series = st.number_input("Cantidad de series (0 si es continuo):", min_value=0, step=1, value=0, key="input_n_series_t4")
            km_totales = st.number_input("Kilómetros totales (km):", min_value=0.0, step=0.1, value=5.0, key="input_km_totales_t4")
        with col_c2:
            tiempo_total = st.text_input("Tiempo total (ej: 25:00):", value="25:00", key="input_tiempo_total_t4")
            ritmo_medio = st.text_input("Ritmo medio (ej: 4:30 min/km):", value="5:00", key="input_ritmo_medio_t4")

        if st.button("💾 Guardar Entrenamiento de Carrera y Progreso", key="btn_guardar_carrera_t4"):
            st.session_state.historial_carreras.append({
                "Fecha": str(fecha_carrera), "Entreno": tipo_carrera, "Series": n_series,
                "Kilómetros (km)": km_totales, "Tiempo": tiempo_total, "Ritmo": ritmo_medio
            })
            if "guardar_carreras_nube" in globals():
                guardar_carreras_nube()
            st.success("🎉 ¡Entrenamiento de carrera guardado y añadido al progreso con éxito!")

    # ------------------------------------------------------------------------------
    # REGISTRE DE LES NOVES PROVES FÍSIQUES - BOMBERS GENERALITAT
    # ------------------------------------------------------------------------------
    st.markdown("---")
    st.markdown("### 🚒 Simulacre de les Noves Proves Oficials")
    tipo_prueba_oficial = st.selectbox("Selecciona la prova oficial a registrar:", [
        "1. Intervenció Estructural (Circuit)",
        "2. Intervenció Forestal (Rectes + Slam Ball)",
        "3. Prova Aquàtica / Rescat (6 fases)"
    ], key="select_prova_oficial_bombers")

    fecha_oficial = st.date_input("Data del simulacre:", value=datetime.date.today(), key="fecha_simulacre_oficial_bombers")

    if "1. Intervenció Estructural" in tipo_prueba_oficial:
        st.info("Circuit continu: Transport de discos, Step-Up, kettlebells, arrossegament/empenta de trineu, obstacle, maniquí i esprint.")
        c1, c2 = st.columns(2)
        with c1: temps_estructural = st.text_input("Temps total empleat (ej: 03:45):", value="03:45", key="t_est")
        with c2: penalitzacions_est = st.number_input("Segons de penalització (errors):", min_value=0, step=1, value=0, key="p_est")
        
        if st.button("💾 Guardar Registre Estructural", key="btn_est"):
            reg_est = {"Data": str(fecha_oficial), "Prova": "Intervenció Estructural", "Temps/Marca": temps_estructural, "Penalització (s)": penalitzacions_est}
            if "historial_proves_oficials" not in st.session_state: st.session_state.historial_proves_oficials = []
            st.session_state.historial_proves_oficials.append(reg_est)
            st.success("🎉 ¡Simulacre estructural guardat correctament!")

    elif "2. Intervenció Forestal" in tipo_prueba_oficial:
        st.info("Prova progressiva: Alterna desplaçaments de 20m amb llançaments de Slam Ball per blocs (8, 10 o 12 rectes).")
        f1, f2 = st.columns(2)
        with f1: bloc_assolit = st.selectbox("Últim bloc completat:", ["Bloc 1 (8 rectes + 16 Slam Ball)", "Bloc 2 (10 rectes + 20 Slam Ball)", "Bloc 3 (12 rectes + 24 Slam Ball)"], key="b_for")
        with f2: temps_forestal = st.text_input("Temps total (ej: 02:30):", value="02:30", key="t_for")
            
        if st.button("💾 Guardar Registre Forestal", key="btn_for"):
            reg_for = {"Data": str(fecha_oficial), "Prova": f"Intervenció Forestal - {bloc_assolit}", "Temps/Marca": temps_forestal, "Penalització (s)": 0}
            if "historial_proves_oficials" not in st.session_state: st.session_state.historial_proves_oficials = []
            st.session_state.historial_proves_oficials.append(reg_for)
            st.success("🎉 ¡Simulacre forestal guardat correctament!")

    else:
        st.info("Prova Aquàtica de Rescat: Entrada, 15m apnea, 30s flotació, crol lliure, crol de salvament i remolc de maniquí (6 fases consecutives).")
        a1, a2 = st.columns(2)
        with a1: temps_aigua = st.text_input("Temps total de la prova aquàtica (ej: 01:55):", value="01:55", key="t_aq")
        with a2: fase_fallida = st.selectbox("Fase amb més dificultat o error:", ["Cap (Completat)", "Fase 1: Entrada", "Fase 2: Apnea 15m", "Fase 3: Flotació 30s", "Fase 4: Crol lliure", "Fase 5: Crol salvament", "Fase 6: Remolc maniquí"], key="f_aq")

        if st.button("💾 Guardar Registre Aquàtic", key="btn_aq"):
            reg_aq = {"Data": str(fecha_oficial), "Prova": f"Aquàtica (Incidència: {fase_fallida})", "Temps/Marca": temps_aigua, "Penalització (s)": 0}
            if "historial_proves_oficials" not in st.session_state: st.session_state.historial_proves_oficials = []
            st.session_state.historial_proves_oficials.append(reg_aq)
            st.success("🎉 ¡Registre aquàtic guardat correctament!")

    if st.session_state.get("historial_proves_oficials"):
        st.markdown("---")
        st.markdown("### 📋 Historial de Simulacres de las Nuevas Pruebas")
        st.dataframe(pd.DataFrame(st.session_state.historial_proves_oficials), use_container_width=True)
# ------------------------------------------------------------------------------
# 6. PLA D'ESTUDI
# ------------------------------------------------------------------------------
elif "6." in opcion_str or "Pla" in opcion_str or "Plan" in opcion_str:
    st.header("📅 Planificador Estratègic d'Estudi")
    st.write("Dissenya la teua planificació teórica a llarg termini basada en els PDFs de la teua biblioteca + 7 temes de legislació.")
    
    col_ps1, col_ps2 = st.columns(2)
    with col_ps1:
        hs = st.slider("Hores disponibles a la setmana:", 5, 50, 20, 5)
    with col_ps2:
        dias_estudio = st.multiselect(
            "Dies d'estudi setmanals:",
            ["Dilluns", "Dimarts", "Dimecres", "Dijous", "Divendres", "Dissabte", "Diumenge"],
            default=["Dilluns", "Dimarts", "Dimecres", "Dijous", "Divendres"]
        )

    if st.button("🚀 Generar Pla Estratègic"):
        if not dias_estudio:
            st.warning("Selecciona al menys un dia d'estudi a la setmana.")
        else:
            # Generació local exacta basada en el pla, desplaçada per començar en dijous
            pla_local = [
                {
                    "semana": "1: Domini del bloc de marc constitucional",
                    "objetivo": "Inici del pla d'estudi estratègic adaptat a dijous.",
                    "dias": [
                        {"dia": "Dijous (Avui)", "tareas": ["Tema 01: Constitución Española, Estatut d'Autonomia, Administración catalana e instituciones - 3 horas de lectura y subrayado + 1 hora de test"]},
                        {"dia": "Divendres", "tareas": ["Tema 01: Constitución Española, Estatut d'Autonomia, Administración catalana e instituciones - 3 horas de profundización y esquemas + 1 hora de test"]}
                    ]
                },
                {
                    "semana": "2: Legislació de igualtat i normativa específica",
                    "objetivo": "Continuació del bloc normatiu.",
                    "dias": [
                        {"dia": "Dilluns", "tareas": ["Tema 02: Personal al servicio de administraciones públicas, función pública de la Generalitat, derechos, deberes y régimen disciplinario - 3 horas de lectura y subrayado + 1 hora de test"]},
                        {"dia": "Dimarts", "tareas": ["Tema 02: Personal al servicio de administraciones públicas, función pública de la Generalitat, derechos, deberes y régimen disciplinario - 3 horas de estudio de régimen disciplinario + 1 hora de test"]},
                        {"dia": "Dimecres", "tareas": ["Tema 03: Ley 31/1995 de Prevención de Riesgos Laborales, EPIs y normativa de despliegue - 3 horas de estudio y esquemas + 1 hora de test"]},
                        {"dia": "Dijous", "tareas": ["Tema 04: Ley 19/2020 d'igualtat de tracte i no discriminació - 3 horas de lectura y subrayado + 1 hora de test"]},
                        {"dia": "Divendres", "tareas": ["Tema 05: Ley 17/2015 d'igualtat efectiva de mujeres y hombres (Cap. 1, 3 y 4) - 3 horas de lectura y esquemas + 1 hora de test"]}
                    ]
                },
                {
                    "semana": "3: Ciències bàsiques aplicades: Fuego, Física y Química",
                    "objetivo": "Física i química aplicada al foc.",
                    "dias": [
                        {"dia": "Dilluns", "tareas": ["Tema 06: Ley 5/1994 de servicios de prevención y extinción de incendios y salvamentos de Cataluña y Ley 4/1997 de Protección Civil - 3 horas de lectura y estudio + 1 hora de test"]},
                        {"dia": "Dimarts", "tareas": ["Tema 06: Ley 5/1994 de servicios de prevención y extinción de incendios y salvamentos de Cataluña y Ley 4/1997 de Protección Civil - 3 horas de esquemas y consolidación + 1 hora de test"]},
                        {"dia": "Dimecres", "tareas": ["Tema 07: Decreto 276/2016 de funciones de guardia y sistema de mando, y Decreto 12/2023 de reestructuración del departamento de Interior - 3 horas de estudio detallado + 1 hora de test"]},
                        {"dia": "Dijous", "tareas": ["Tema 08: Teoría del Fuego - 3 horas de lectura y esquemas + 1 hora de test"]},
                        {"dia": "Divendres", "tareas": ["Tema 09: Física - 3 horas de lectura y conceptos fundamentales + 1 hora de test"]}
                    ]
                },
                {
                    "semana": "4: Electricidad, Instalaciones, hidráulica y orientación",
                    "objetivo": "Hidràulica, instal·lacions i orientació.",
                    "dias": [
                        {"dia": "Dilluns", "tareas": ["Tema 09: Física - 3 horas de resolución de problemas + 1 hora de test"]},
                        {"dia": "Dimarts", "tareas": ["Tema 10: Química - 3 horas de lectura y formulación básica + 1 hora de test"]},
                        {"dia": "Dimecres", "tareas": ["Tema 10: Química - 3 horas de estudio de reacciones y productos peligrosos + 1 hora de test"]},
                        {"dia": "Dijous", "tareas": ["Tema 11: Electricidad - 3 horas de lectura y esquemas + 1 hora de test"]},
                        {"dia": "Divendres", "tareas": ["Tema 12: Instalaciones - 3 horas de estudio de edificación y servicios + 1 hora de test"]}
                    ]
                },
                {
                    "semana": "5: Construcción, asistencia técnica, comunicaciones y parque",
                    "objetivo": "Sistemes de construcció i vehicles.",
                    "dias": [
                        {"dia": "Dilluns", "tareas": ["Tema 13: Hidráulica y Bombas - 3 horas de teoría de fluidos e hidrostática + 1 hora de test"]},
                        {"dia": "Dimarts", "tareas": ["Tema 13: Hidráulica y Bombas - 3 horas de hidrodinámica y cálculo de bombas + 1 hora de test"]},
                        {"dia": "Dimecres", "tareas": ["Tema 14: Cartografía y Orientación - 3 horas de estudio de mapas y escalas + 1 hora de test"]},
                        {"dia": "Dijous", "tareas": ["Tema 15: Construcción - 3 horas de lectura y análisis de elementos estructurales + 1 hora de test"]},
                        {"dia": "Divendres", "tareas": ["Tema 16: Intervención básica en asistencias técnicas - 3 horas de estudio de procedimientos + 1 hora de test"]}
                    ]
                },
                {
                    "semana": "6: Protección individual, gestión operativa e intervención",
                    "objetivo": "EPIs i operativitat contra incendis.",
                    "dias": [
                        {"dia": "Dilluns", "tareas": ["Tema 17: Comunicaciones por radio - 3 horas de estudio de protocolos y redes + 1 hora de test"]},
                        {"dia": "Dimarts", "tareas": ["Tema 18: Vehículos de intervención en emergencias - 3 horas de lectura y tipologías + 1 hora de test"]},
                        {"dia": "Dimecres", "tareas": ["Tema 19: Conducción y mecánica - 3 horas de estudio de mecánica y conducción de emergencia + 1 hora de test"]},
                        {"dia": "Dijous", "tareas": ["Tema 20: Equipos de protección individual en emergencias - 3 horas de estudio de EPIs y ERA + 1 hora de test"]},
                        {"dia": "Divendres", "tareas": ["Tema 21: Introducción a la gestión de emergencias y Protección Civil - 3 horas de lectura y esquemas + 1 hora de test"]}
                    ]
                },
                {
                    "semana": "7: Incendios forestales, riesgos especiales y NRBQ",
                    "objetivo": "Incendis forestals i riscos específics.",
                    "dias": [
                        {"dia": "Dilluns", "tareas": ["Tema 22: Principios y características del Sistema de Mando - 3 horas de análisis del sistema + 1 hora de test"]},
                        {"dia": "Dimarts", "tareas": ["Tema 23: Prevención básica de incendios - 3 horas de lectura y normativa + 1 hora de test"]},
                        {"dia": "Dimecres", "tareas": ["Tema 24: Intervención básica en incendios estructurales - 3 horas de estudio táctico y desarrollo + 1 hora de test"]},
                        {"dia": "Dijous", "tareas": ["Tema 24: Intervención básica en incendis estructurals - 3 horas de profundización e hidráulica de incendios + 1 hora de test"]},
                        {"dia": "Divendres", "tareas": ["Tema 25: Intervención básica en incendios forestales - 3 horas de estudio de comportamiento y extinción + 1 hora de test"]}
                    ]
                },
                {
                    "semana": "8: Atención sanitaria, múltiples víctimas y salvamento",
                    "objetivo": "Sanitària i rescats.",
                    "dias": [
                        {"dia": "Dilluns", "tareas": ["Tema 26: Prevención incendios varios - 3 horas de lectura y esquemas + 1 hora de test"]},
                        {"dia": "Dimarts", "tareas": ["Tema 27: Intervención básica en riesgos NRBQ - 3 horas de zonificación e identificación de sustancias + 1 hora de test"]},
                        {"dia": "Dimecres", "tareas": ["Tema 27: Intervención básica en riesgos NRBQ - 3 horas de descontaminación y protocolos + 1 hora de test"]},
                        {"dia": "Dijous", "tareas": ["Tema 28: Asistencia sanitaria - 3 horas de soporte vital básico y anatomía + 1 hora de test"]},
                        {"dia": "Divendres", "tareas": ["Tema 28: Asistencia sanitaria - 3 horas de atención al trauma y patologías urgentes + 1 hora de test"]}
                    ]
                },
                {
                    "semana": "9: Rescate en accidentes de tráfico, entornos urbanos e inundaciones",
                    "objetivo": "Tancament de la volta amb rescats i inundacions.",
                    "dias": [
                        {"dia": "Dilluns", "tareas": ["Tema 29: Intervención básica en incidentes de múltiples víctimas - 3 horas de estudio de triaje y organización + 1 hora de test"]},
                        {"dia": "Dimarts", "tareas": ["Tema 30: Intervención básica en estructuras colapsadas - 3 horas de apuntalamientos y búsqueda + 1 hora de test"]},
                        {"dia": "Dimecres", "tareas": ["Tema 31: Intervención básica al medi natural terrestre - 3 horas de técnicas de rescate terrestre + 1 hora de test"]},
                        {"dia": "Dijous", "tareas": ["Tema 32: Intervención básica en accidentes de movilidad viaria - 3 horas de estudio de excarcelación y estabilización + 1 hora de test"]},
                        {"dia": "Divendres", "tareas": ["Tema 33: Intervención básica en rescate urbano - 3 horas de estudio de rescate en altura y espacios confinados + 1 hora de test"]}
                    ]
                },
                {
                    "semana": "10: Repàs final i tancament",
                    "objetivo": "Últims temes i consolidació de la volta.",
                    "dias": [
                        {"dia": "Dilluns", "tareas": ["Tema 34: Intervención básica en inundaciones - 3 horas de estudio de dinámicas de riadas y rescate acuático + 1 hora de test"]},
                        {"dia": "Dimarts", "tareas": ["Tema 28: Asistencia sanitaria - 3 horas de repaso general de algoritmos + 1 hora de test global de sanidad"]},
                        {"dia": "Dimecres", "tareas": ["Tema 13: Hidráulica y Bombas - 3 horas de repaso de fórmulas y cálculos aplicados + 1 hora de test global de hidráulica"]}
                    ]
                }
            ]

            st.session_state.plan_estudio_json = pla_local
            st.session_state.plan_estudio_texto_raw = ""
            st.success("¡Pla d'estudi estratègic carregat exactament a mida!")
            if 'guardar_plan_nube' in globals():
                guardar_plan_nube()

    if "plan_estudio_json" in st.session_state and st.session_state.plan_estudio_json:
        st.markdown("---")
        st.subheader("📋 El teu Pla d'Estudi Interactiu")
        if "progreso_estudio" not in st.session_state:
            st.session_state.progreso_estudio = {}

        for k, v in st.session_state.progreso_estudio.items():
            st.session_state[k] = v

        for sem in st.session_state.plan_estudio_json:
            with st.expander(f"Setmana {sem.get('semana')}: {sem.get('objetivo', '')}", expanded=False):
                for d_info in sem.get('dias', []):
                    dia_nombre = d_info.get('dia', '')
                    st.markdown(f"**📅 {dia_nombre}**")
                    for t_idx, tarea in enumerate(d_info.get('tareas', [])):
                        key_check = f"chk_sem_{sem.get('semana')}_{dia_nombre}_{t_idx}"
                        if key_check not in st.session_state:
                            st.session_state[key_check] = st.session_state.progreso_estudio.get(key_check, False)

                        def actualizar_checkbox(k=key_check):
                            st.session_state.progreso_estudio[k] = st.session_state[k]
                            if 'guardar_plan_nube' in globals():
                                guardar_plan_nube()

                        st.checkbox(tarea, key=key_check, on_change=actualizar_checkbox)
                    st.markdown("")

    elif "plan_estudio_texto_raw" in st.session_state and st.session_state.plan_estudio_texto_raw:
        st.markdown("---")
        st.markdown(st.session_state.plan_estudio_texto_raw)
# ------------------------------------------------------------------------------
# 7. FLASHCARDS
# ------------------------------------------------------------------------------
elif "7." in opcion_str or "Flashcards" in opcion_str or "Targetes" in opcion_str:
    st.header("🎴 Targetes de Memorització")
    docs = list(st.session_state.textos_pdfs_temario.keys())
    t1, t2 = st.tabs(["➕ Generar Flashcards", "🎴 Veure Flashcards Guardades"])
    with t1:
        if not docs: 
            st.warning("Puja PDFs primer a la biblioteca.")
        else:
            ts = st.selectbox("Tema base:", docs)
            nf = st.slider("Nombre de flashcards:", 3, 15, 8)
            if st.button("Generar Flashcards"):
                resp = generar_con_reintento(f"Genera {nf} flashcards (anvers i revers concisos) basades en: {st.session_state.textos_pdfs_temario[ts][:10000]}. Torna un JSON pur en format de llista de diccionaris amb claus 'anverso' i 'reverso'. RESPON EN CATALÀ.")
                if resp:
                    try:
                        clean = resp.text.strip().replace("```json", "").replace("```", "")
                        cards = json.loads(clean)
                        for c in cards:
                            c["tema"] = ts
                            if not any(x.get("anverso") == c.get("anverso") for x in st.session_state.flashcards):
                                st.session_state.flashcards.append(c)
                        guardar_flashcards_disco()
                        st.success("¡Flashcards guardades!")
                    except Exception as e: 
                        st.error(f"Error processant JSON: {e}")
    with t2:
        if not st.session_state.flashcards: 
            st.info("No hi ha flashcards guardades.")
        else:
            for fc in st.session_state.flashcards:
                with st.expander(f"[{fc.get('tema')}] {fc.get('anverso')}"):
                    st.write(fc.get('reverso'))


# ------------------------------------------------------------------------------
# 8. ESQUEMES I TAULES TÈCNIQUES
# ------------------------------------------------------------------------------
elif "8." in opcion_str or "Esquemas" in opcion_str or "Esquemes" in opcion_str:
    st.header("📄 Generador de Material Sintètic")
    docs = list(st.session_state.textos_pdfs_temario.keys())
    if not docs: 
        st.warning("Puja PDFs primer a la biblioteca.")
    else:
        ts = st.selectbox("Tema:", docs)
        tipo = st.selectbox("Format:", ["Maquetat Mnemotècnic", "Taula Comparativa", "Resum Executiu"])
        if st.button("Generar Esquema"):
            resp = generar_con_reintento(f"Genera un recurs tipus '{tipo}' enfocat a oposicions de Bombers basat en: {st.session_state.textos_pdfs_temario[ts][:12000]}. RESPON EN CATALÀ.")
            if resp: 
                st.markdown(resp.text)


# ------------------------------------------------------------------------------
# 9. EXÀMENS OFICIALS
# ------------------------------------------------------------------------------
elif "9." in opcion_str or "Exámenes" in opcion_str or "Exàmens" in opcion_str:
    st.header("🏛️ Simulador Exàmens Oficials (Núvol)")
    oficiales = st.file_uploader("Puja exàmens oficials anteriors:", type=["pdf"], accept_multiple_files=True, key="up_oficiales")
    if oficiales and supabase:
        for arch in oficiales:
            nombre_limpio_of = limpiar_nombre_archivo(arch.name)
            if nombre_limpio_of not in st.session_state.textos_pdfs_oficiales:
                try:
                    supabase.storage.from_("temarios").upload(f"oficiales/{nombre_limpio_of}", arch.getvalue(), {"content-type": "application/pdf", "upsert": "true"})
                    arch.seek(0)
                    txt = "".join([p.extract_text() + "\n" for p in pypdf.PdfReader(arch).pages if p.extract_text()])
                    if txt.strip(): 
                        st.session_state.textos_pdfs_oficiales[nombre_limpio_of] = txt
                except Exception as e: 
                    st.error(f"Error: {e}")
    
    docs_oficiales = list(st.session_state.textos_pdfs_oficiales.keys())
    if docs_oficiales:
        st.success(f"Hi ha {len(docs_oficiales)} document(s) oficial(s) carregat(s) a la base.")
        
        st.markdown("---")
        st.subheader("⚙️ Configuració del Test / Simulacre")
        c1, c2 = st.columns(2)
        with c1: 
            num_preg_of = st.slider("Nombre de preguntes:", 10, 100, 25, 5, key="slider_num_oficiales")
        with c2: 
            tiempo_lim_of = st.slider("Temps límit (minuts):", 15, 180, 45, 15, key="slider_tiempo_oficiales")
        
        modo_gen_of = st.radio(
            "Selecciona el mode d'examen oficial:",
            ["Simulacre Mixt (Tots els exàmens)", "Test Específic per Temari Oficial"],
            horizontal=True
        )

        if modo_gen_of == "Simulacre Mixt (Tots els exàmens)":
            if st.button("🚀 Generar Simulacre Oficial Mixt"):
                if verificar_cliente():
                    texto_oficiales_acumulado = obtener_texto_acumulado_oficiales()
                    prompt_oficial = (
                        f"Actua com un tribunal d'oposició de Bombers de la Generalitat. "
                        f"Genera un simulacre d'examen oficial de {num_preg_of} preguntes tipus test amb 4 opcions (A, B, C, D) "
                        f"basades estrictament en els següents exàmens oficials i RESPON EN CATALÀ:\n\n{texto_oficiales_acumulado[:15000]}"
                    )
                    with st.spinner("Generant simulacre mixt..."):
                        resp = generar_con_reintento(prompt_oficial)
                        if resp: 
                            st.session_state.sim_of_activo = resp.text
                            st.success("¡Simulacre oficial generat amb èxit!")

        else:
            tema_oficial_elegido = st.selectbox(
                "Selecciona el temari corresponent de la biblioteca:",
                ["Física i Hidràulica", "Química i Foc", "Legislació", "Mecànica i Vehicles", "Construcció i Edificació", "Sanitària / Primers Auxilis", "General / Diversos"]
            )
            
            if st.button("🚀 Generar Test Oficial per Temari"):
                if verificar_cliente():
                    texto_oficiales_acumulado = obtener_texto_acumulado_oficiales()
                    prompt_oficial_tema = (
                        f"Actua com un tribunal d'oposició de Bombers de la Generalitat. "
                        f"Genera un test oficial de {num_preg_of} preguntes tipus test (A, B, C, D) sobre el tema '{tema_oficial_elegido}' "
                        f"basat en els següents documents i RESPON EN CATALÀ:\n{texto_oficiales_acumulado[:15000]}"
                    )
                    with st.spinner(f"Generant test de '{tema_oficial_elegido}'..."):
                        resp = generar_con_reintento(prompt_oficial_tema)
                        if resp: 
                            st.session_state.sim_of_activo = resp.text
                            st.success("¡Test oficial generat amb èxit!")

        if "sim_of_activo" in st.session_state:
            st.markdown("---")
            renderizar_test_interactivo(st.session_state.sim_of_activo, "sim_of", nombre_tema="Examen Oficial")
    else:
        st.info("Puja almenys un PDF d'examen oficial a dalt.")


# ------------------------------------------------------------------------------
# 10. ESTADÍSTIQUES I PROGRESSOS
# ------------------------------------------------------------------------------
elif "10." in opcion_str or "Estadísticas" in opcion_str or "Estadístiques" in opcion_str:
    st.header("📊 Panell d'Estadístiques i Progrés")
    t1, t2, t3 = st.tabs(["📝 Simulacres", "🎯 Test per Temes", "📚 Temari"])
    
    with t1:
        if "historico" in st.session_state and st.session_state.historico:
            df = pd.DataFrame(st.session_state.historico)
            st.metric("Nota Mitjana Simulacres", f"{df['nota'].mean():.2f}")
            st.dataframe(df, use_container_width=True)
            if "fecha" in df.columns and "nota" in df.columns:
                st.line_chart(df.set_index("fecha")[["nota"]])
        else: 
            st.info("Sense registres de simulacres.")
            
    with t2:
        if "historico_test_temas" in st.session_state and st.session_state.historico_test_temas:
            df2 = pd.DataFrame(st.session_state.historico_test_temas)
            st.metric("Nota Mitjana Temes", f"{df2['nota'].mean():.2f}")
            st.dataframe(df2, use_container_width=True)
            if "fecha" in df2.columns and "nota" in df2.columns:
                st.line_chart(df2.set_index("fecha")[["nota"]])
        else: 
            st.info("Sense registres de test per temes.")
            
    with t3:
        st.subheader("📈 Estat i Maduració del Temari")
        
        # Càlcul del progrés del pla d'estudi basat en els checkboxes
        progreso = st.session_state.get("progreso_estudio", {})
        plan = st.session_state.get("plan_estudio_json", [])
        
        total_tareas = 0
        tareas_completadas = 0
        
        for sem in plan:
            for d_info in sem.get('dias', []):
                dia_nombre = d_info.get('dia', '')
                for t_idx, _ in enumerate(d_info.get('tareas', [])):
                    total_tareas += 1
                    key_check = f"chk_sem_{sem.get('semana')}_{dia_nombre}_{t_idx}"
                    if progreso.get(key_check, False):
                        tareas_completadas += 1
                        
        if total_tareas > 0:
            porcentaje_completado = (tareas_completadas / total_tareas) * 100
            voltas_completas = tareas_completadas // total_tareas
            tareas_vuelta_actual = tareas_completadas % total_tareas
            porcentaje_vuelta_actual = (tareas_vuelta_actual / total_tareas) * 100
        else:
            porcentaje_completado = 0
            voltas_completas = 0
            porcentaje_vuelta_actual = 0

        # Mètriques principals
        col_m1, col_m2, col_m3 = st.columns(3)
        with col_m1:
            st.metric("Temari Completat (Total)", f"{porcentaje_completado:.1f}%")
        with col_m2:
            st.metric("Voltes completes al temari", f"{voltas_completas}")
        with col_m3:
            st.metric("Progrés de la volta actual", f"{porcentaje_vuelta_actual:.1f}%")
            
        st.progress(min(porcentaje_vuelta_actual / 100.0, 1.0))
        st.markdown("---")
        
        # Relació amb els resultats dels test per temes (Punts febles / forts)
        st.subheader("🔍 Anàlisi de Punts Febles (Test per Temes)")
        historico_tests = st.session_state.get("historico_test_temas", [])
        
        if historico_tests:
            df_tests = pd.DataFrame(historico_tests)
            # Suposem que el registre guarda el tema a una columna anomenada 'tema' o 'nombre_tema' o similar
            # Busquem quina columna pot contenir el tema
            col_tema_candidatas = [c for c in df_tests.columns if 'tema' in c.lower()]
            col_nota_candidatas = [c for c in df_tests.columns if 'nota' in c.lower() or 'puntuacion' in c.lower()]
            
            if col_tema_candidatas and col_nota_candidatas:
                c_tema = col_tema_candidatas[0]
                c_nota = col_nota_candidatas[0]
                
                # Agrupem per tema per calcular la mitjana de cadascun
                df_resumen = df_tests.groupby(c_tema)[c_nota].mean().reset_index()
                df_resumen = df_resumen.sort_values(by=c_nota, ascending=True) # Del pitjor al millor
                
                col_f1, col_f2 = st.columns(2)
                with col_f1:
                    st.markdown("⚠️ **Temes que portes pitjor (Menor nota mitjana):**")
                    peores = df_resumen.head(5)
                    for _, row in peores.iterrows():
                        st.write(f"- **{row[c_tema]}**: {row[c_nota]:.2f}")
                with col_f2:
                    st.markdown("🏆 **Temes que domines millor (Major nota mitjana):**")
                    mejores = df_resumen.tail(5).sort_values(by=c_nota, ascending=False)
                    for _, row in mejores.iterrows():
                        st.write(f"- **{row[c_tema]}**: {row[c_nota]:.2f}")
            else:
                st.info("No s'han trobat columnes de 'tema' o 'nota' identificables a l'historial de testos per temes per fer l'anàlisi detallat.")
        else:
            st.info("Encara no hi ha suficients registres a 'Test per Temes' per calcular els teus punts febles. Fes algun test per veure l'anàlisi aquí!")


# ------------------------------------------------------------------------------
# 11. TUTOR IA 24/7 (Amb opció de xat per veu corregida)
# ------------------------------------------------------------------------------
elif opcion == "💬 Tutor IA 24/7":
    st.header("💬 Tutor IA 24/7")
    st.write("Resol dubtes al moment sobre qualsevol tema del temari de Bombers de la Generalitat.")
    
    docs_tutor = list(st.session_state.textos_pdfs_temario.keys())
    tema_contexto = st.selectbox("Selecciona un tema de referència (opcional):", ["Cap (General)"] + docs_tutor)
    
    if "mensajes_tutor" not in st.session_state:
        st.session_state.mensajes_tutor = []

    for msg in st.session_state.mensajes_tutor:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    pregunta_usuario = st.chat_input("Escriu el teu dubte sobre l'oposició...")

    st.markdown("---")
    st.markdown("🎙️ **O pots parlar directament amb el tutor:**")
    audio_file = st.audio_input("Fes clic al micròfon per gravar la teva consulta:")

    if audio_file is not None and audio_file != st.session_state.get("ultimo_audio_procesado"):
        with st.spinner("Pujant i processant l'àudio amb la IA..."):
            try:
                st.session_state["ultimo_audio_procesado"] = audio_file
                
                # Guardar temporalmente el archivo de audio en disco para subirlo a la API
                temp_audio_path = "temp_audio_consulta.wav"
                with open(temp_audio_path, "wb") as f:
                    f.write(audio_file.getbuffer())
                
                # Subir el archivo usando el gestor de archivos de la API de Google GenAI
                audio_ref = client.files.upload(file=temp_audio_path)
                
                prompt_audio = [
                    audio_ref,
                    "Transcriu fidelment el que diu l'alumne en aquest àudio i actua com a tutor expert de Bombers de la Generalitat per respondre-li tècnicament en català."
                ]
                
                resp_audio = client.models.generate_content(model=MODELO_IA, contents=prompt_audio)
                
                # Borrar el archivo temporal local
                if os.path.exists(temp_audio_path):
                    os.remove(temp_audio_path)
                
                if resp_audio:
                    respuesta_texto = resp_audio.text
                    st.session_state.mensajes_tutor.append({"role": "user", "content": "🎤 *(Missatge de veu enviat)*"})
                    st.session_state.mensajes_tutor.append({"role": "assistant", "content": respuesta_texto})
                    st.rerun()
            except Exception as e:
                st.error(f"Error al processar l'àudio amb l'API: {e}")

    if pregunta_usuario:
        st.session_state.mensajes_tutor.append({"role": "user", "content": pregunta_usuario})
        with st.chat_message("user"):
            st.markdown(pregunta_usuario)

        with st.chat_message("assistant"):
            with st.spinner("Pensant la resposta..."):
                contexto_extra = ""
                if tema_contexto != "Cap (General)" and tema_contexto in st.session_state.textos_pdfs_temario:
                    contexto_extra = f"\n\nContext del document de referència '{tema_contexto}':\n{st.session_state.textos_pdfs_temario[tema_contexto][:8000]}"
                
                prompt_tutor = (
                    f"Actua com un tutor expert i professor acadèmic per a les oposicions de Bombers de la Generalitat de Catalunya. "
                    f"Resol el següent dubte de l'opositor de manera clara, rigorosa i tècnica, basant-te en la normativa vigent i el temari oficial. "
                    f"RESPON SEMPRE EN CATALÀ.\n"
                    f"{contexto_extra}\n\n"
                    f"Dubte de l'alumne: {pregunta_usuario}"
                )
                
                resp = generar_con_reintento(prompt_tutor)
                if resp:
                    respuesta_texto = resp.text
                    st.markdown(respuesta_texto)
                    st.session_state.mensajes_tutor.append({"role": "assistant", "content": respuesta_texto})
                else:
                    error_msg = "Disculpa, hi ha hagut un error a l'hora de generar la resposta. Torna-ho a provar."
                    st.error(error_msg)
                    st.session_state.mensajes_tutor.append({"role": "assistant", "content": error_msg})
