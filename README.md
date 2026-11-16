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
botti vastaa kanavalla liitteen sisältävään viestiin. Varoitus näyttää
samankaltaisuuspisteet. Mahdolliselle kuvakopiolle näytetään myös pHash-etäisyys
ja värikartan keskimääräinen ero.
Täsmälliselle kopiolle viestissä näkyvät lähettäjän oma määrä, kanavan
kokonaismäärä ja linkki ensimmäiseen indeksoituun osumaan. Lisäksi varoitus
näyttää lähettäjän sijoituksen kaikilta indeksoiduilta kanavilta sekä sijoituksen
saman SHA-256-sisällön uudelleenlähettäjien joukossa. Sijoituksiin lasketaan
kanavakohtaiset uudelleenlähetykset, joiden lähettäjä on tiedossa.
Kuvakopiosta
huomautetaan, kun yhdistetty
samankaltaisuuspiste on oletuksena vähintään 90 %. Pisteessä pHashin paino on
70 % ja värikartan 30 %. Automaattisen varoituksen rajan voi vaihtaa
`.env`-asetuksella `REPOST_WARNING_THRESHOLD=92.5` (0–100). Käynnistä botti
uudelleen asetuksen muuttamisen jälkeen. Täsmälliset SHA-256-osumat varoitetaan
aina, ja `/duplikaatit`-haun kuvavertailun raja on 90 %.

- `/indeksoi` lukee nykyisen kanavan historiaa enintään 1 000 viestiä kerrallaan.
  Komento vaatii käyttäjältä **Manage Messages** -oikeuden. Jos historiaa on vielä
  jäljellä, paina **Jatka indeksointia**. Painike on käytettävissä 10 minuuttia.
  Voit aina jatkaa myös uudella `/indeksoi`-komennolla, sillä edistyminen tallentuu kanavittain.
- `/duplikaatit tiedosto:<liite>` etsii nykyisen kanavan indeksistä ja näyttää
  käyttäjälle linkit enintään kymmeneen viestiin. Täsmälliset SHA-256-osumat
  näytetään ensin ja visuaaliset pHash- ja värikarttaosumat mahdollisina kopioina.
  Animoiduille kuville ja muille tiedostoille käytetään SHA-256:ta.

- `/repostaajat` listaa nykyisen kanavan viisi eniten tarkkoja liitekopioita
  lähettänyttä käyttäjää. Yksi viesti lasketaan kerran ja bottitilit ohitetaan.
  Kullekin käyttäjälle näytetään enintään kaksi ensimmäisen osuman linkkiä ja
  kyseiseen viestiin liittyvien uudelleenlähetysten määrä.
  Vanhojen indeksirivien tekijät haetaan tarvittaessa viesteistä Discordissa.
  Haku käyttää tallennettuja tiivisteitä, joten liitteitä ei ladata uudelleen.

Varmista, että botin Discord-asennuksella on `applications.commands`-oikeus.
Liitteet ladataan väliaikaisesti sormenjälkien laskemista varten.
`Channels/attachments.sqlite3` sisältää indeksin ja historiaskannauksen etenemisen.

## Botin ajastamattomien kanavaviestien siivous

Taustasiivous etsii botin omia viestejä, joilta puuttuu JSONissa poistoaika.
Oletuksena käytetään `TARGET_CHANNEL_ID`-kanavaa. Esikatselu kirjaa lokiin
ehdokkaiden määrän ja erääntyneiden viestien tunnisteet.

```dotenv
UNTRACKED_BOT_MESSAGE_CLEANUP_MODE=preview
UNTRACKED_BOT_MESSAGE_RETENTION_HOURS=24
# UNTRACKED_BOT_MESSAGE_CHANNEL_ID=123456789012345678
```

Vaihda tila arvoon `delete` ja käynnistä botti uudelleen, kun haluat ottaa
poiston käyttöön. `off` poistaa ajastamattomien viestien haun käytöstä.
Poistoaika lasketaan Discordin lähetysajasta. Jo yli vuorokauden ikäiset
ehdokkaat erääntyvät heti, ja aiemmin asetetut poistoajat säilyvät.
Botilla pitää olla kanavalla viestihistorian lukuoikeus.
