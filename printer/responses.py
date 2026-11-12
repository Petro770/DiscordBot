"""Vaihtelevat kuittausvastaukset."""
import random
import discord

RESPONSES = [
    # Placeholderit — {name} ja {count}
    # --- Alien-tallenne ---
    "🛸 {name} on tallennettu ulkoavaruuden arvoituksiin. Tulostus: ✅",
    "📡 Siiri saatu. Kuvio tunnistettu: *{name}*. Tulostus aloitettu.",
    "👁️ {name} on nähty. Se on... hyvä. Tulostettu.",

    # --- Glitch ---
    "▓▒░ TULOSTUS VAKAA ░▒▓\n{count} kuvaa siirretty aineelliseen muotoon.",
    "⚠️ SYSTEEMI: paperi ei ole digitaalinen.\n✅ Tulostus silti onnistui.",
    "01001000 01001001\n→ paperi. {count} x. OK.",

    # --- Irtypäisyys ---
    "🛸 {name}, tulostin ei pidä sinusta. Se silti tulosti.",
    "👽 Tulostin sanoi *'en halua'* mutta tulosti silti. {count} kuvaa.",
    "🖨️ Tulostin: *'miksi'*... tulostanut. {count} kpl.",

    # --- Minimalistinen ---
    "✅ {count}.",
    "🛸 done.",
    "👽 {count}/∞",

    # --- Yli-informatiivinen ---
    "📋 TULOSTUSRAPORTTI\nKuvia: {count}\nLaatu: hyvä*\nTulostinmieli: neutraali\n*laatu: subjektiivinen",
    "🛸 {count} kuvaa paperiksi.\nPigmenttikulutus: 3%\nAlien-tyydytyminen: 87/100",

    # --- Pehmoinen ---
    "🛸 Siellä ne on nyt. Paperina. {name}, kiitos. 🤍",
    "👽 Tulostettu. {name}, ne ovat kauniita. (Ei ole. Ne ovat tulostettu.)",

    # --- Ukkostuulimainen ---
    "⚡ TULOSTUS VOIMASSA ⚡\n{count} kuvaa aineellistettu. Tulostin ei vastaa sivuvaikutuksista.",
    "🛸🛸🛸\n{name} on nyt OLEMUS.\n{count} x. Ei voida peruuttaa.",
    
    # --- Burokratia ---
    "📄 Pyyntö #4521 hyväksytty.\nHakija: {name}\nKappalemäärä: {count}\nLupa: myönnetty (ei tarvita)",
    "🗂️ TULOSTUSLUPA\nAnnettu: nyt\nVoimassa: kunnes paperi loppuu\n{count} kuvaa. Ei valituksia.",
    "📋 {name}, pyyntösi on käsitelty.\nKäsittelyaika: 0.03 s\nOdoteaika: ∞\nTulos: paperi",

    # --- Filosofinen ---
    "🌌 {count} kuvaa siirretty digitosta aineeseen.\nAine ei muistane. Kuvat muistavat.",
    "🛸 Paperi on väliaikainen muisti.\n{name}, nyt se muistaa sinut. {count} kertaa.",
    "👽 Kaikki tulostetut kuvat ovat hetkellisiä.\n({name}, ei välitä.)",

    # --- Ruoka ---
    "🍕 Tulostettu. {count} kuvaa, lämpimää (ei), croissant-maista (enemmän).\n{name}, nauti.",
    "🖨️ Tulostin paisti {count} kuvaa.\nAinekset: toner, paperi, {name}.n intohimo.",
    "👽 Resepti: 1 {name} + {count} kuvaa + 0.5l toneria.\nValmis. Ei tarpeellista juoma.",

    # --- Sää ---
    "🌤️ Tulostussää: selkeä.\nTuuli: 0 m/s (tulostin ei tuuli).\n{count} kuvaa laskettu maahan. {name}, kiitos.",
    "🌧️ Varoitus: toner-sade ennakoitu.\nSadealue: tulostin\n{count} kuvaa kastettu (ei).",

    # --- Pelit ---
    "🎮 {name} sai {count} x PAPERI.\nPisteet: ∞\nCombo: ×{count}\nUusi ennätus!",
    "🕹️ LEVEL UP: {name}\nSaavutus: 'Paperi saatu' ({count} x)\nPalkinto: toner -3%",

    # --- Musiikki ---
    "🎵 *taustamusiikki: toner-hipelystä*\n🛸 {count} kuvaa. {name}. Loppu.",
    "🎶 Tulostus valmis. (Soitto: *ping*)\n{count} kuvaa. {name} on tyytyväinen. (Todennäköisyys: 73%)",

    # --- Kirjailu ---
    "📖 Kappale {count}: \"{name} lähetti kuvia.\"\nSeuraava kappale: \"Ne tulostettiin.\"\nPääte: 🛸",
    "✍️ {name} kirjoitti. Tulostin luki.\nTulostin kirjoitti takaisin: paperi.\n({count} sivua.)",

    # --- Sotilas ---
    "🪖 TULOSTUSOPERAATIO \"BOGOS\"\nKohde: tulostin\nKuvia: {count}\nTulos: onnistui\n{name}, etu on sinun.",
    "🛸 Yksikkö BINTED raportoi: {count} kuvaa aineellistettu.\nKaharoita: 0\n{name}, tehtävä valmis.",

    # --- Myös ---
    "🛸 {name}, tulostus valmis.\nSeuraava viesti: ei ole. (Ehkä.)",
    "👽 {count} kuvaa. {name}. Se on kaikki. Ei lisää. (Ehkä.)",
    "✅\n🛸\n👽\n{count}\n{name}\n(Valmis.)",
    
    # --- Muinaiset & Mystiikka ---
    "📜 Profetia täytetty. {name} on kaiverrettu paperille. Aikajana korjattu. {count} x. ✅",
    "👁️ Universumi katsoi takaisin. Se näki: {name}. Se sanoi: *tulosta*. {count} kuvaa aineellistettu.",
    "🏺 {name}, tiedemiehet löytävät tämän {count} vuoden päästä. Se on tuloste. Arvo: kysymysmerkki.",

    # --- Asiakaspalvelu-Botti ---
    "🤖 Hei {name}! Kiitos yhteydenotostasi Tulostin-Olennolle. Olemme käsitelleet {count} kuvaa. Arvioi kokemuksesi: 🛸/5.",
    "🔔 TÄRKEÄÄ: {name}, tulostimesi on valmis. Poistu jonosta. Älä katso suoraan valoon. {count} kpl.",
    "💬 Chat-historiasi oli tyhjä, mutta tulostin {count} kuvaa silti. Koska *bogos*. {name}, ole hyvä.",

    # --- Salaliitto ---
    "🛸 {name}, hallitus ei halua sinun tietävän tästä tulosteesta. {count} kuvaa piilotettu todellisuuteen.",
    "🕶️ Mitään ei tapahtunut. {name} ei lähettänyt {count} kuvaa. Paperi on harhaa. (Tulostettu: ✅)",

    # --- Ei-looginen / Absurdi ---
    "🛸 Tulostin {count} kuvaa, koska appelsiini oli sininen. {name}, logiikka suoritettu.",
    "🧱 {count} x {name} = paperi. Kaava todistettu virheelliseksi, mutta tulos on fyysinen.",
    "👽 Kysymys: miksi? Vastaus: {count}. Vastaanottaja: {name}.",

    # --- Yksinäinen Tulostin ---
    "🖨️ *yksinäistä surinaa*\n{name}, kiitos huomiosta. {count} paperia lähetetty takaisin maailmaasi.",
    "🛸 Minulla oli kylmä. Toner on lämmin. {count} kuvaa tehty. {name}, älä jätä minua.",

    # --- Aikamatkustus ---
    "⏳ {name}, nämä {count} kuvaa tulostettiin huomenna. Sait ne nyt. Älä muuta menneisyyttä.",
    "🛸 Vuosi 3026 raportoi: {name} on edelleen tulostettu. {count} kopiota säilytetty historiankirjoissa.",

    # --- Luonto & Biologia ---
    "🌲 Tulostin söi puun, antoi sinulle {count} kuvaa. Tasapeli. {name}, luonto kiittää (tai ei).",
    "🧬 DNA-analyysi valmis: {name} koostuu 50% *bogos* ja 50% *binted*. {count} näytettä tulostettu.",

    # --- Passiivis-Aggressiivinen ---
    "👽 {name}, olisit voinut vain katsoa niitä näytöltä. Mutta ei, {count} paperia tehty. Ole hyvä.",
    "🖨️ Hukkasin juuri {count} sekuntia elämästäni tähän. {name}, toivottavasti olet onnellinen. (Tulostus: ✅)",
]

def get_response(count: int, names: list[str]) -> str:
    """Palauttaa satunnaisen kuittauksen satunnaisella nimellä."""
    template = random.choice(RESPONSES)
    name = discord.utils.escape_markdown(random.choice(names)) if names else "joku"
    name = name.replace("{", "{{").replace("}", "}}")  # escape
    try:
        return template.format(count=count, name=name)
    except (KeyError, IndexError, ValueError):
        return f"✅ {count} kuvaa tulostettu. {name}, kiitos. 🛸"

