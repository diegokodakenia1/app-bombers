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
        # En la librería de Supabase, .list() sin parámetros o con path vacío lista la raíz
        archivos_nube = supabase.storage.from_("temarios").list()
        
        if archivos_nube:
            for archivo in archivos_nube:
                # Soportar diferentes formatos de respuesta de Supabase
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
MODELO_IA = "gemini-3.6-flash"

# Archivos locales de respaldo
CSV_SIMULACROS = "historial_simulacros.csv"
CSV_TEST_TEMAS = "historial_test_temas.csv"
CSV_FALLOS_REPASO = "banco_fallos_repaso.csv"
CSV_FLASHCARDS = "flashcards_guardadas.csv"
LISTA_EJERCICIOS_HEAVY = [
    # --- PECHO (CHEST) - BARRAS, MANCUERNAS, POLEAS Y MÁQUINAS ---
    "Press de banca plano con barra", "Press de banca plano con mancuernas",
    "Press de banca inclinado con barra", "Press de banca inclinado con mancuernas",
    "Press de banca declinado con barra", "Press declinado con mancuernas",
    "Press en máquina de pecho (Chest Press Machine)", "Press inclinado en máquina",
    "Press plano en máquina convergente", "Press inclinado en máquina convergente",
    "Press en máquina Smith (plano)", "Press en máquina Smith (inclinado)", "Press en máquina Smith (declinado)",
    "Aperturas con mancuernas en banco plano (Chest Fly)", "Aperturas con mancuernas en banco inclinado", "Aperturas con mancuernas en banco declinado",
    "Contractor de pecho / Pec Deck (Aperturas en máquina)",
    "Cruce de poleas altas (Cable Crossover de arriba a abajo)", "Cruce de poleas a la altura del pecho (horizontal)", "Cruce de poleas bajas (de abajo a arriba para pecho superior)",
    "Pullover con mancuerna", "Pullover en polea alta con barra recta o cuerda", "Pullover en máquina específica",
    "Fondos en paralelas (Dips - enfoque pectoral)", "Flexiones de pecho tradicionales (Push-ups)",
    "Flexiones declinadas", "Flexiones inclinadas", "Flexiones diamantinas", "Flexiones con manos anchas", "Flexiones lastradas",

    # --- ESPALDA (BACK) - POLEAS, MÁQUINAS Y LIBRES ---
    "Dominadas pronas lastradas", "Dominadas
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
    st.header("🎯 Test por Temas")
    
    if "textos_pdfs_temario" not in st.session_state:
        st.session_state.textos_pdfs_temario = {}

    # Botón de sincronización manual para la carpeta 'temarios'
    if st.button("🔄 Sincronizar PDFs desde Supabase"):
        try:
            # Listar los archivos dentro de la carpeta 'temarios' del bucket
            archivos_nube = supabase.storage.from_("temarios").list("temarios")
            
            contador = 0
            for archivo in archivos_nube:
                nombre_archivo = archivo.get("name") if isinstance(archivo, dict) else getattr(archivo, "name", None)
                
                if nombre_archivo and nombre_archivo.endswith(".pdf"):
                    # Descargar indicando la ruta completa dentro del bucket
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
                st.success(f"¡Se han cargado {contador} PDFs correctamente desde la carpeta 'temarios'!")
                st.rerun()
            else:
                st.warning("No se encontraron archivos PDF dentro de la carpeta 'temarios'.")
        except Exception as e:
            st.error(f"Error al sincronizar con Supabase: {e}")

    docs = list(st.session_state.textos_pdfs_temario.keys())

    if not docs:
        st.warning("Sube PDFs en la Biblioteca o pulsa el botón de arriba para sincronizar con la nube.")
    else:
        # Seleccionar tema para el test
        tema_sel = st.selectbox("Selecciona un documento/tema:", docs)
        num_preguntas = st.slider("Número de preguntas:", 5, 20, 10)
        
        if st.button("🚀 Generar Test del Tema"):
            texto_base = st.session_state.textos_pdfs_temario[tema_sel]
            prompt = (
                f"A partir del siguiente texto, genera un test tipo test de {num_preguntas} preguntas "
                f"con 4 opciones (A, B, C, D) y marca la respuesta correcta.\n\nTexto:\n{texto_base}"
            )
            resp = generar_con_reintento(prompt)
            if resp:
                st.session_state[f"test_{tema_sel}"] = resp.text
        
        key_test = f"test_{tema_sel}"
        if key_test in st.session_state:
            renderizar_test_interactivo(st.session_state[key_test], key_test, nombre_tema=tema_sel)

# ------------------------------------------------------------------------------
# 4. PREGUNTAS DE REPASO
# ------------------------------------------------------------------------------
elif opcion == "💡 Preguntas de Repaso":
    st.header("💡 Preguntas de Repaso Rápido")
    modo = st.radio("Modo:", ["🎯 Repaso de mis Fallos", "🎲 Repaso Aleatorio"])
    
    if "Fallos" in modo:
        if not st.session_state.banco_fallos: 
            st.info("No hay fallos registrados aún.")
        else:
            st.success(f"Tienes {len(st.session_state.banco_fallos)} preguntas guardadas de tus fallos anteriores.")
            # AQUÍ EL CAMBIO: Ya no llamamos a 'generar_con_reintento'. 
            # Mostramos directamente el banco de fallos en formato interactivo local.
            if st.button("🚀 Cargar Repaso de Mis Fallos"):
                # Convertimos tu banco de fallos directamente en el formato que lee tu renderizador
                texto_banco_local = ""
                for i, f in enumerate(st.session_state.banco_fallos, 1):
                    texto_banco_local += f"\nPregunta {i}: {f.get('enunciado')}\n"
                    for opcion_letra in ['A', 'B', 'C', 'D']:
                        if f.get(opcion_letra):
                            texto_banco_local += f"- {opcion_letra}) {f[opcion_letra]}\n"
                    texto_banco_local += f"Respuesta Correcta: {f.get('correcta')}\n"
                
                st.session_state.repaso_fallos_activo = texto_banco_local

            if "repaso_fallos_activo" in st.session_state:
                renderizar_test_interactivo(st.session_state.repaso_fallos_activo, "repaso_fallos", nombre_tema="Repaso de Mis Fallos")
                
    else:
        # El repaso aleatorio sí usa la IA porque necesita inventar preguntas nuevas desde cero
        if st.button("🚀 Generar Repaso Aleatorio"):
            resp = generar_con_reintento("Genera 10 preguntas de repaso general tipo test para Bombers.")
            if resp: 
                st.session_state.repaso_aleatorio = resp.text
        if "repaso_aleatorio" in st.session_state:
            renderizar_test_interactivo(st.session_state.repaso_aleatorio, "repaso_rand", nombre_tema="Repaso Aleatorio")
# ------------------------------------------------------------------------------
# 5. PREPARACIÓN FÍSICA (ESTILO HEVY INTEGRADO)
# ------------------------------------------------------------------------------
elif opcion == "🏋️‍♂️ Preparación Física":
    st.header("🏋️️‍♂️ Preparación Física & Progreso")
    t1, t2, t3, t4 = st.tabs(["🏋️‍♂️ Entrenar Rutina", "➕ Crear / Gestionar Rutinas", "📈 Gráficas de Progreso", "🏃‍♂️ Entrenamientos de Carrera"])
    
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
                    # --- BUSCAR HISTORIAL ANTERIOR ESPECÍFICO PARA ESTA SERIE ---
                    peso_anterior_s = 0.0
                    reps_anterior_s = 10
                    if st.session_state.get("historial_marcas"):
                        df_h = pd.DataFrame(st.session_state.historial_marcas)
                        df_ej = df_h[(df_h["Ejercicio"] == ej) & (df_h["Serie"] == s)]
                        if not df_ej.empty:
                            ultimo_reg_s = df_ej.iloc[-1]
                            peso_anterior_s = float(ultimo_reg_s.get("Peso (kg)", 0.0))
                            reps_anterior_s = int(ultimo_reg_s.get("Reps", 10))
                        else:
                            # Si no hay registro específico para esta serie, buscar el último general del ejercicio
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
                        peso_s = st.number_input(
                            f"Peso (kg) - {ej} S{s}", 
                            min_value=0.0, 
                            value=peso_anterior_s, 
                            step=0.5, 
                            key=f"peso_{ej}_{s}"
                        )
                    with col_s3: 
                        reps_s = st.number_input(
                            f"Reps - {ej} S{s}", 
                            min_value=1, 
                            max_value=100, 
                            value=reps_anterior_s, 
                            step=1, 
                            key=f"reps_{ej}_{s}"
                        )
                    
                    # --- DETECCIÓN DE RÉCORD EN TIEMPO REAL (MEDALLA HEVY) ---
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
            
            if st.button("💾 Guardar Entrenamiento y Actualizar Progreso"):
                st.session_state.historial_marcas.extend(nuevos_registros)
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
            st.info(f"✏️ Estás editando la rutina: **{rutina_en_edicion}**. Modifica el nombre o añade/quita ejercicios y guarda los cambios.")

        nombre_nueva_rutina = st.text_input(
            "Nombre de la rutina:", 
            value=st.session_state.form_nombre_rutina
        )
        
        lista_ejercicios = st.multiselect(
            "Selecciona o deselecciona ejercicios:",
            LISTA_EJERCICIOS_HEAVY,
            default=st.session_state.form_ejs_rutina
        )
        
        col_b1, col_b2 = st.columns([0.8, 0.2])
        with col_b1:
            btn_texto = "💾 Guardar Cambios de la Rutina" if rutina_en_edicion else "➕ Guardar Nueva Rutina"

            if st.button(btn_texto, key="btn_guardar_rutina_accion"):
                if nombre_nueva_rutina and lista_ejercicios:
                    if rutina_en_edicion and rutina_en_edicion != nombre_nueva_rutina:
                        if rutina_en_edicion in st.session_state.mis_rutinas:
                            del st.session_state.mis_rutinas[rutina_en_edicion]

                    st.session_state.mis_rutinas[nombre_nueva_rutina] = lista_ejercicios
                    
                    try:
                        json_bytes = json.dumps(st.session_state.mis_rutinas, ensure_ascii=False).encode("utf-8")
                        try:
                            supabase.storage.from_("temarios").remove(["datos/mis_rutinas.json"])
                        except:
                            pass
                        
                        supabase.storage.from_("temarios").upload(
                            path="datos/mis_rutinas.json",
                            file=json_bytes,
                            file_options={"content-type": "application/json"}
                        )
                        
                        st.session_state.editando_rutina = None
                        st.session_state.form_nombre_rutina = ""
                        st.session_state.form_ejs_rutina = []
                        
                        st.success(f"¡Rutina '{nombre_nueva_rutina}' guardada y sincronizada con éxito!")
                        st.rerun()
                    except Exception as e2:
                        st.error(f"Error al guardar en la nube: {e2}")
                else:
                    st.warning("Introduce un nombre y selecciona al menos un ejercicio.")
        
        with col_b2:
            if rutina_en_edicion:
                if st.button("❌ Cancelar", key="cancelar_edicion_rutina"):
                    st.session_state.editando_rutina = None
                    st.session_state.form_nombre_rutina = ""
                    st.session_state.form_ejs_rutina = []
                    st.rerun()

        if st.session_state.mis_rutinas:
            st.markdown("---")
            st.markdown("### Tus Rutinas Actuales:")
            
            rutinas_keys = list(st.session_state.mis_rutinas.keys())
            
            for i, r_nombre in enumerate(rutinas_keys):
                r_ejs = st.session_state.mis_rutinas[r_nombre]
                c_r1, c_r2, c_r3 = st.columns([0.65, 0.17, 0.18])
                
                with c_r1: 
                    st.write(f"• **{r_nombre}**: {', '.join(r_ejs)}")
                
                with c_r2:
                    if st.button("✏️ Editar", key=f"edit_rutina_idx_{i}"):
                        st.session_state.editando_rutina = r_nombre
                        st.session_state.form_nombre_rutina = r_nombre
                        st.session_state.form_ejs_rutina = r_ejs
                        st.rerun()

                with c_r3:
                    if st.button("🗑️ Borrar", key=f"del_rutina_idx_{i}"):
                        if st.session_state.editando_rutina == r_nombre:
                            st.session_state.editando_rutina = None
                            st.session_state.form_nombre_rutina = ""
                            st.session_state.form_ejs_rutina = []
                            
                        if r_nombre in st.session_state.mis_rutinas:
                            del st.session_state.mis_rutinas[r_nombre]
                        
                        try:
                            json_bytes = json.dumps(st.session_state.mis_rutinas, ensure_ascii=False).encode("utf-8")
                            try:
                                supabase.storage.from_("temarios").remove(["datos/mis_rutinas.json"])
                            except:
                                pass
                            
                            supabase.storage.from_("temarios").upload(
                                path="datos/mis_rutinas.json",
                                file=json_bytes,
                                file_options={"content-type": "application/json"}
                            )
                            st.success(f"Rutina '{r_nombre}' eliminada correctamente.")
                            st.rerun()
                        except Exception as e_del:
                            st.error(f"Error al actualizar la nube: {e_del}")

    with t3:
        st.subheader("📈 Gráficas de Progreso")
        
        tipo_progreso = st.radio("Selecciona el tipo de progreso a visualizar:", ["🏋️️‍♂️ Fuerza (Gym)", "🏃‍♂️ Carrera"], horizontal=True)
        
        if tipo_progreso == "🏋️‍♂️️ Fuerza (Gym)":
            if st.session_state.get("historial_marcas") and st.session_state.get("mis_rutinas"):
                df_marcas = pd.DataFrame(st.session_state.historial_marcas)
                
                rutina_grafico = st.selectbox("Selecciona la rutina para ver el desglose de sus ejercicios:", list(st.session_state.mis_rutinas.keys()))
                
                if rutina_grafico:
                    ejercicios_de_esta_rutina = st.session_state.mis_rutinas[rutina_grafico]
                    st.markdown(f"### Evolución de la rutina: *{rutina_grafico}*")
                    
                    for ej in ejercicios_de_esta_rutina:
                        st.markdown(f"#### 📊 {ej}")
                        df_filtrado = df_marcas[df_marcas["Ejercicio"] == ej]
                        
                        if not df_filtrado.empty:
                            max_peso = df_filtrado["Peso (kg)"].max()
                            st.metric(label=f"🏆 Récord Personal (PR) en {ej}", value=f"{max_peso} kg")
                            st.line_chart(df_filtrado.set_index("Fecha")[["Peso (kg)"]])
                        else:
                            st.info(f"Todavía no hay registros guardados para {ej}.")
                        st.markdown("---")
            else:
                st.info("Todavía no hay registros de entrenamientos de fuerza o rutinas guardadas.")
        
        else:
            if st.session_state.get("historial_carreras"):
                df_carreras = pd.DataFrame(st.session_state.historial_carreras)
                st.markdown("#### 📊 Evolución de Kilómetros por Sesión")
                st.line_chart(df_carreras.set_index("Fecha")[["Kilómetros (km)"]])
                st.markdown("#### 📋 Historial Completo de Carrera")
                st.dataframe(df_carreras, use_container_width=True)
            else:
                st.info("Todavía no hay registros de entrenamientos de carrera guardados.")

    with t4:
        st.subheader("🏃‍♂️ Registrar Entrenamiento de Carrera")

        fecha_carrera = st.date_input("Fecha de la carrera:", value=datetime.date.today(), key="fecha_carrera_input")
        
        col_c1, col_c2 = st.columns(2)
        with col_c1:
            tipo_carrera = st.text_input("Tipo de entreno / Nombre (ej: Series 400m, Rodaje Suave):", value="Rodaje Suave")
            n_series = st.number_input("Cantidad de series (0 si es continuo):", min_value=0, step=1, value=0)
            km_totales = st.number_input("Kilómetros totales (km):", min_value=0.0, step=0.1, value=5.0)
        
        with col_c2:
            tiempo_total = st.text_input("Tiempo total (ej: 25:00):", value="25:00")
            ritmo_medio = st.text_input("Ritmo medio (ej: 4:30 min/km):", value="5:00")

        if st.button("💾 Guardar Entrenamiento de Carrera y Progreso"):
            nuevo_registro_carrera = {
                "Fecha": str(fecha_carrera),
                "Entreno": tipo_carrera,
                "Series": n_series,
                "Kilómetros (km)": km_totales,
                "Tiempo": tiempo_total,
                "Ritmo": ritmo_medio
            }
            
            st.session_state.historial_carreras.append(nuevo_registro_carrera)
            guardar_carreras_nube()
            st.success("🎉 ¡Entrenamiento de carrera guardado y añadido al progreso con éxito!")

    # ------------------------------------------------------------------------------
    # AFEGIT: REGISTRE DE LES NOVES PROVES FÍSIQUES - BOMBERS GENERALITAT
    # ------------------------------------------------------------------------------
    st.markdown("---")
    st.markdown("### 🚒 Simulacre de les Noves Proves Oficials")
    tipo_prueba_oficial = st.selectbox(
        "Selecciona la prova oficial a registrar:", 
        [
            "1. Intervenció Estructural (Circuit)",
            "2. Intervenció Forestal (Rectes + Slam Ball)",
            "3. Prova Aquàtica / Rescat (6 fases)"
        ]
    )

    fecha_oficial = st.date_input("Data del simulacre:", value=datetime.date.today(), key="fecha_simulacre_oficial")

    if "1. Intervenció Estructural" in tipo_prueba_oficial:
        st.info("Circuit continu: Transport de discos, Step-Up, kettlebells, arrossegament/empenta de trineu, obstacle, maniquí i esprint.")
        c1, c2 = st.columns(2)
        with c1:
            temps_estructural = st.text_input("Temps total empleat (ej: 03:45):", value="03:45")
        with c2:
            penalitzacions_est = st.number_input("Segons de penalització (errors):", min_value=0, step=1, value=0)
        
        if st.button("💾 Guardar Registre Estructural"):
            reg_est = {
                "Data": str(fecha_oficial),
                "Prova": "Intervenció Estructural",
                "Temps/Marca": temps_estructural,
                "Penalització (s)": penalitzacions_est
            }
            if "historial_proves_oficials" not in st.session_state:
                st.session_state.historial_proves_oficials = []
            st.session_state.historial_proves_oficials.append(reg_est)
            st.success("🎉 ¡Simulacre estructural guardat correctament!")

    elif "2. Intervenció Forestal" in tipo_prueba_oficial:
        st.info("Prova progressiva: Alterna desplaçaments de 20m amb llançaments de Slam Ball per blocs (8, 10 o 12 rectes).")
        f1, f2 = st.columns(2)
        with f1:
            bloc_assolit = st.selectbox("Últim bloc completat:", ["Bloc 1 (8 rectes + 16 Slam Ball)", "Bloc 2 (10 rectes + 20 Slam Ball)", "Bloc 3 (12 rectes + 24 Slam Ball)"])
        with f2:
            temps_forestal = st.text_input("Temps total (ej: 02:30):", value="02:30")
            
        if st.button("💾 Guardar Registre Forestal"):
            reg_for = {
                "Data": str(fecha_oficial),
                "Prova": f"Intervenció Forestal - {bloc_assolit}",
                "Temps/Marca": temps_forestal,
                "Penalització (s)": 0
            }
            if "historial_proves_oficials" not in st.session_state:
                st.session_state.historial_proves_oficials = []
            st.session_state.historial_proves_oficials.append(reg_for)
            st.success("🎉 ¡Simulacre forestal guardat correctament!")

    else:
        st.info("Prova Aquàtica de Rescat: Entrada, 15m apnea, 30s flotació, crol lliure, crol de salvament i remolc de maniquí (6 fases consecutives).")
        a1, a2 = st.columns(2)
        with a1:
            temps_aigua = st.text_input("Temps total de la prova aquàtica (ej: 01:55):", value="01:55")
        with a2:
            fase_fallida = st.selectbox("Fase amb més dificultat o error:", ["Cap (Completat)", "Fase 1: Entrada", "Fase 2: Apnea 15m", "Fase 3: Flotació 30s", "Fase 4: Crol lliure", "Fase 5: Crol salvament", "Fase 6: Remolc maniquí"])

        if st.button("💾 Guardar Registre Aquàtic"):
            reg_aq = {
                "Data": str(fecha_oficial),
                "Prova": f"Aquàtica (Incidència: {fase_fallida})",
                "Temps/Marca": temps_aigua,
                "Penalització (s)": 0
            }
            if "historial_proves_oficials" not in st.session_state:
                st.session_state.historial_proves_oficials = []
            st.session_state.historial_proves_oficials.append(reg_aq)
            st.success("🎉 ¡Registre aquàtic guardat correctament!")

    # Mostrar taula amb l'historial de simulacres oficials si existeix
    if st.session_state.get("historial_proves_oficials"):
        st.markdown("---")
        st.markdown("### 📋 Historial de Simulacres de les Noves Proves")
        df_oficials = pd.DataFrame(st.session_state.historial_proves_oficials)
        st.dataframe(df_oficials, use_container_width=True)
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

        # REFUERZO: Inyectar todo el progreso guardado en las keys de Streamlit antes de pintar
        for k, v in st.session_state.progreso_estudio.items():
            st.session_state[k] = v

        for sem in st.session_state.plan_estudio_json:
            with st.expander(f"Semana {sem.get('semana')}: {sem.get('objetivo', '')}", expanded=False):
                for d_info in sem.get('dias', []):
                    dia_nombre = d_info.get('dia', '')
                    st.markdown(f"**📅 {dia_nombre}**")
                    for t_idx, tarea in enumerate(d_info.get('tareas', [])):
                        key_check = f"chk_sem_{sem.get('semana')}_{dia_nombre}_{t_idx}"
                        
                        # Asegurar clave individual
                        if key_check not in st.session_state:
                            st.session_state[key_check] = st.session_state.progreso_estudio.get(key_check, False)

                        def actualizar_checkbox(k=key_check):
                            st.session_state.progreso_estudio[k] = st.session_state[k]
                            guardar_plan_nube()

                        st.checkbox(tarea, key=key_check, on_change=actualizar_checkbox)
                        
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
