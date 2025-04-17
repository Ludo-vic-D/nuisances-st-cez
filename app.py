import streamlit as st
import pandas as pd
import uuid
import requests
import folium
from streamlit_folium import st_folium
import plotly.express as px
import boto3
import io

# === CONFIGURATION STREAMLIT ===
st.set_page_config(page_title="Déclaration de nuisances", layout="wide", initial_sidebar_state="expanded")

# === PARAMÈTRES ===
NUISANCES = ["Bruit", "Odeur", "Effet sur la santé", "Lumineuse"]
FREQUENCES = ["Tous les jours", "Une fois par semaine", "Une fois par mois", "Une fois par an"]
COULEURS_NUISANCES = {
    "Bruit": "red",
    "Odeur": "green",
    "Effet sur la santé": "orange",
    "Lumineuse": "blue"
}

# === S3 CONFIGURATION ===
S3_BUCKET = st.secrets["BUCKET_NAME"]
S3_KEY = "nuisances.csv"

s3 = boto3.client(
    "s3",
    aws_access_key_id=st.secrets["AWS_ACCESS_KEY_ID"],
    aws_secret_access_key=st.secrets["AWS_SECRET_ACCESS_KEY"],
    region_name="eu-west-3"
)

# === CHARGEMENT / SAUVEGARDE DES DONNÉES ===
def load_data():
    try:
        obj = s3.get_object(Bucket=S3_BUCKET, Key=S3_KEY)
        return pd.read_csv(obj["Body"])
    except s3.exceptions.NoSuchKey:
        return pd.DataFrame(columns=["id", "nom", "lat", "lon", "adresse", "nuisances", "frequence", "commentaire"])

def save_data(df):
    buffer = io.StringIO()
    df.to_csv(buffer, index=False)
    s3.put_object(Bucket=S3_BUCKET, Key=S3_KEY, Body=buffer.getvalue())

# === AJOUT PLAINTES ===
def ajouter_plainte(nom, lat, lon, adresse, nuisances, frequence, commentaire):
    df = load_data()
    nouvelle_plainte = {
        "id": str(uuid.uuid4()),
        "nom": nom if nom.strip() else "anonyme",
        "lat": lat,
        "lon": lon,
        "adresse": adresse,
        "nuisances": ";".join(nuisances),
        "frequence": frequence,
        "commentaire": commentaire
    }
    df = pd.concat([df, pd.DataFrame([nouvelle_plainte])], ignore_index=True)
    save_data(df)

# === GÉOCODAGE ===
def geocoder_adresse(adresse):
    try:
        url = "https://nominatim.openstreetmap.org/search"
        params = {"q": adresse, "format": "json"}
        r = requests.get(url, params=params, headers={"User-Agent": "streamlit-app"})
        r.raise_for_status()
        results = r.json()
        if results:
            return float(results[0]["lat"]), float(results[0]["lon"])
    except Exception as e:
        st.error(f"Erreur de géocodage : {e}")
    return None, None

# === SESSION STATE ===
for var, default in [("lat", None), ("lon", None), ("adresse", ""), ("zoom", 15)]:
    if var not in st.session_state:
        st.session_state[var] = default

# === INTERFACE ===
page = st.sidebar.radio("Navigation", ["Déclarer une nuisance", "Voir la carte globale"])

# === PAGE 1 : DÉCLARATION ===
if page == "Déclarer une nuisance":
    st.header("📍 Déclarer une nuisance ressentie")
    st.subheader("Double clic sur la carte pour placer le repère, possible de chercher avec l'adresse dans le bandeau de gauche")

    with st.sidebar:
        nom = st.text_input("Votre nom ou pseudo (laisser vide pour 'anonyme')", "")
        adresse = st.text_input("Adresse (autocomplétée via OpenStreetMap)", st.session_state.adresse)

        if adresse and adresse != st.session_state.adresse:
            lat, lon = geocoder_adresse(adresse)
            if lat and lon:
                st.session_state.lat = lat
                st.session_state.lon = lon
                st.session_state.adresse = adresse
                st.success(f"Adresse localisée : {lat:.5f}, {lon:.5f}")
            else:
                st.warning("Adresse introuvable. Essayez une autre formulation.")

        st.markdown("**Ou cliquez sur la carte pour indiquer l'emplacement**")

        st.subheader("Type(s) de nuisance ressentie")
        selected_nuisances = [n for n in NUISANCES if st.checkbox(n)]

        st.subheader("Fréquence de la nuisance")
        frequence = st.selectbox("À quelle fréquence ressentez-vous cette nuisance ?", FREQUENCES)

        commentaire = st.text_area("Commentaire (facultatif)")

        if st.button("✅ Envoyer la déclaration"):
            if st.session_state.lat and st.session_state.lon and selected_nuisances:
                ajouter_plainte(
                    nom,
                    st.session_state.lat,
                    st.session_state.lon,
                    st.session_state.adresse,
                    selected_nuisances,
                    frequence,
                    commentaire
                )
                st.success("Votre déclaration a été enregistrée. Merci !")
            else:
                st.warning("Veuillez indiquer une adresse ou cliquer sur la carte, et cocher au moins un type de nuisance.")

    map_center = [st.session_state.lat or 43.65388, st.session_state.lon or 6.80198]
    m = folium.Map(location=map_center, zoom_start=st.session_state.zoom,
    doubleClickZoom=False)

    if st.session_state.lat and st.session_state.lon:
        folium.Marker([st.session_state.lat, st.session_state.lon], tooltip="Localisation sélectionnée").add_to(m)

    click = st_folium(m, height=500, key="map", use_container_width=True)

    if click and click["last_clicked"]:
        st.session_state.lat = click["last_clicked"]["lat"]
        st.session_state.lon = click["last_clicked"]["lng"]
        if not adresse:
            st.session_state.adresse = "Localisation manuelle"

# === PAGE 2 : VISUALISATION ===
if page == "Voir la carte globale":
    st.header("🗺️ Carte des nuisances déclarées")
    df = load_data()

    if df.empty:
        st.info("Aucune plainte enregistrée pour le moment.")
    else:
        st.sidebar.subheader("🎛️ Filtres")
        types_filtres = st.sidebar.multiselect("Types de nuisance", NUISANCES, default=NUISANCES)
        freq_filtres = st.sidebar.multiselect("Fréquence", FREQUENCES, default=FREQUENCES)

        df_filtré = df[
            df["frequence"].isin(freq_filtres) &
            df["nuisances"].str.contains("|".join(types_filtres))
        ]

        st.subheader("Carte interactive")
        carte = folium.Map(location=[df["lat"].mean(), df["lon"].mean()], zoom_start=14)

        for _, row in df_filtré.iterrows():
            type_principal = row["nuisances"].split(";")[0]
            couleur = COULEURS_NUISANCES.get(type_principal, "gray")
            popup = f"<b>{row['nom']}</b><br>{row['adresse']}<br>{row['nuisances']}<br>Fréquence : {row['frequence']}<br>{row['commentaire']}"
            folium.Marker(
                location=[row["lat"], row["lon"]],
                popup=popup,
                icon=folium.Icon(color=couleur, icon="info-sign")
            ).add_to(carte)

        st_folium(carte, height=600, use_container_width=True)

        st.subheader("📊 Répartition des nuisances par type et fréquence")
        data_exploded = df_filtré.copy()
        data_exploded["nuisances"] = data_exploded["nuisances"].str.split(";")
        data_exploded = data_exploded.explode("nuisances")

    fig = px.histogram(
        data_exploded,
        x="nuisances",
        color="frequence",
        barmode="group",
        category_orders={"frequence": FREQUENCES},
        color_discrete_map={
            "Tous les jours": "red",
            "Une fois par semaine": "orange",
            "Une fois par mois": "yellow",
            "Une fois par an": "blue"
        }
    )
    st.plotly_chart(fig, use_container_width=True)
