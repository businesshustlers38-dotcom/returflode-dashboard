"""
Returflöde-dashboard – demo för en e-handel som säljer FTX-ventilationspaket.

Visar hur retur-, reklamations- och fraktskadeärenden kan följas upp,
och hur inkommande kundmeddelanden kan triageras automatiskt
(regelbaserat här – kan bytas mot en AI-agent, t.ex. Claude via API).

All data är påhittad. Inga personuppgifter: kunder är pseudonymiserade (KUND-xxxx).
"""

from __future__ import annotations

import datetime as dt
import json
import os

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------
PRODUKTER = {
    "FTX-aggregat": 32000,
    "Kanalpaket villa": 8500,
    "Styrenhet/display": 2900,
    "Filtersats": 650,
    "Ventilationsdon": 450,
    "Ljuddämpare": 1200,
}
TYPER = ["Retur", "Reklamation", "Fraktskada"]
ORSAKER = {
    "Retur": ["Ångerrätt", "Fel produkt beställd", "Fel dimension", "Behövdes inte"],
    "Reklamation": ["Defekt fläkt", "Felkod på display", "Missljud", "Läckage", "Saknade delar"],
    "Fraktskada": ["Skadad förpackning", "Bucklig produkt", "Kollin saknas"],
}
STATUSAR = ["Ny", "Under utredning", "Väntar på kund", "Godkänd", "Avslutad"]
KUNDTYPER = ["Villaägare", "Installatör"]
AI_MODELL = "claude-haiku-5-5"  # snabb och billig modell räcker för klassning

# Nyckelord för automatisk triage (enkel regelmotor – ersätts med AI-agent i skarp drift)
TRIAGE_REGLER = [
    ("Fraktskada", ["trasig", "krossad", "skadad", "bucklig", "förpackning", "frakt", "saknas kolli"]),
    ("Reklamation", ["felkod", "fungerar inte", "missljud", "låter", "läcker", "defekt", "slutat", "garanti"]),
    ("Retur", ["ångra", "returnera", "skicka tillbaka", "fel storlek", "fel dimension", "behöver inte"]),
]
NASTA_STEG = {
    "Fraktskada": "Be kunden om foton inom 7 dagar och anmäl till transportören.",
    "Reklamation": "Skicka felsökningsguide + be om serienummer och felkod. Eskalera till leverantör vid behov.",
    "Retur": "Kontrollera ångerrätt (14 dagar) och skicka returfraktsedel automatiskt.",
    "Oklart": "Skicka till manuell hantering – be kunden förtydliga ärendet.",
}


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------
@st.cache_data
def skapa_demodata(antal: int = 420, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idag = dt.date(2026, 11, 18)
    rader = []
    for i in range(antal):
        typ = rng.choice(TYPER, p=[0.45, 0.40, 0.15])
        produkt = rng.choice(list(PRODUKTER), p=[0.12, 0.18, 0.12, 0.25, 0.23, 0.10])
        skapad = idag - dt.timedelta(days=int(rng.integers(0, 180)))
        status = rng.choice(STATUSAR, p=[0.08, 0.14, 0.10, 0.18, 0.50])
        # Reklamationer på dyra produkter tar längre tid
        bas = {"Retur": 3, "Reklamation": 9, "Fraktskada": 5}[typ]
        dagar = max(1, int(rng.gamma(2.0, bas / 2) + (4 if produkt == "FTX-aggregat" else 0)))
        rader.append(
            {
                "Ärende": f"ÄR-{1000 + i}",
                "Skapad": pd.Timestamp(skapad),
                "Typ": typ,
                "Orsak": rng.choice(ORSAKER[typ]),
                "Produkt": produkt,
                "Kundtyp": rng.choice(KUNDTYPER, p=[0.7, 0.3]),
                "Kund": f"KUND-{rng.integers(1000, 9999)}",
                "Status": status,
                "Handläggningstid (dagar)": dagar if status == "Avslutad" else None,
                "Värde (kr)": PRODUKTER[produkt],
            }
        )
    return pd.DataFrame(rader).sort_values("Skapad", ascending=False)


def hamta_api_nyckel() -> str | None:
    """API-nyckeln läses från Streamlit secrets eller miljövariabel – aldrig hårdkodad."""
    try:
        if "ANTHROPIC_API_KEY" in st.secrets:
            return st.secrets["ANTHROPIC_API_KEY"]
    except Exception:
        pass
    return os.environ.get("ANTHROPIC_API_KEY")


AI_SYSTEMPROMPT = """Du är kundtjänstagent för en svensk e-handel som säljer FTX-ventilationspaket
(aggregat, kanalpaket, styrenheter, filter, don) till villaägare och installatörer.
Klassa kundens meddelande och svara ENDAST med JSON enligt:
{
  "kategori": "Retur" | "Reklamation" | "Fraktskada" | "Oklart",
  "produkt": "<produkt som nämns eller 'Okänd'>",
  "sammanfattning": "<en mening>",
  "sakerhet": <tal 0-1, hur säker du är på kategorin>,
  "behover_manniska": <true om ärendet är oklart, argt, juridiskt eller gäller säkerhet>,
  "forslag_svar": "<kort, vänligt svar på svenska till kunden>"
}
Regler: ångerrätt 14 dagar för privatpersoner. Fraktskada: be om foton inom 7 dagar.
Reklamation: be om serienummer och felkod. Lova aldrig återbetalning – det beslutar en människa."""


def ai_triagera(text: str, api_nyckel: str) -> dict:
    """Klassar ärendet med Claude. Kastar undantag vid fel så att vi kan falla tillbaka."""
    import anthropic

    klient = anthropic.Anthropic(api_key=api_nyckel)
    svar = klient.messages.create(
        model=AI_MODELL,
        max_tokens=600,
        system=AI_SYSTEMPROMPT,
        messages=[{"role": "user", "content": text}],
    )
    ra = svar.content[0].text.strip()
    start, slut = ra.find("{"), ra.rfind("}")
    data = json.loads(ra[start : slut + 1])
    if data.get("kategori") not in NASTA_STEG:
        data["kategori"] = "Oklart"
    # Människa i loopen: låg säkerhet skickas alltid till manuell granskning
    if float(data.get("sakerhet", 0)) < 0.7:
        data["behover_manniska"] = True
    return data


def triagera(text: str) -> tuple[str, list[str]]:
    """Regelbaserad reserv: returnerar (kategori, träffade nyckelord)."""
    t = text.lower()
    bast, traffar = "Oklart", []
    for kategori, ord_lista in TRIAGE_REGLER:
        hit = [o for o in ord_lista if o in t]
        if len(hit) > len(traffar):
            bast, traffar = kategori, hit
    return bast, traffar


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
st.set_page_config(page_title="Returflöde – FTX e-handel", page_icon="🌀", layout="wide")
st.title("🌀 Returer & reklamationer")
st.caption("Demo med påhittad data · kunder pseudonymiserade · byggd i Python/Streamlit")

df = skapa_demodata()

with st.sidebar:
    st.header("Filter")
    min_d, max_d = df["Skapad"].min().date(), df["Skapad"].max().date()
    period = st.date_input("Period", (max_d - dt.timedelta(days=90), max_d), min_d, max_d)
    typer = st.multiselect("Ärendetyp", TYPER, default=TYPER)
    kundtyper = st.multiselect("Kundtyp", KUNDTYPER, default=KUNDTYPER)

start, slut = (period if isinstance(period, tuple) and len(period) == 2 else (min_d, max_d))
f = df[
    df["Skapad"].between(pd.Timestamp(start), pd.Timestamp(slut))
    & df["Typ"].isin(typer)
    & df["Kundtyp"].isin(kundtyper)
]

flik1, flik2, flik3 = st.tabs(["📊 Översikt", "🤖 Automatisk triage", "📋 Ärenden"])

with flik1:
    oppna = f[f["Status"] != "Avslutad"]
    avslutade = f[f["Status"] == "Avslutad"]
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Ärenden i perioden", len(f))
    k2.metric("Öppna ärenden", len(oppna))
    k3.metric(
        "Snitt handläggningstid",
        f"{avslutade['Handläggningstid (dagar)'].mean():.1f} dagar" if len(avslutade) else "–",
    )
    k4.metric("Värde i öppna ärenden", f"{oppna['Värde (kr)'].sum():,.0f} kr".replace(",", " "))

    if f.empty:
        st.info("Inga ärenden matchar filtret.")
    else:
        v1, v2 = st.columns(2)
        per_vecka = (
            f.assign(Vecka=f["Skapad"].dt.to_period("W").dt.start_time)
            .groupby(["Vecka", "Typ"]).size().reset_index(name="Antal")
        )
        v1.subheader("Inflöde per vecka")
        v1.altair_chart(
            alt.Chart(per_vecka).mark_bar().encode(
                x=alt.X("Vecka:T", title=None),
                y=alt.Y("Antal:Q", title="Ärenden"),
                color=alt.Color("Typ:N", legend=alt.Legend(orient="bottom")),
                tooltip=["Vecka:T", "Typ:N", "Antal:Q"],
            ),
            width="stretch",
        )
        orsaker = f.groupby("Orsak").size().reset_index(name="Antal").sort_values("Antal", ascending=False)
        v2.subheader("Vanligaste orsakerna")
        v2.altair_chart(
            alt.Chart(orsaker.head(8)).mark_bar().encode(
                x=alt.X("Antal:Q", title="Ärenden"),
                y=alt.Y("Orsak:N", sort="-x", title=None),
                tooltip=["Orsak", "Antal"],
            ),
            width="stretch",
        )

        st.subheader("Var fastnar ärendena?")
        status_df = f.groupby("Status").size().reindex(STATUSAR, fill_value=0).reset_index(name="Antal")
        st.altair_chart(
            alt.Chart(status_df).mark_bar().encode(
                x=alt.X("Status:N", sort=STATUSAR, title=None),
                y=alt.Y("Antal:Q", title="Ärenden"),
                tooltip=["Status", "Antal"],
            ),
            width="stretch",
        )

        st.subheader("💡 Insikter")
        topp = orsaker.iloc[0]
        rekl = f[f["Typ"] == "Reklamation"]
        st.markdown(
            f"- **{topp['Orsak']}** är vanligaste orsaken ({topp['Antal']} ärenden) – "
            "kandidat för bättre produkttext eller felsökningsguide.\n"
            f"- **{(f['Status'] == 'Väntar på kund').sum()}** ärenden väntar på kunden – "
            "en automatisk påminnelse efter 3 dagar kan stänga dem snabbare.\n"
            + (
                f"- Reklamationer på **FTX-aggregat** tar i snitt "
                f"{rekl[rekl['Produkt'] == 'FTX-aggregat']['Handläggningstid (dagar)'].mean():.1f} dagar "
                "– längst av alla produkter."
                if not rekl[(rekl["Produkt"] == "FTX-aggregat") & (rekl["Status"] == "Avslutad")].empty
                else ""
            )
        )

with flik2:
    st.subheader("Klistra in ett kundmeddelande")
    api_nyckel = hamta_api_nyckel()
    if api_nyckel:
        st.success("🤖 AI-läge: Claude klassar ärendet och föreslår ett svar. En människa godkänner innan något skickas.")
    else:
        st.info(
            "Regelläge (ingen API-nyckel hittad). Lägg till `ANTHROPIC_API_KEY` i Streamlit secrets "
            "eller som miljövariabel för att aktivera AI-triage med Claude."
        )
    exempel = {
        "Välj exempel…": "",
        "Fraktskada": "Hej, kartongen var krossad när den kom och aggregatet är bucklig på sidan.",
        "Reklamation": "Vårt FTX-aggregat visar felkod E3 och fläkten har slutat gå. Gäller garantin?",
        "Retur": "Jag beställde fel dimension på kanalerna, kan jag returnera dem?",
    }
    val = st.selectbox("Exempel", list(exempel))
    text = st.text_area("Meddelande", value=exempel[val], height=120)
    if st.button("Triagera", type="primary") and text.strip():
        resultat = None
        if api_nyckel:
            try:
                with st.spinner("Claude analyserar…"):
                    resultat = ai_triagera(text, api_nyckel)
            except Exception as fel:  # nätverk, kvot, ogiltig JSON …
                st.warning(f"AI-anropet misslyckades ({type(fel).__name__}) – använder regelmotorn i stället.")

        if resultat:
            kategori = resultat["kategori"]
            c1, c2, c3 = st.columns(3)
            c1.metric("Kategori", kategori)
            c2.metric("Säkerhet", f"{float(resultat.get('sakerhet', 0)):.0%}")
            c3.metric("Granskning", "Människa krävs" if resultat.get("behover_manniska") else "Kan automatiseras")
            st.markdown(f"**Produkt:** {resultat.get('produkt', 'Okänd')}  \n**Sammanfattning:** {resultat.get('sammanfattning', '')}")
            st.markdown(f"**Nästa steg:** {NASTA_STEG[kategori]}")
            st.text_area("Föreslaget svar till kunden (redigera innan du skickar)", resultat.get("forslag_svar", ""), height=140)
        else:
            kategori, traffar = triagera(text)
            c1, c2 = st.columns([1, 2])
            c1.metric("Föreslagen kategori", kategori)
            c2.markdown(f"**Nästa steg:** {NASTA_STEG[kategori]}")
            if traffar:
                st.caption("Träffade nyckelord: " + ", ".join(traffar))

with flik3:
    st.subheader("Ärendelista")
    st.dataframe(
        f,
        width="stretch",
        hide_index=True,
        column_config={
            "Skapad": st.column_config.DateColumn(format="YYYY-MM-DD"),
            "Värde (kr)": st.column_config.NumberColumn(format="%d kr"),
        },
    )
    st.download_button(
        "Ladda ner som CSV",
        f.to_csv(index=False).encode("utf-8"),
        file_name="arenden.csv",
        mime="text/csv",
    )
