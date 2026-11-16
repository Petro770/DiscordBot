# DiscordBot (Bogos Binted)

Bogos Binted on Pythonilla tehty Discord-botti, joka käsittelee kuvia ja medialinkkejä yksityisviesteissä ja määritetyllä palvelinkanavalla. Botti lataa mediaa YouTubesta, Instagramista, X:stä, TikTokista ja Twitchistä, pakkaa tarvittaessa videoita ja lähettää tuloksen Discordiin. Kuvia voi myös tulostaa Windowsissa emoji-reaktiolla.

## Asennus ja käynnistys

Tarvitset Python 3.10:n tai uudemman sekä Discord-sovelluksen, jolle on luotu botti.

1. Luo projektikansiossa virtuaaliympäristö ja asenna riippuvuudet. Komennot ovat Windowsin PowerShellille.

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   ```

2. Ota Discord Developer Portalissa botin **Message Content Intent** käyttöön. Jos käytät bottia palvelimella, kutsu se palvelimelle ja anna sille kohdekanavalla oikeudet nähdä kanava, lukea viestihistoriaa, lähettää viestejä ja liitteitä sekä lisätä reaktioita. `POISTA` tarvitsee palvelinkanavalla myös **Manage Messages** -oikeuden.

3. Luo projektin juureen `.env` ja korvaa esimerkkiarvot botin tunnuksella ja kohdekanavan tunnisteella. Botti tarkistaa kohdekanavan käynnistyessään ja käyttää sitä myös `JAA`-komennon kohteena.

   ```dotenv
   DISCORD_TOKEN=oma_botin_token
   TARGET_CHANNEL_ID=123456789012345678
   ```

4. Käynnistä botti komentoriviltä.

   ```powershell
   .\.venv\Scripts\python.exe main.py
   ```

   Graafisen käynnistimen saat auki komennolla `.\.venv\Scripts\python.exe gui_launcher.py`.

## Käyttö Discordissa

Lähetä botille tuettu medialinkki tai kuva yksityisviestinä tai määritetyllä palvelinkanavalla. Kirjoita `OHJE`, niin saat komentolistan Discordissa.

| Komento | Toiminto |
| --- | --- |
| `POISTA <linkki>` | Poistaa alkuperäisen viestin onnistuneen käsittelyn jälkeen, jos botilla on siihen oikeus. |
| `JAA <linkki>` | Lähettää yksityisviestissä käsitellyn tuloksen myös kohdekanavalle. |
| `SISÄLTÖ POIS` / `SISÄLTÖ PÄÄLLÄ` | Piilottaa tai näyttää tiedoston mukana lähetettävät metatiedot. |
| `UNOHDAMINUT` | Käynnistää yksityisviestissä käyttäjäasetusten ja botin lähettämien yksityisviestien poiston. |

## Valinnaiset asetukset

Ominaisuuksia voi säätää `.env`-tiedostossa. `ENABLE_IMAGE_PRINTING=false` poistaa tulostuksen käytöstä. Tulostus käyttää Windowsin tulostinajuria, ja tulostimen nimi määritetään `config.py`-tiedostossa. `ENABLE_VIDEO_COMPRESS=false` poistaa videopakkauksen käytöstä, ja `VIDEO_COMPRESS_TARGET_MB` määrittää pakkauksen tavoitekoon megatavuina.

Botin tunnus, käyttäjäasetukset, viestiseuranta ja lokit tallentuvat paikallisesti. `.gitignore` rajaa ne versionhallinnan ulkopuolelle.

## Kanavan liitteiden indeksointi

Botti indeksoi uudet liitteet oletuksena `TARGET_CHANNEL_ID`-kanavalta.
Voit valita muita kanavia asettamalla `ATTACHMENT_INDEX_CHANNEL_IDS`-muuttujaan
kanavien tunnisteet pilkuilla erotettuina. Tyhjä arvo poistaa indeksoinnin käytöstä.
Kun käyttäjän uuden viestin liitteelle löytyy aiempi osuma samalta kanavalta,
botti vastaa kanavalle linkillä aiempaan viestiin. Vastaus erottaa täsmällisen
kopion mahdollisesta kuvakopiosta. Kuvakopiosta huomautetaan, kun yhdistetty
samankaltaisuuspiste on vähintään 90 %. Pisteessä pHashin paino on 70 % ja
värikartan 30 %. Sama raja koskee myös `/duplikaatit`-hakua.

- `/indeksoi` lukee nykyisen kanavan historiaa enintään 1 000 viestiä kerrallaan.
  Komento vaatii käyttäjältä **Manage Messages** -oikeuden. Jos historiaa on vielä
  jäljellä, paina **Jatka indeksointia**. Painike on käytettävissä 10 minuuttia.
  Voit aina jatkaa myös uudella `/indeksoi`-komennolla, sillä edistyminen tallentuu kanavittain.
- `/duplikaatit tiedosto:<liite>` etsii nykyisen kanavan indeksistä ja näyttää
  käyttäjälle linkit enintään kymmeneen viestiin. Täsmälliset SHA-256-osumat
  näytetään ensin ja visuaaliset pHash- ja värikarttaosumat mahdollisina kopioina.
  Animoiduille kuville ja muille tiedostoille käytetään SHA-256:ta.

- `/repostaajat` listaa nykyisen kanavan kymmenen eniten tarkkoja liitekopioita
  lähettänyttä käyttäjää. Yksi viesti lasketaan kerran ja bottitilit ohitetaan.
  Vanhojen indeksirivien tekijät haetaan tarvittaessa viesteistä Discordissa.
  Haku käyttää tallennettuja tiivisteitä, joten liitteitä ei ladata uudelleen.

Varmista, että botin Discord-asennuksella on `applications.commands`-oikeus.
Liitteet ladataan väliaikaisesti sormenjälkien laskemista varten.
`Channels/attachments.sqlite3` sisältää indeksin ja historiaskannauksen etenemisen.
