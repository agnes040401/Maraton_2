import json
import streamlit as st
from langfuse import Langfuse
from openai import OpenAI
#import pandas as pd 

#df = pd.read_csv('halfmarathon_wroclaw_2023__final.csv', sep=';')

# ======================
# Konfiguracja
# ======================
st.set_page_config(page_title="Półmaraton – estymacja czasu")

client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])

langfuse = Langfuse(
    public_key=st.secrets["LANGFUSE_PUBLIC_KEY"],
    secret_key=st.secrets["LANGFUSE_SECRET_KEY"],
    host=st.secrets["LANGFUSE_HOST"],
)

# ======================
# Prompt do ekstrakcji
# ======================
EXTRACTION_PROMPT = """
Wyciągnij z tekstu dane użytkownika.
Zwróć WYŁĄCZNIE poprawny JSON.

Pola:
- name: string | null
- gender: "male" | "female" | null
- age: int | null
- pace_5k: string | null  (format mm:ss na km)

Tekst:
"""

# ======================
# Model estymacji (do szacowania nieznanych parametrów)
# ======================
def estimate_half_marathon_time(pace_5k, age, gender): # pace_5k - tempo na 5 km
    minutes, seconds = map(int, pace_5k.split(":")) # split - podział
    pace_sec = minutes * 60 + seconds

    # współczynnik wydłużenia dystansu (Riegel) Współczynnik ten sugeruje, że przy podwojeniu 
    # dystansu (np. z 5 km na 10 km), czas nie wydłuża się dwukrotnie, lecz o ok. 6% więcej 
    # niż wynikałoby to z prostej proporcji 
    half_marathon_sec = pace_sec * 21.097 * 1.06
    # Half Marathon Sec: Total finish time in seconds.
    # Pace Sec: Average time per kilometer (in seconds) you plan to run.
    # 21.097: The standardized half marathon distance in kilometers (often rounded from 
    # 21.0975).
    # 1.06: A correction factor (approximately 6%) often used in predictions (derived from 
    # the Riegel formula) to account for fatigue and the likelihood that a runner will cover 
    # more than the exact distance

    # Example Calculation
    # If you want to run at a pace of 5:00 minutes/km (300 seconds per km):
    # Pace Sec: 300
    # Formula: 300*21.097*1.06
    # Result: 6,708.846 seconds
    # Conversion: 6,708.846 / 60 = 111.81 minutes (1 hour, 51 minutes, 49 seconds)
    # Note: Without the 1.06 factor, the result would be 1 hour 45 minutes, meaning the 
    # factor added ~7 minutes for a more realistic goal.

    # korekty
    if age and age > 40:
        half_marathon_sec *= 1 + (age - 40) * 0.003

    if gender == "female":
        half_marathon_sec *= 1.05

    total_minutes = int(half_marathon_sec // 60)
    total_seconds = int(half_marathon_sec % 60)

    return f"{total_minutes}:{total_seconds:02d}"

# ======================
# UI
# ======================
st.title("🏃 Szacowanie czasu półmaratonu")

user_text = st.text_area(
    "Przedstaw się i podaj swoje dane (naturalnym językiem)",
    placeholder="Cześć, mam na imię Marek, mam 35 lat, biegam 5 km w tempie 4:45/km",
)

if st.button("Oszacuj czas"):
    with st.spinner("Analiza danych..."):
        trace = langfuse.trace(
            name="half_marathon_estimation",
            input=user_text,
        )

        span = trace.span(
            name="llm", 
            input=user_text,
        )

        # ===== LLM extraction =====
        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Jesteś parserem danych."},
                {"role": "user", "content": EXTRACTION_PROMPT + user_text},
            ],
            response_format={"type": "json_object"},
        )

        extracted = json.loads(completion.choices[0].message.content)

        span.generation( # span zamiast trace
            name="llm_extraction",
            model="gpt-4o-mini",
            input=user_text,
            output=extracted,
       )

        # ===== Walidacja =====
        missing = [k for k in ["pace_5k"] if not extracted.get(k)]
        if missing:
            span.score( # span zamiast trace
                name="extraction_completeness",
                value=0.0,
            )
            st.error("Nie udało się wyciągnąć wszystkich danych.")
            st.json(extracted)
            st.stop()

        span.score( # span zamiast trace 
            name="extraction_completeness",
            value=1.0,
        )

        # ===== Estymacja =====
        result = estimate_half_marathon_time(
            pace_5k=extracted["pace_5k"],
            age=extracted["age"],
            gender=extracted["gender"],
        )

        span.end(output=result) # span zamiast trace

        # ===== UI wynik =====
        st.success(f"Szacowany czas półmaratonu: *{result}*")
        st.caption(f"Dane: {extracted}")