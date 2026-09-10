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

# Configuración inicial de la página
st.set_page_config(
    page_title="Gestor Integral Bombers & Fitness",
    page_icon="🚒",
    layout="wide"
)

# ==============================================================================
# CONFIGURACIÓN DE SUPABASE (NUBE)
# ==============================================================================
SUPABASE_URL = "https://gxrdfdckjfixuugupygg.supabase.co"
SUPABASE_KEY = "PEGA_AQUI_TU_CLAVE_ANON_COMPLETA"

@st.cache_resource
def init_supabase():
    try:
        return create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception:
        return None

supabase = init_supabase()

# Carga segura de la API Key de Gemini
api_key = None
try:
    if "GEMINI_API_KEY" in st.secrets:
        api_key = st.secrets["GEMINI_API_KEY"]
except Exception:
    pass

if not api_key:
    api_key = os.environ.get("GEMINI_API_KEY")

if not api_key:
    st.sidebar.warning("⚠️ No se encontró la API Key de Gemini en el sistema.")
    api_key_input = st.sidebar.text_input("Introduce tu Gemini API Key:", type="password")
    if api_key_input:
        api_key = api_key_input

client = genai.Client(api_key=api_key) if api_key else None
MODELO_IA = "gemini-3.6-flash"

# Archivos locales de respaldo
CSV_SIMULACROS = "historial_simulacros.csv"
CSV_TEST_TEMAS = "historial_test_temas.csv"
CSV_FALLOS_REPASO = "banco_fallos_repaso.csv"
CSV_FLASHCARDS = "flashcards_guardadas.csv"

# Rutinas y catálogo masivo de ejercicios para Bombers y Fuerza
RUTINAS_POR_DEFECTO = {
    "Push (Empuje)": ["Press de banca plano con barra", "Press de banca inclinado con barra", "Press militar con barra", "Fondos en paralelas (Dips)", "Elevaciones laterales con mancuernas", "Press francés con barra Z", "Extensiones de tríceps en polea"],
    "Pull (Tirón)": ["Dominadas pronas lastradas", "Remo con barra", "Jalón al pecho en polea", "Remo en polea baja (Tirón horizontal)", "Face pull", "Curl de bíceps con barra", "Curl con mancuernas tipo martillo"],
    "Pierna (Tren Inferior)": ["Sentadilla trasera con barra", "Sentadilla frontal", "Prensa de piernas 45º", "Peso muerto rumano", "Zancadas con mancuernas (Lunges)", "Curl de isquios en máquina", "Elevación de talones en máquina (Gemelos)"],
    "Upper (Tren Superior)": ["Press de banca plano con barra", "Dominadas libres", "Press militar con mancuernas", "Remo con mancuerna a una mano", "Dominadas lastradas supinas"],
    "Lower (Fuerza / Salto / Opos)": ["Sentadilla trasera con barra", "Salto vertical con contramovimiento", "Cargadas de potencia (Power Clean)", "Prensa de piernas 45º", "Plancha abdominal isométrica"]
}

LISTA_EJERCICIOS_HEAVY = [
    # Pecho (Pesos Libres y Máquinas)
    "Press de banca plano con barra", "Press de banca plano con mancuernas",
    "Press de banca inclinado con barra", "Press de banca inclinado con mancuernas",
    "Press de banca inclinado en máquina Smith", "Press de banca plano en máquina Smith",
    "Press de banca declinado en máquina Smith", "Press de pecho sentado en máquina (Convergent Chest Press)",
    "Press de banca declinado con barra", "Aperturas en máquina (Contractor / Pec Deck)",
    "Aperturas planas con mancuernas", "Aperturas inclinadas con mancuernas",
    "Cruce de poleas (Chest Flyes)", "Fondos en paralelas (Dips)",
    
    # Espalda / Dorsales (Pesos Libres, Poleas y Máquinas)
    "Dominadas pronas lastradas", "Dominadas libres", "Dominadas supinas (chin-ups)",
    "Dominadas neutras", "Remo con barra", "Remo con mancuerna a una mano",
    "Remo en polea baja (Tirón horizontal)", "Remo en máquina convergente (Chest-supported Row)",
    "Remo sentado en máquina agarre neutro", "Jalón al pecho agarre prono",
    "Jalón al pecho agarre supino", "Jalón al pecho agarre neutro",
    "Jalón al pecho en máquina convergente", "Pulldown en polea alta con brazos estirados",
    "Remo en máquina T", "Remo Pendlay", "Pullover en polea alta con barra o cuerda",
    
    # Hombros (Pesos Libres y Máquinas)
    "Press militar con barra (Standing Overhead Press)", "Press militar sentado con mancuernas",
    "Press militar en máquina sentado (Shoulder Press Machine)", "Press militar en máquina Smith",
    "Press Arnold", "Elevaciones laterales con mancuernas", "Elevaciones laterales en polea",
    "Elevaciones laterales en máquina", "Elevaciones frontales con disco o mancuerna",
    "Pájaros (Elevaciones posteriores con mancuernas)", "Pájaros en máquina contractora (Reverse Pec Deck)",
    "Face pull", "Encogimientos de hombros con barra o mancuernas (Trapecios)",
    "Encogimientos de hombros en máquina Smith",
    
    # Bíceps (Pesos Libres, Poleas y Máquinas)
    "Curl de bíceps con barra", "Curl de bíceps con barra Z",
    "Curl con mancuernas alterno", "Curl con mancuernas tipo martillo",
    "Curl en banco Scott con barra Z", "Curl en banco Scott en máquina",
    "Curl en polea baja con barra", "Curl en polea baja con cuerda",
    "Curl concentrado", "Curl de bíceps en máquina sentado",
    
    # Tríceps (Pesos Libres, Poleas y Máquinas)
    "Press francés con barra Z", "Extensiones de tríceps en polea alta (Cuerda)",
    "Extensiones de tríceps en polea alta (Barra recta)", "Press de banca con agarre cerrado",
    "Extensiones de tríceps en máquina sentado (Triceps Extension Machine)",
    "Extensiones de tríceps por detrás de la cabeza con mancuerna",
    "Extensiones de tríceps tras nuca en polea baja", "Patada de tríceps con mancuerna",
    
    # Piernas - Cuádriceps, Glúteos e Isquios (Pesos Libres y Máquinas)
    "Sentadilla trasera con barra (Back Squat)", "Sentadilla frontal con barra (Front Squat)",
    "Sentadilla en máquina Smith", "Sentadilla búlgara con mancuernas",
    "Prensa de piernas 45º", "Prensa horizontal", "Extensiones de cuádriceps en máquina",
    "Sentadilla Sissy en máquina", "Peso muerto convencional", "Peso muerto rumano",
    "Peso muerto sumo", "Curl de isquios tumbado en máquina", "Curl de isquios sentado en máquina",
    "Curl de isquios de pie en máquina", "Hip thrust con barra", "Hip thrust en máquina",
    "Patada de glúteos en polea baja", "Abductor de cadera en máquina", "Aductor de cadera en máquina",
    "Zancadas con mancuernas (Lunges)", "Elevación de talones de pie en máquina (Gemelos)",
    "Elevación de talones sentado en máquina (Gemelos)", "Elevaciones de talones en prensa 45º",
    
    # Core / Abdominales / Funcionales Oposición
    "Plancha abdominal isométrica", "Elevación de piernas colgado en barra",
    "Elevación de rodillas en máquina de paralelas/abdominales", "Abdominales en V (V-Ups)",
    "Rueda abdominal (Ab Wheel Rollout)", "Giros rusos con peso (Russian Twists)",
    "Crunch abdominal en máquina", "Salto vertical con contramovimiento",
    "Cargadas de potencia (Power Clean)", "Clean & Jerk", "Course Navette (Simulación)"
]

def limpiar_nombre_archivo(nombre):
    nfkd_form = unicodedata.normalize('NFKD', nombre)
    solo_ascii = "".join([c for c in nfkd_form if not unicodedata.combining(c)])
    limpio = re.sub(r'[^a-zA-Z0-9_\.-]', '_', solo_ascii)
    return limpio

def generar_con_reintento(prompt_texto, intentos=4, espera=3):
    if client is None:
        return None
    global MODELO_IA
    for intento in range(intentos):
        try:
            resp = client.models.generate_content(model=MODELO_IA, contents=prompt_texto)
            return resp
        except APIError as e:
            if "503" in str(e) or "UNAVAILABLE" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                if intento < intentos - 1:
                    time.sleep(espera)
                    continue
            raise e
        except Exception as e:
            raise e
    return None

def obtener_texto_acumulado():
    if "textos_pdfs_temario" in st.session_state and st.session_state.textos_pdfs_temario:
        return "\n".join(st.session_state.textos_pdfs_temario.values())
    return ""

def obtener_texto_acumulado_oficiales():
    if "textos_pdfs_oficiales" in st.session_state and st.session_state.textos_pdfs_oficiales:
        return "\n".join(st.session_state.textos_pdfs_oficiales.values())
    return ""

def verificar_cliente():
    if client is None:
        st.error("⚠️ Por favor, introduce tu Gemini API Key en la barra lateral.")
        return False
    return True

# ------------------------------------------------------------------------------
# SINCRONIZACIÓN Y PERSISTENCIA AUTOMÁTICA CON SUPABASE NUBE
# ------------------------------------------------------------------------------
def sincronizar_desde_supabase():
    if not supabase:
        return

    # 1. Sincronizar PDFs de Temario
    if "textos_pdfs_temario" not in st.session_state:
        st.session_state.textos_pdfs_temario = {}
    
    try:
        archivos_nube = supabase.storage.from_("temarios").list("temarios")
        for archivo in archivos_nube:
            nombre = archivo.get("name")
            if nombre and nombre.endswith(".pdf") and nombre not in st.session_state.textos_pdfs_temario:
                res_bytes = supabase.storage.from_("temarios").download(f"temarios/{nombre}")
                if res_bytes:
                    lector = pypdf.PdfReader(io.BytesIO(res_bytes))
                    texto = "".join([p.extract_text() + "\n" for p in lector.pages if p.extract_text()])
                    if texto.strip():
                        st.session_state.textos_pdfs_temario[nombre] = texto
    except Exception:
        pass

    # 2. Sincronizar PDFs de Exámenes Oficiales
    if "textos_pdfs_oficiales" not in st.session_state:
        st.session_state.textos_pdfs_oficiales = {}
        
    try:
        archivos_of = supabase.storage.from_("temarios").list("oficiales")
        for archivo in archivos_of:
            nombre = archivo.get("name")
            if nombre and nombre.endswith(".pdf") and nombre not in st.session_state.textos_pdfs_oficiales:
                res_bytes = supabase.storage.from_("temarios").download(f"oficiales/{nombre}")
                if res_bytes:
                    lector = pypdf.PdfReader(io.BytesIO(res_bytes))
                    texto = "".join([p.extract_text() + "\n" for p in lector.pages if p.extract_text()])
                    if texto.strip():
                        st.session_state.textos_pdfs_oficiales[nombre] = texto
    except Exception:
        pass

    # 3. Sincronizar Rutinas y Marcas de Entrenamiento
    if "mis_rutinas" not in st.session_state:
        st.session_state.mis_rutinas = {}
        try:
            res_bytes = supabase.storage.from_("temarios").download("datos/mis_rutinas.json")
            if res_bytes:
                st.session_state.mis_rutinas = json.loads(res_bytes.decode("utf-8"))
        except Exception:
            pass
            
        if not st.session_state.mis_rutinas:
            st.session_state.mis_rutinas = RUTINAS_POR_DEFECTO
            guardar_rutinas_nube()

    if "historial_marcas" not in st.session_state:
        st.session_state.historial_marcas = []
        try:
            res_bytes = supabase.storage.from_("temarios").download("datos/historial_marcas.json")
            if res_bytes:
                st.session_state.historial_marcas = json.loads(res_bytes.decode("utf-8"))
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
            pass

def guardar_marcas_nube():
    if supabase and "historial_marcas" in st.session_state:
        try:
            json_bytes = json.dumps(st.session_state.historial_marcas).encode("utf-8")
            supabase.storage.from_("temarios").upload(
                path="datos/historial_marcas.json",
                file=json_bytes,
                file_options={"content-type": "application/json", "upsert": "true"}
            )
        except Exception:
            pass

def inicializar_estados():
    sincronizar_desde_supabase()
    
    if "historico" not in st.session_state:
        st.session_state.historico = pd.read_csv(CSV_SIMULACROS).to_dict("records") if os.path.exists(CSV_SIMULACROS) else []
    if "historico_test_temas" not in st.session_state:
        st.session_state.historico_test_temas = pd.read_csv(CSV_TEST_TEMAS).to_dict("records") if os.path.exists(CSV_TEST_TEMAS) else []
    if "banco_fallos" not in st.session_state:
        st.session_state.banco_fallos = pd.read_csv(CSV_FALLOS_REPASO).to_dict("records") if os.path.exists(CSV_FALLOS_REPASO) else []
    if "flashcards" not in st.session_state:
        st.session_state.flashcards = pd.read_csv(CSV_FLASHCARDS).to_dict("records") if os.path.exists(CSV_FLASHCARDS) else []

inicializar_estados()

def guardar_simulacros_disco():
    if st.session_state.historico:
        pd.DataFrame(st.session_state.historico).to_csv(CSV_SIMULACROS, index=False)

def guardar_test_temas_disco():
    if st.session_state.historico_test_temas:
        pd.DataFrame(st.session_state.historico_test_temas).to_csv(CSV_TEST_TEMAS, index=False)

def guardar_banco_fallos_disco():
    if st.session_state.banco_fallos:
        pd.DataFrame(st.session_state.banco_fallos).to_csv(CSV_FALLOS_REPASO, index=False)

def guardar_flashcards_disco():
    if st.session_state.flashcards:
        pd.DataFrame(st.session_state.flashcards).to_csv(CSV_FLASHCARDS, index=False)

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
                "explicacion": explicacion if explicacion else "Respuesta oficial validada."
            })
    return preguntas_limpias

def renderizar_test_interactivo(texto_ia, clave_sesion, nombre_tema="General"):
    if f"parsed_{clave_sesion}" not in st.session_state:
        st.session_state[f"parsed_{clave_sesion}"] = parsear_test_a_objetos(texto_ia)
    
    preguntas = st.session_state[f"parsed_{clave_sesion}"]
    if not preguntas:
        st.markdown(texto_ia)
        return

    st.info("💡 **Modo Interactivo:** Selecciona una opción en cada pregunta.")
    respuestas_usuario = {}
    total_preguntas = len(preguntas)
    
    for idx, p in enumerate(preguntas):
        st.markdown(f"**Pregunta {idx + 1}:** {p['enunciado']}")
        opciones_texto = [f"{p['letras'][i]}) {op}" for i, op in enumerate(p['opciones'])]
        seleccion = st.radio(f"Elige opción (P{idx+1}):", options=opciones_texto, key=f"test_q_{clave_sesion}_{idx}", index=None)
        if seleccion:
            letra_elegida = seleccion[0]
            idx_elegido = p['letras'].index(letra_elegida) if letra_elegida in p['letras'] else -1
            respuestas_usuario[idx] = idx_elegido
            if idx_elegido == p['correcta']: st.success("✅ ¡Correcto!")
            else: st.error(f"❌ Incorrecto. La buena era la **{p['letras'][p['correcta']]}) {p['opciones'][p['correcta']]}**")
            if p['explicacion']: st.markdown(f"> 📖 *{p['explicacion']}*")
        st.markdown("---")

    if st.button("💾 Finalizar y Guardar Resultados", key=f"btn_guardar_{clave_sesion}"):
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
        st.success(f"🎉 ¡Guardado! Nota: {nota_calc}/10")

# ------------------------------------------------------------------------------
# PANEL DE NAVEGACIÓN LATERAL
# ------------------------------------------------------------------------------
st.sidebar.title("🚒 Panel de Navegación")
opcion = st.sidebar.radio(
    "Selecciona un módulo:",
    [
        "📚 Biblioteca del Temario",
        "📝 Simulacro de Examen",
        "🎯 Test por Temas",
        "💡 Preguntas de Repaso",
        "🏋️‍♂️ Preparación Física",
        "📅 Plan de Estudio Personalizado",
        "🎴 Flashcards de Memorización",
        "📄 Esquemas y Tablas Técnicas",
        "🏛️ Preguntas Exámenes Oficiales",
        "📊 Estadísticas y Progresos",
        "💬 Tutor IA 24/7"
    ]
)

# ------------------------------------------------------------------------------
# 1. BIBLIOTECA DEL TEMARIO
# ------------------------------------------------------------------------------
if opcion == "📚 Biblioteca del Temario":
    st.header("📚 Biblioteca del Temario Oficial (Nube)")
    st.write("Sube tus PDFs. Los nombres se adaptarán automáticamente para guardarse sin errores en Supabase.")

    archivos_subidos = st.file_uploader("Sube archivos PDF:", type=["pdf"], accept_multiple_files=True, key="up_temario")

    if archivos_subidos and supabase:
        for archivo in archivos_subidos:
            nombre_limpio = limpiar_nombre_archivo(archivo.name)
            if nombre_limpio not in st.session_state.textos_pdfs_temario:
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
                        st.success(f"📄 '{nombre_limpio}' subido y guardado en la nube con éxito.")
                except Exception as e:
                    st.error(f"Error al subir {archivo.name}: {e}")

    if st.session_state.textos_pdfs_temario:
        st.subheader("📁 Documentos en la Nube")
        for doc in list(st.session_state.textos_pdfs_temario.keys()):
            c1, c2 = st.columns([0.8, 0.2])
            with c1: st.write(f"• **{doc}**")
            with c2:
                if st.button("Eliminar", key=f"del_doc_{doc}"):
                    del st.session_state.textos_pdfs_temario[doc]
                    try: supabase.storage.from_("temarios").remove([f"temarios/{doc}"])
                    except Exception: pass
                    st.rerun()

# ------------------------------------------------------------------------------
# 2. SIMULACRO DE EXAMEN
# ------------------------------------------------------------------------------
elif opcion == "📝 Simulacro de Examen":
    st.header("📝 Simulacro de Examen Oficial")
    c1, c2 = st.columns(2)
    with c1: 
        num_preguntas = st.slider("Número de preguntas:", 10, 120, 50, 10)
    with c2: 
        tiempo_limite = st.slider("Tiempo límite (minutos):", 15, 180, 90, 15)

    if st.button("🚀 Generar Simulacro"):
        if verificar_cliente():
            txt_ref = obtener_texto_acumulado()
            prompt = (
                f"Genera un examen tipo test oficial de {num_preguntas} preguntas con 4 opciones (A, B, C, D), "
                f"respuesta correcta y explicación. "
                f"Las preguntas deben estar generadas estrictamente sobre el temario de los PDF subidos a la biblioteca del temario:\n\n"
                f"{txt_ref[:15000]}"
            )
            with st.spinner("Generando simulacro con el temario de la biblioteca..."):
                resp = generar_con_reintento(prompt)
                if resp: 
                    st.session_state.simulacro_activo = resp.text

    if "simulacro_activo" in st.session_state:
        st.markdown("---")
        renderizar_test_interactivo(st.session_state.simulacro_activo, "simulacro_gen", nombre_tema="Simulacro Oficial")

# ------------------------------------------------------------------------------
# 3. TEST POR TEMAS
# ------------------------------------------------------------------------------
elif opcion == "🎯 Test por Temas":
    st.header("🎯 Test Específico por Temas")
    docs = list(st.session_state.textos_pdfs_temario.keys())
    if not docs: st.warning("Sube PDFs en la Biblioteca.")
    else:
        ts = st.selectbox("Tema:", docs)
        cant = st.slider("Preguntas:", 5, 40, 15, 5)
        if st.button("🚀 Generar Test de Tema"):
            if verificar_cliente():
                prompt = f"Genera un test técnico de {cant} preguntas con formato Pregunta, A, B, C, D, respuesta correcta y explicación basado en: {st.session_state.textos_pdfs_temario[ts][:12000]}"
                with st.spinner("Generando..."):
                    resp = generar_con_reintento(prompt)
                    if resp: st.session_state.test_tema_activo = resp.text
        if "test_tema_activo" in st.session_state:
            renderizar_test_interactivo(st.session_state.test_tema_activo, "test_tema", nombre_tema=ts)

# ------------------------------------------------------------------------------
# 4. PREGUNTAS DE REPASO
# ------------------------------------------------------------------------------
elif opcion == "💡 Preguntas de Repaso":
    st.header("💡 Preguntas de Repaso Rápido")
    modo = st.radio("Modo:", ["🎯 Repaso de mis Fallos", "🎲 Repaso Aleatorio"])
    if "Fallos" in modo:
        if not st.session_state.banco_fallos: st.info("No hay fallos registrados aún.")
        else:
            if st.button("🚀 Iniciar Repaso de Fallos"):
                banco_txt = "".join([f"\nPregunta: {f['enunciado']}\nCorrecta: {f['correcta']}\n" for f in st.session_state.banco_fallos])
                resp = generar_con_reintento(f"Crea un test con estas preguntas que fallé anteriormente: {banco_txt}")
                if resp: st.session_state.repaso_fallos_activo = resp.text
            if "repaso_fallos_activo" in st.session_state:
                renderizar_test_interactivo(st.session_state.repaso_fallos_activo, "repaso_fallos", nombre_tema="Repaso de Fallos")
    else:
        if st.button("🚀 Generar Repaso Aleatorio"):
            resp = generar_con_reintento("Genera 10 preguntas de repaso general tipo test para Bombers.")
            if resp: st.session_state.repaso_aleatorio = resp.text
        if "repaso_aleatorio" in st.session_state:
            renderizar_test_interactivo(st.session_state.repaso_aleatorio, "repaso_rand", nombre_tema="Repaso Aleatorio")

# ------------------------------------------------------------------------------
# 5. PREPARACIÓN FÍSICA
# ------------------------------------------------------------------------------
elif opcion == "🏋️‍♂️ Preparación Física":
    st.header("🏋️‍♂️ Preparación Física & Progreso")
    t1, t2, t3 = st.tabs(["🏋️‍♂️ Entrenar Rutina", "➕ Crear / Gestionar Rutinas", "📈 Gráficas de Progreso"])
    
    with t1:
        if not st.session_state.mis_rutinas:
            st.info("No tienes ninguna rutina creada todavía. Ve a la pestaña 'Crear / Gestionar Rutinas' para añadir una.")
        else:
            rutina_sel = st.selectbox("Selecciona tu rutina de hoy:", list(st.session_state.mis_rutinas.keys()))
            fecha_entreno = st.date_input("Fecha del entrenamiento:", value=datetime.date.today())
            
            st.markdown(f"### Ejercicios de: {rutina_sel}")
            ejercicios_rutina = st.session_state.mis_rutinas[rutina_sel]
            
            nuevos_registros = []
            for ej in ejercicios_rutina:
                st.markdown(f"#### 🔹 {ej}")
                num_series = st.number_input(f"Número de series para {ej}:", 1, 6, 3, key=f"ns_{ej}")
                for s in range(1, int(num_series) + 1):
                    col_s1, col_s2, col_s3 = st.columns(3)
                    with col_s1: st.text(f"Serie {s}")
                    with col_s2: peso_s = st.number_input(f"Peso (kg) - {ej} S{s}", 0.0, step=0.5, key=f"peso_{ej}_{s}")
                    with col_s3: reps_s = st.number_input(f"Reps - {ej} S{s}", 1, 100, 10, key=f"reps_{ej}_{s}")
                    
                    nuevos_registros.append({
                        "Fecha": str(fecha_entreno),
                        "Rutina": rutina_sel,
                        "Ejercicio": ej,
                        "Serie": s,
                        "Peso (kg)": peso_s,
                        "Reps": reps_s
                    })
            
            if st.button("💾 Guardar Entrenamiento y Actualizar Progreso"):
                st.session_state.historial_marcas.extend(nuevos_registros)
                guardar_marcas_nube()
                st.success("🎉 ¡Entrenamiento guardado con éxito en la nube!")

    with t2:
        st.subheader("Crea tus propias rutinas de entrenamiento")
        nombre_nueva_rutina = st.text_input("Nombre de la rutina (ej: Torso - Fuerza, Pierna Bombero):")
        lista_ejercicios = st.multiselect(
            "Selecciona o añade los ejercicios que componen esta rutina (Catálogo Completo):",
            LISTA_EJERCICIOS_HEAVY,
            default=["Press de banca plano con barra", "Dominadas pronas lastradas", "Sentadilla trasera con barra (Back Squat)"]
        )
        
        if st.button("➕ Guardar Nueva Rutina"):
            if nombre_nueva_rutina and lista_ejercicios:
                st.session_state.mis_rutinas[nombre_nueva_rutina] = lista_ejercicios
                guardar_rutinas_nube()
                st.success(f"¡Rutina '{nombre_nueva_rutina}' guardada correctamente en la nube!")
                st.rerun()
            else:
                st.warning("Introduce un nombre y selecciona al menos un ejercicio.")

        if st.session_state.mis_rutinas:
            st.markdown("---")
            st.markdown("### Tus Rutinas Actuales:")
            for r_nombre, r_ejs in list(st.session_state.mis_rutinas.items()):
                c_r1, c_r2 = st.columns([0.8, 0.2])
                with c_r1: st.write(f"• **{r_nombre}**: {', '.join(r_ejs)}")
                with c_r2:
                    if st.button("Borrar", key=f"del_rut_{r_nombre}"):
                        del st.session_state.mis_rutinas[r_nombre]
                        guardar_rutinas_nube()
                        st.rerun()

    with t3:
        if st.session_state.historial_marcas:
            df_marcas = pd.DataFrame(st.session_state.historial_marcas)
            ejercicio_grafico = st.selectbox("Selecciona ejercicio para ver evolución de peso:", df_marcas["Ejercicio"].unique())
            df_filtrado = df_marcas[df_marcas["Ejercicio"] == ejercicio_grafico]
            st.line_chart(df_filtrado.set_index("Fecha")[["Peso (kg)"]])
            st.dataframe(df_filtrado, use_container_width=True)
        else:
            st.info("Todavía no hay registros de entrenamientos guardados.")

# ------------------------------------------------------------------------------
# 6. PLAN DE ESTUDIO
# ------------------------------------------------------------------------------
elif opcion == "📅 Plan de Estudio Personalizado":
    st.header("📅 Planificador Estratégico de Estudio")
    st.write("Diseña tu planificación teórica a largo plazo basada en los PDFs de tu biblioteca + 7 temas de legislación.")
    
    col_ps1, col_ps2 = st.columns(2)
    with col_ps1:
        hs = st.slider("Horas disponibles a la semana:", 5, 50, 20, 5)
    with col_ps2:
        dias_estudio = st.multiselect(
            "Días de estudio semanales:",
            ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"],
            default=["Lunes", "Martes", "Miércoles", "Jueves", "Viernes"]
        )

    if st.button("🚀 Generar Plan Estratégico"):
        if verificar_cliente():
            if not dias_estudio:
                st.warning("Selecciona al menos un día de estudio en la semana.")
            else:
                txt_ref = obtener_texto_acumulado()
                prompt = (
                    f"Actúa como un planificador experto para oposiciones de Bombers de la Generalitat. "
                    f"Crea un plan de estudio teórico a largo plazo (distribuido en varias semanas hasta cubrir todo el temario). "
                    f"Dispone de {hs} horas semanales distribuidas exclusivamente en los siguientes días seleccionados: {', '.join(dias_estudio)}. "
                    f"El plan debe cubrir estrictamente el contenido de los PDFs subidos a la biblioteca y contemplar además 7 temas adicionales de legislación. "
                    f"NO incluyas preparación física ni entrenamientos de ningún tipo, este plan es 100% de estudio teórico. "
                    f"Devuelve el resultado en formato JSON puro con una lista de objetos por semana. Cada objeto semana debe tener las claves: "
                    f"'semana' (número entero), 'objetivo' (string resumido del objetivo semanal) y 'dias' (una lista de objetos, donde cada objeto tiene 'dia' (string con el nombre del día) y 'tareas' (lista de strings con los temas/tareas a realizar)).\n\n"
                    f"Temario disponible en biblioteca:\n{txt_ref[:12000]}"
                )
                with st.spinner("Generando plan de estudio estratégico..."):
                    resp = generar_con_reintento(prompt)
                    if resp:
                        try:
                            clean_json = resp.text.strip().replace("```json", "").replace("```", "")
                            st.session_state.plan_estudio_json = json.loads(clean_json)
                            st.session_state.plan_estudio_texto_raw = ""
                            st.success("¡Plan de estudio estratégico generado con éxito!")
                        except Exception:
                            st.session_state.plan_estudio_json = None
                            st.session_state.plan_estudio_texto_raw = resp.text
                            st.success("¡Plan generado con éxito!")

    if "plan_estudio_json" in st.session_state and st.session_state.plan_estudio_json:
        st.markdown("---")
        st.subheader("📋 Tu Plan de Estudio Interactivo")
        st.write("Marca las tareas a medida que las vayas completando para llevar un seguimiento de tu progreso:")
        
        if "progreso_estudio" not in st.session_state:
            st.session_state.progreso_estudio = {}

        for sem in st.session_state.plan_estudio_json:
            with st.expander(f"Semana {sem.get('semana')}: {sem.get('objetivo', '')}", expanded=False):
                for d_info in sem.get('dias', []):
                    dia_nombre = d_info.get('dia', '')
                    st.markdown(f"**📅 {dia_nombre}**")
                    for t_idx, tarea in enumerate(d_info.get('tareas', [])):
                        key_check = f"chk_sem_{sem.get('semana')}_{dia_nombre}_{t_idx}"
                        completado = st.checkbox(tarea, key=key_check, value=st.session_state.progreso_estudio.get(key_check, False))
                        st.session_state.progreso_estudio[key_check] = completado
            st.markdown("")

    elif "plan_estudio_texto_raw" in st.session_state and st.session_state.plan_estudio_texto_raw:
        st.markdown("---")
        st.markdown(st.session_state.plan_estudio_texto_raw)
# ------------------------------------------------------------------------------
# 7. FLASHCARDS
# ------------------------------------------------------------------------------
elif opcion == "🎴 Flashcards de Memorización":
    st.header("🎴 Tarjetas de Memorización")
    docs = list(st.session_state.textos_pdfs_temario.keys())
    t1, t2 = st.tabs(["➕ Generar Flashcards", "🎴 Ver Flashcards Guardadas"])
    with t1:
        if not docs: st.warning("Sube PDFs primero.")
        else:
            ts = st.selectbox("Tema base:", docs)
            nf = st.slider("Número de flashcards:", 3, 15, 8)
            if st.button("Generar"):
                resp = generar_con_reintento(f"Genera {nf} flashcards (anverso y reverso concisos) basadas en: {st.session_state.textos_pdfs_temario[ts][:10000]}. Devuelve un JSON puro en formato de lista de diccionarios con claves 'anverso' y 'reverso'.")
                if resp:
                    try:
                        clean = resp.text.strip().replace("```json", "").replace("```", "")
                        cards = json.loads(clean)
                        for c in cards:
                            c["tema"] = ts
                            if not any(x.get("anverso") == c.get("anverso") for x in st.session_state.flashcards):
                                st.session_state.flashcards.append(c)
                        guardar_flashcards_disco()
                        st.success("¡Flashcards guardadas!")
                    except Exception as e: st.error(f"Error procesando JSON: {e}")
    with t2:
        if not st.session_state.flashcards: st.info("No hay flashcards.")
        else:
            for fc in st.session_state.flashcards:
                with st.expander(f"[{fc.get('tema')}] {fc.get('anverso')}"):
                    st.write(fc.get('reverso'))

# ------------------------------------------------------------------------------
# 8. ESQUEMAS Y TABLAS TÉCNICAS
# ------------------------------------------------------------------------------
elif opcion == "📄 Esquemas y Tablas Técnicas":
    st.header("📄 Generador de Material Sintético")
    docs = list(st.session_state.textos_pdfs_temario.keys())
    if not docs: st.warning("Sube PDFs.")
    else:
        ts = st.selectbox("Tema:", docs)
        tipo = st.selectbox("Formato:", ["Maquetado Mnemotécnico", "Tabla Comparativa", "Resumen Ejecutivo"])
        if st.button("Generar Esquema"):
            resp = generar_con_reintento(f"Genera un recurso tipo '{tipo}' enfocado a oposiciones de Bombers basado en: {st.session_state.textos_pdfs_temario[ts][:12000]}")
            if resp: st.markdown(resp.text)

# ------------------------------------------------------------------------------
# 9. EXÁMENES OFICIALES
# ------------------------------------------------------------------------------
elif opcion == "🏛️ Preguntas Exámenes Oficiales":
    st.header("🏛️ Simulador Exámenes Oficiales (Nube)")
    oficiales = st.file_uploader("Sube exámenes oficiales anteriores:", type=["pdf"], accept_multiple_files=True, key="up_oficiales")
    if oficiales and supabase:
        for arch in oficiales:
            nombre_limpio_of = limpiar_nombre_archivo(arch.name)
            if nombre_limpio_of not in st.session_state.textos_pdfs_oficiales:
                try:
                    supabase.storage.from_("temarios").upload(f"oficiales/{nombre_limpio_of}", arch.getvalue(), {"content-type": "application/pdf", "upsert": "true"})
                    arch.seek(0)
                    txt = "".join([p.extract_text() + "\n" for p in pypdf.PdfReader(arch).pages if p.extract_text()])
                    if txt.strip(): st.session_state.textos_pdfs_oficiales[nombre_limpio_of] = txt
                except Exception as e: st.error(f"Error: {e}")
    
    docs_oficiales = list(st.session_state.textos_pdfs_oficiales.keys())
    if docs_oficiales:
        st.success(f"Hay {len(docs_oficiales)} documento(s) oficial(es) cargado(s) en la base.")
        
        st.markdown("---")
        st.subheader("⚙️ Configuración del Test / Simulacro")
        c1, c2 = st.columns(2)
        with c1: 
            num_preg_of = st.slider("Número de preguntas:", 10, 100, 25, 5, key="slider_num_oficiales")
        with c2: 
            tiempo_lim_of = st.slider("Tiempo límite (minutos):", 15, 180, 45, 15, key="slider_tiempo_oficiales")
        
        # Pestañas para elegir el modo de generación
        modo_gen_of = st.radio(
            "Selecciona el modo de examen oficial:",
            ["Simulacro Mixto (Todos los exámenes)", "Test Específico por Temario Oficial"],
            horizontal=True
        )

        if modo_gen_of == "Simulacro Mixto (Todos los exámenes)":
            if st.button("🚀 Generar Simulacro Oficial Mixto"):
                if verificar_cliente():
                    texto_oficiales_acumulado = obtener_texto_acumulado_oficiales()
                    prompt_oficial = (
                        f"Actúa como un tribunal de oposición de Bombers de la Generalitat. "
                        f"Genera un simulacro de examen oficial de {num_preg_of} preguntas de tipo test con 4 opciones (A, B, C, D), "
                        f"indicando claramente la respuesta correcta y una explicación detallada basada en las convocatorias oficiales. "
                        f"Las preguntas DEBEN estar basadas estrictamente en el contenido de los siguientes exámenes oficiales / documentos proporcionados:\n\n"
                        f"{texto_oficiales_acumulado[:15000]}"
                    )
                    with st.spinner("Generando simulacro mixto con tus PDFs oficiales..."):
                        resp = generar_con_reintento(prompt_oficial)
                        if resp: 
                            st.session_state.sim_of_activo = resp.text
                            st.success("¡Simulacro oficial generado con éxito!")

        else: # Test Específico por Temario Oficial
            tema_oficial_elegido = st.selectbox(
                "Selecciona el temario correspondiente de la biblioteca:",
                ["Física e Hidráulica", "Química y Fuego", "Legislación", "Mecánica y Vehículos", "Construcción y Edificación", "Sanitaria / Primeros Auxilios", "General / Varios"]
            )
            
            if st.button("🚀 Generar Test Oficial por Temario"):
                if verificar_cliente():
                    texto_oficiales_acumulado = obtener_texto_acumulado_oficiales()
                    prompt_oficial_tema = (
                        f"Actúa como un tribunal de oposición de Bombers de la Generalitat. "
                        f"Analiza los documentos de exámenes oficiales proporcionados, extrae y filtra únicamente aquellas preguntas "
                        f"que estén estrictamente relacionadas con el tema: '{tema_oficial_elegido}'. "
                        f"Genera un test oficial de {num_preg_of} preguntas tipo test con 4 opciones (A, B, C, D) sobre dicho tema, "
                        f"indicando la respuesta correcta y una explicación detallada.\n\n"
                        f"Documentos de exámenes oficiales:\n{texto_oficiales_acumulado[:15000]}"
                    )
                    with st.spinner(f"Filtrando y generando test oficial de '{tema_oficial_elegido}'..."):
                        resp = generar_con_reintento(prompt_oficial_tema)
                        if resp: 
                            st.session_state.sim_of_activo = resp.text
                            st.success(f"¡Test oficial de {tema_oficial_elegido} generado con éxito!")

        if "sim_of_activo" in st.session_state:
            st.markdown("---")
            renderizar_test_interactivo(st.session_state.sim_of_activo, "sim_of", nombre_tema="Examen Oficial")
    else:
        st.info("Sube al menos un PDF de examen oficial arriba para poder generar las preguntas basadas en tus documentos.")

# ------------------------------------------------------------------------------
# 10. ESTADÍSTICAS Y PROGRESOS
# ------------------------------------------------------------------------------
elif opcion == "📊 Estadísticas y Progresos":
    st.header("📊 Panel de Estadísticas")
    t1, t2 = st.tabs(["📝 Simulacros", "🎯 Test por Temas"])
    with t1:
        if st.session_state.historico:
            df = pd.DataFrame(st.session_state.historico)
            st.metric("Nota Media Simulacros", f"{df['nota'].mean():.2f}")
            st.dataframe(df, use_container_width=True)
            st.line_chart(df.set_index("fecha")[["nota"]])
        else: st.info("Sin registros de simulacros.")
    with t2:
        if st.session_state.historico_test_temas:
            df2 = pd.DataFrame(st.session_state.historico_test_temas)
            st.metric("Nota Media Temas", f"{df2['nota'].mean():.2f}")
            st.dataframe(df2, use_container_width=True)
            st.line_chart(df2.set_index("fecha")[["nota"]])
        else: st.info("Sin registros de test por temas.")

# ------------------------------------------------------------------------------
# 11. TUTOR IA
# ------------------------------------------------------------------------------
elif opcion == "💬 Tutor IA 24/7":
    st.header("💬 Tutoría Técnica Bombers")
    d = st.text_input("Consulta tu duda técnica:")
    if st.button("Preguntar al Tutor") and d:
        resp = generar_con_reintento(d)
        if resp: st.markdown(resp.text)