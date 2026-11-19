# Returflöde-dashboard (demo)

En dashboard i Streamlit för retur-, reklamations- och fraktskadeärenden i en e-handel som säljer FTX-ventilationspaket.

**All data är påhittad.** Kunderna är pseudonymiserade (`KUND-xxxx`), så demon innehåller inga personuppgifter.

## Vad den gör

| Flik | Innehåll |
|---|---|
| 📊 Översikt | Nyckeltal (antal ärenden, öppna ärenden, handläggningstid, värde), inflöde per vecka, vanligaste orsaker och var ärendena fastnar, plus automatiska insikter |
| 🤖 Automatisk triage | Claude klassar kundmeddelandet (retur, reklamation eller fraktskada), sammanfattar det, anger hur säker klassningen är och föreslår ett svar. Utan API-nyckel används en regelmotor som reserv |
| 📋 Ärenden | Filtrerbar ärendelista med CSV-export |

## Kör lokalt

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Aktivera AI-triage

Skapa `.streamlit/secrets.toml` utifrån `secrets.toml.example`, eller sätt miljövariabeln `ANTHROPIC_API_KEY`. På Streamlit Community Cloud lägger du nyckeln under *Settings → Secrets*.

**Så är AI-flödet uppbyggt:**
- **Människa i loopen:** svarsförslaget skickas aldrig automatiskt, och klassningar med under 70 % säkerhet flaggas för manuell granskning.
- **Reserv:** om API-anropet misslyckas (nätverk, kvot, ogiltig JSON) tar regelmotorn över, så flödet aldrig stannar.
- **Begränsade befogenheter:** agenten får aldrig lova återbetalning. Det beslutet fattas av en människa.
- **Nyckelhantering:** nyckeln läses från secrets eller miljövariabel och skyddas av `.gitignore`.

## Kör med Docker

```bash
docker build -t returflode .
docker run -p 8501:8501 -e ANTHROPIC_API_KEY=sk-ant-... returflode
```

Öppna sedan http://localhost:8501.

## Nästa steg i skarp drift

1. **Datakälla:** byt `skapa_demodata()` mot Shopify Admin API (ordrar, returer) eller helpdesk-exporten.
2. **Agent med verktyg:** låt Claude slå upp ordern i Shopify (via MCP eller API) och skapa ärendet direkt.
3. **Automation:** Zapier, Make eller n8n skapar ärenden, skickar returfraktsedlar och påminner kunder som inte har svarat efter tre dagar.
4. **Säkerhet och GDPR:** API-nycklar ligger i miljövariabler och aldrig i koden. Dashboarden visar bara den data som behövs, och åtkomsten är inloggningsskyddad.
