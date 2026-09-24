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
RUTINAS_POR_DEFECTO = {
    "Push (Empuje)": ["Press de banca plano con barra", "Press de banca inclinado con barra", "Press militar con barra", "Fondos en paralelas (Dips)", "Elevaciones laterales con mancuernas", "Press francés con barra Z", "Extensiones de tríceps en polea"],
    "Pull (Tirón)": ["Dominadas pronas lastradas", "Remo con barra", "Jalón al pecho en polea", "Remo en polea baja (Tirón horizontal)", "Face pull", "Curl de bíceps con barra", "Curl con mancuernas tipo martillo"],
    "Pierna (Tren Inferior)": ["Sentadilla trasera con barra", "Sentadilla frontal", "Prensa de piernas 45º", "Peso muerto rumano", "Zancadas con mancuernas (Lunges)", "Curl de isquios en máquina", "Elevación de talones en máquina (Gemelos)"],
    "Upper (Tren Superior)": ["Press de banca plano con barra", "Dominadas libres", "Press militar con mancuernas", "Remo con mancuerna a una mano", "Dominadas lastradas supinas"],
    "Lower (Fuerza / Salto / Opos)": ["Sentadilla trasera con barra", "Salto vertical con contramovimiento", "Cargadas de potencia (Power Clean)", "Prensa de piernas 45º", "Plancha abdominal isométrica"]
}

# Lectura directa y estricta de secretos (sin respaldos falsos)
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]

@st.cache_resource
def init_supabase():
    try:
        return create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        st.error(f"Error al conectar con Supabase: {e}")
        return None

supabase = init_supabase()

# Asegurarnos de que las rutinas NUNCA empiecen vacías
if "mis_rutinas" not in st.session_state:
    st.session_state.mis_rutinas = RUTINAS_POR_DEFECTO.copy()

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

LISTA_EJERCICIOS_HEAVY = [
    "Press de banca plano con barra", "Press de banca plano con mancuernas",
    "Press de banca inclinado con barra", "Press de banca inclinado con mancuernas",
    "Dominadas pronas lastradas", "Dominadas libres", "Dominadas supinas (chin-ups)",
    "Remo con barra", "Remo con mancuerna a una mano", "Remo en polea baja (Tirón horizontal)",
    "Press militar con barra (Standing Overhead Press)", "Press militar sentado con mancuernas",
    "Curl de bíceps con barra", "Curl con mancuernas tipo martillo",
    "Press francés con barra Z", "Extensiones de tríceps en polea alta (Cuerda)",
    "Sentadilla trasera con barra (Back Squat)", "Prensa de piernas 45º", "Peso muerto rumano",
    "Plancha abdominal isométrica", "Elevación de piernas colgado en barra", "Salto vertical con contramovimiento"
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
        except Exception as e:
            st.error(f"Detalle exacto del error de Google: {e}")
            str_e = str(e)
            # Si es un error temporal (503, saturación), reintentamos si quedan intentos
            if ("503" in str_e or "UNAVAILABLE" in str_e or "RESOURCE_EXHAUSTED" in str_e) and intento < intentos - 1:
                time.sleep(espera)
                continue
            return None
    return None
def sincronizar_desde_supabase():
    if not supabase:
        return
    # Intentar descargar rutinas de la nube si existen
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
                # Si falla porque el archivo ya existe, usamos update
                json_bytes = json.dumps(st.session_state.mis_rutinas).encode("utf-8")
                supabase.storage.from_("temarios").update(
                    path="datos/mis_rutinas.json",
                    file=json_bytes,
                    file_options={"content-type": "application/json"}
                )
            except Exception as e:
                pass

def inicializar_estados():
    sincronizar_desde_supabase()
    
    if "mis_rutinas" not in st.session_state:
        st.session_state.mis_rutinas = RUTINAS_POR_DEFECTO.copy()
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

# Botón de emergencia para forzar la sincronización en la barra lateral
if st.sidebar.button("🔄 Sincronizar con Nube"):
    if "mis_rutinas" in st.session_state:
        del st.session_state.mis_rutinas
    sincronizar_desde_supabase()
    st.rerun()

def guardar_simulacros_disco():
    if st.session_state.historico:
        df = pd.DataFrame(st.session_state.historico)
        df.to_csv(CSV_SIMULACROS, index=False)
        # Sincronizar con Supabase
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
    """Guarda el plan de estudio y el progreso actual en Supabase o en el estado local."""
    try:
        # Si ya tienes el cliente de Supabase configurado en tu app, 
        # puedes añadir aquí la llamada para actualizar la tabla del usuario.
        # Por ejemplo:
        # supabase.table("tu_tabla").upsert({
        #     "usuario_id": ..., 
        #     "plan_json": st.session_state.get("plan_estudio_json"),
        #     "progreso": st.session_state.get("progreso_estudio")
        # }).execute()
        pass
    except Exception as e:
        print(f"Error al guardar en la nube: {e}")

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
# 1. BIBLIOTECA DEL TEMARIO (SINCRONIZADA CON SUPABASE)
# ------------------------------------------------------------------------------
if opcion == "📚 Biblioteca del Temario":
    st.header("📚 Biblioteca del Temario Oficial (Nube)")
    st.write("Sube tus PDFs. Los nombres se adaptarán automáticamente para guardarse sin errores en Supabase.")

    archivos_subidos = st.file_uploader("Sube archivos PDF:", type=["pdf"], accept_multiple_files=True, key="up_temario")

    if archivos_subidos and supabase:
        for archivo in archivos_subidos:
            nombre_limpio = limpiar_nombre_archivo(archivo.name)
            try:
                # Subir archivo al bucket de Supabase
                supabase.storage.from_("temarios").upload(
                    path=f"temarios/{nombre_limpio}",
                    file=archivo.getvalue(),
                    file_options={"content-type": "application/pdf", "upsert": "true"}
                )
                
                # Extraer texto y guardarlo en session_state para la sesión actual
                archivo.seek(0)
                texto = "".join([p.extract_text() + "\n" for p in pypdf.PdfReader(archivo).pages if p.extract_text()])
                if texto.strip():
                    st.session_state.textos_pdfs_temario[nombre_limpio] = texto
                    st.success(f"📄 '{nombre_limpio}' subido y guardado en la nube con éxito.")
            except Exception as e:
                st.error(f"Error al subir {archivo.name}: {e}")

    # Sincronizar y listar directamente desde el bucket de Supabase
    if supabase:
        try:
            archivos_nube = supabase.storage.from_("temarios").list("temarios")
            nombres_nube = [f['name'] for f in archivos_nube if f['name'] != '']
        except Exception:
            nombres_nube = []
    else:
        nombres_nube = list(st.session_state.textos_pdfs_temario.keys())

    if nombres_nube:
        st.subheader("📁 Documentos en la Nube")
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
        
        nombre_nueva_rutina = st.text_input(
            "Nombre de la rutina (ej: Torso - Fuerza, Pierna Bombero):", 
            key="input_nombre_nueva_rutina"
        )
        lista_ejercicios = st.multiselect(
            "Selecciona o añade los ejercicios que componen esta rutina (Catálogo Completo):",
            LISTA_EJERCICIOS_HEAVY,
            default=["Press de banca plano con barra", "Dominadas pronas lastradas", "Sentadilla trasera con barra (Back Squat)"],
            key="multiselect_nueva_rutina"
        )
        
        if st.button("➕ Guardar Nueva Rutina", key="btn_guardar_nueva_rutina"):
            if nombre_nueva_rutina and lista_ejercicios:
                # 1. Actualizamos la memoria local
                st.session_state.mis_rutinas[nombre_nueva_rutina] = lista_ejercicios
                
                try:
                    # 2. Preparamos y subimos a Supabase con el booleano real upsert=True
                    json_bytes = json.dumps(st.session_state.mis_rutinas, ensure_ascii=False).encode("utf-8")
                    supabase.storage.from_("temarios").upload(
                        path="datos/mis_rutinas.json",
                        file=json_bytes,
                        file_options={"content-type": "application/json", "upsert": True}
                    )
                    st.success(f"¡Rutina '{nombre_nueva_rutina}' guardada!")
                    st.cache_data.clear()
                except Exception as e:
                    # Por si acaso el upload falla porque ya existe de otra forma, probamos update
                    try:
                        supabase.storage.from_("temarios").update(
                            path="datos/mis_rutinas.json",
                            file=json_bytes,
                            file_options={"content-type": "application/json"}
                        )
                        st.success(f"¡Rutina '{nombre_nueva_rutina}' actualizada en nube!")
                        st.cache_data.clear()
                    except Exception as e2:
                        st.error(f"Error al guardar: {e2}")
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
        if st.session_state.get("historial_marcas"):
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
        if client is not None:
            if not dias_estudio:
                st.warning("Selecciona al menos un día de estudio en la semana.")
            else:
                # Listado oficial completo: 7 de legislación + Temas técnicos del 8 al 34
                temario_oficial = [
                    # Legislación (Temas 1 a 7)
                    "Tema 01: Constitución Española, Estatut d'Autonomia, Administració catalana e instituciones",
                    "Tema 02: Personal al servicio de administraciones públicas, función pública de la Generalitat, derechos, deberes y régimen disciplinario",
                    "Tema 03: Ley 31/1995 de Prevención de Riesgos Laborales, EPIs y normativa de despliegue",
                    "Tema 04: Ley 19/2020 de igualdad de trato y no discriminación",
                    "Tema 05: Ley 17/2015 de igualdad efectiva de mujeres y hombres (Cap. 1, 3 y 4)",
                    "Tema 06: Ley 5/1994 de servicios de prevención y extinción de incendios y salvamentos de Cataluña y Ley 4/1997 de Protección Civil",
                    "Tema 07: Decreto 276/2016 de funciones de guardia y sistema de comandamiento, y Decreto 12/2023 de reestructuración del departamento de Interior",
                    
                    # Temario Específico / Técnico (Temas 8 al 34)
                    "Tema 08: Teoría del Fuego",
                    "Tema 09: Física",
                    "Tema 10: Química",
                    "Tema 11: Electricidad",
                    "Tema 12: Instalaciones",
                    "Tema 13: Hidráulica y Bombas",
                    "Tema 14: Cartografía y Orientación",
                    "Tema 15: Construcción",
                    "Tema 16: Intervención básica en asistencias técnicas",
                    "Tema 17: Comunicaciones por radio",
                    "Tema 18: Vehículos de intervención en emergencies",
                    "Tema 19: Conducción y mecánica",
                    "Tema 20: Equipos de protección individual en emergencias",
                    "Tema 21: Introducción a la gestión de emergencias y Protección Civil",
                    "Tema 22: Principis i característiques del Sistema de Comandament",
                    "Tema 23: Prevención básica de incendios",
                    "Tema 24: Intervención básica en incendios estructurales",
                    "Tema 25: Intervención básica en incendios forestales",
                    "Tema 26: Prevención incendios varios",
                    "Tema 27: Intervención básica en riesgos NRBQ",
                    "Tema 28: Asistencia sanitaria",
                    "Tema 29: Intervención básica en incidentes de múltiples víctimas",
                    "Tema 30: Intervención básica en estructuras colapsadas",
                    "Tema 31: Intervención básica al medi natural terrestre",
                    "Tema 32: Intervención básica en accidentes de movilidad viaria",
                    "Tema 33: Intervención básica en rescate urbano",
                    "Tema 34: Intervención básica en inundaciones"
                ]

                prompt = (
                    f"Actúa como un planificador experto y directo para oposiciones de Bombers de la Generalitat. "
                    f"Crea un plan de estudio teórico estructurado para dar una vuelta completa a TODO el temario oficial listado abajo. Extiéndete las semanas que sean necesarias (sin límite de 4 semanas, calcula las que hagan falta para cubrir los 41 temas de forma realista). "
                    f"Dispones de {hs} horas semanales distribuidas en los días: {', '.join(dias_estudio)} (4 horas diarias). "
                    f"REQUISITO DE CONTENIDO: Cada tarea debe seguir estrictamente este formato limpio por día: número y nombre exacto del tema de la lista oficial, seguido de las horas de teoría y las horas de test (ejemplo: 'Tema 9: Física - 3 horas de lectura y subrayado + 1 hora de test'). Si un tema es muy denso, divídelo en varias sesiones lógicas. "
                    f"Usa **única y exclusivamente** los temas de este listado oficial. Está prohibido inventar temas externos. "
                    f"Devuelve el resultado estrictamente en formato JSON puro con una lista de objetos por semana. Cada objeto semana debe tener las claves: "
                    f"'semana' (número entero), 'objetivo' (string corto) y 'dias' (una lista de objetos, donde cada objeto tiene 'dia' (string con el día) y 'tareas' (una lista de strings con el formato limpio de estudio y test)).\n\n"
                    f"Listado oficial completo de temas:\n" + "\n".join(temario_oficial)
                )
                with st.spinner("Generando plan de estudio estratégico..."):
                    resp = generar_con_reintento(prompt)
                    if resp:
                        try:
                            clean_json = resp.text.strip().replace("```json", "").replace("```", "")
                            st.session_state.plan_estudio_json = json.loads(clean_json)
                            st.session_state.plan_estudio_texto_raw = ""
                            st.success("¡Plan de estudio estratégico generado con éxito!")
                            guardar_plan_nube()
                        except Exception:
                            st.session_state.plan_estudio_json = None
                            st.session_state.plan_estudio_texto_raw = resp.text
                            st.success("¡Plan generado con éxito!")
                            guardar_plan_nube()

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
                        
                        if st.session_state.progreso_estudio.get(key_check) != completado:
                            st.session_state.progreso_estudio[key_check] = completado
                            guardar_plan_nube()
                            
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
