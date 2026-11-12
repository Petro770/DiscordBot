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
