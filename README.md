# DiscordBot (Bogos Binted)

Bogos Binted on Pythonilla tehty Discord-botti, joka käsittelee kuvia ja medialinkkejä yksityisviesteissä ja määritetyllä palvelinkanavalla. Botti lataa mediaa YouTubesta, Instagramista, X:stä, TikTokista, Twitchistä ja SoundCloudista, pakkaa tarvittaessa videoita ja lähettää tuloksen Discordiin. Botti lähettää SoundCloud-kappaleen MP4-videona, jossa kansikuva näkyy koko ajan ja kappaleen nimi sekä artisti ensimmäiset viisi sekuntia. Jos videota ei saada tehtyä tai se ylittää Discordin kokorajan, botti käyttää MP3-tiedostoa. Kuvia voi myös tulostaa Windowsissa emoji-reaktiolla.

## Asennus ja käynnistys

Tarvitset Python 3.10:n tai uudemman sekä Discord-sovelluksen, jolle on luotu botti.

1. Luo projektikansiossa virtuaaliympäristö ja asenna riippuvuudet. Komennot ovat Windowsin PowerShellille.

   ```powershell
   .\install.ps1
   ```

2. Ota Discord Developer Portalissa botin **Message Content Intent** käyttöön. Jos käytät bottia palvelimella, kutsu se palvelimelle ja anna sille kohdekanavalla oikeudet nähdä kanava, lukea viestihistoriaa, lähettää viestejä ja liitteitä sekä lisätä reaktioita. `POISTA` tarvitsee palvelinkanavalla myös **Manage Messages** -oikeuden.

3. Kopioi [example.env](example.env) nimellä `.env` komennolla `Copy-Item example.env .env` (jos sinulla ei vielä ole `.env`-tiedostoa). Täytä botin token ja tarvittaessa kohdekanavan tunniste. Mallitiedosto sisältää kaikki projektin käyttämät ympäristöasetukset ja niiden oletusarvot. Botti tarkistaa kohdekanavan käynnistyessään ja käyttää sitä myös `JAA`-komennon kohteena.

   ```dotenv
   DISCORD_TOKEN=oma_botin_token
   TARGET_CHANNEL_ID=123456789012345678
   ```

4. Käynnistä graafinen hallintaikkuna tai komentorivibotti.

   ```powershell
   .\launch.ps1
   .\launch.ps1 -Mode Main
   ```

   `.\launch.ps1 -CheckOnly` tarkistaa molempien käynnistystapojen Python-riippuvuudet ja moduulien latautumisen ilman Discord-yhteyttä. Skriptit käyttävät projektin omaa `.venv`-ympäristöä tavallisilla käyttäjäoikeuksilla.

   Jos PowerShell estää skriptin suorituskäytännön vuoksi, voit käynnistää sen erillisessä PowerShell-prosessissa komennolla `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1`. Vaihda tiedoston nimeksi `.\launch.ps1` käynnistystä varten.

## Käyttö Discordissa

Lähetä botille tuettu medialinkki tai kuva yksityisviestinä tai määritetyllä palvelinkanavalla. Kirjoita `OHJE`, niin saat komentolistan Discordissa.

| Komento | Toiminto |
| --- | --- |
| `POISTA <linkki>` | Poistaa alkuperäisen viestin onnistuneen käsittelyn jälkeen, jos botilla on siihen oikeus. |
| `JAA <linkki>` | Lähettää yksityisviestissä käsitellyn tuloksen myös kohdekanavalle. |
| `SISÄLTÖ POIS` / `SISÄLTÖ PÄÄLLÄ` | Piilottaa tai näyttää tiedoston mukana lähetettävät metatiedot. |
| `UNOHDAMINUT` | Käynnistää yksityisviestissä käyttäjäasetusten ja botin lähettämien yksityisviestien poiston. |

## Ollama-vastaukset

Lisää `ENABLE_OLLAMA=true` tiedostoon `.env` ja käynnistä botti uudelleen.
Kokeile Discordissa esimerkiksi `@K-Embedder Miksi taivas on sininen?`.
Botti vastaa suoraan viestiin yksityisviesteissä ja sallituilla palvelinkanavilla.
Oletuksena sallittu kanava on `TARGET_CHANNEL_ID`. Voit antaa useita
kanavatunnisteita pilkulla eroteltuina asetuksessa `OLLAMA_CHANNEL_IDS`.

`OLLAMA_HOSTS` sisältää palvelinten osoitteet kokeilujärjestyksessä.
Oletusosoitteet ovat `192.168.1.11`, `192.168.1.12` ja `192.168.1.13`
portissa `11434`. Tyhjällä `OLLAMA_MODELS`-asetuksella botti hakee
asennetut mallit kultakin palvelimelta. Halutessasi anna pilkulla erotettu
lista tarkoista paikallisista mallinimistä. Botti kokeilee listaa kullekin
palvelimelle ja käyttää ensimmäistä onnistunutta vastausta. Lokista näkee
vastanneen palvelimen ja mallin.

Botti lähettää Ollamalle Glorpin ohjeet ja mainintaviestin tekstin ilman omaa mainintaansa.
Se käsittelee yhden Ollama-kysymyksen kerrallaan. Botin koneen pitää päästä
Ollama-palvelimiin lähiverkosta. Yhteyden voi tarkistaa botin koneelta
esimerkiksi PowerShellissä komennolla
`Invoke-RestMethod http://192.168.1.11:11434/api/tags`.
Jos Ollama kuuntelee vain paikallisia yhteyksiä, määritä palvelimella
`OLLAMA_HOST` kuuntelemaan lähiverkon osoitetta.

### Glorpin persoona ja ohjeet

[bot/glorp.md](bot/glorp.md) sisältää Glorpin puhetyylin ja ohjeet botin
Discord-toiminnoista. Kokeile esimerkiksi `@Glorp mitä osaat?` tai
`@Glorp miten laitan repostausvaroitukset yksityisviesteihin?`.
Glorp saa lisäksi tiedon käytössä olevista medialatauspalveluista,
kuvatulostuksesta ja liiteindeksoinnista.

Jos haluat omat ohjeet, kopioi oletusohje UTF-8-tiedostoksi, muokkaa
sitä ja aseta `OLLAMA_INSTRUCTIONS_FILE=glorp-paikallinen.md` tiedostoon
`.env`. Suhteellinen polku alkaa projektikansiosta. Käynnistä botti uudelleen
ladataksesi muutokset.

## Leikepöydän medialataukset

SoundCloud-kappaleet ladataan oletuksena MP4-videoiksi animoidulla aaltomuodolla. Videon muodostus käyttää samaa toteutusta kuin Discord-botti. Poista GUI:n **SoundCloud leikepöydälle MP4-videona** -valinta, kun haluat MP3-tiedoston. Valinta muistetaan seuraavalla käynnistyksellä.

Valitse GUI:ssa **Seuraa leikepöydän medialinkkejä** ja kopioi yksittäinen YouTube-, Instagram-, X-, TikTok-, Twitch- tai SoundCloud-medialinkki. Lataus toimii taustalla yksi linkki kerrallaan. Yli 150 MB:n videot yritetään pakata, ja valmis tiedosto saa olla enintään 150 MB.

Valmis tiedosto korvaa leikepöydän sisällön automaattisesti. Kun saat ilmoituksen, liitä tiedosto Discordiin painamalla **Ctrl+V**. Tiedostot tallentuvat paikalliseen `clipboard_downloads/`-kansioon.

## Valinnaiset asetukset

Ominaisuuksia voi säätää `.env`-tiedostossa. `ENABLE_SOUNDCLOUD=false` poistaa SoundCloud-lataukset käytöstä. `ENABLE_SOUNDCLOUD_VIDEO=false` käyttää SoundCloudissa aina MP3-tiedostoa. `ENABLE_IMAGE_PRINTING=false` poistaa tulostuksen käytöstä. Tulostus käyttää Windowsin tulostinajuria, ja tulostimen nimi määritetään `config.py`-tiedostossa. `ENABLE_VIDEO_COMPRESS=false` poistaa videopakkauksen käytöstä, ja `VIDEO_COMPRESS_TARGET_MB` määrittää pakkauksen tavoitekoon megatavuina.

Botin tunnus, käyttäjäasetukset, viestiseuranta ja lokit tallentuvat paikallisesti. `.gitignore` rajaa ne versionhallinnan ulkopuolelle.

## Kanavan liitteiden indeksointi

Botti indeksoi uudet liitteet oletuksena `TARGET_CHANNEL_ID`-kanavalta.
Voit valita muita kanavia asettamalla `ATTACHMENT_INDEX_CHANNEL_IDS`-muuttujaan
kanavien tunnisteet pilkuilla erotettuina. Tyhjä arvo poistaa indeksoinnin käytöstä.
Kun käyttäjän uuden viestin liitteelle löytyy aiempi osuma samalta kanavalta,
botti varoittaa oletuksena vastaamalla kanavalla liitteen sisältävään viestiin.
Voit valita varoitustavan erikseen mahdollisille kuvakopioille ja täsmällisille
liitekopioille botin yksityisviestissä tai sen kohdekanavalla.

| Komento | Varoituksen tyyppi |
| --- | --- |
| `KUVAKOPIOVAROITUS KANAVA` / `DM` / `POIS` | Mahdollinen kuvakopio |
| `REPOSTAUSVAROITUS KANAVA` / `DM` / `POIS` | Täsmällinen liitekopio |

`KANAVA` on oletus, `DM` lähettää varoituksen yksityisviestinä ja `POIS` kytkee
varoituksen pois. Asetukset tallentuvat käyttäjäkohtaisesti. Jos yksityisviestin
lähetys epäonnistuu, julkista varoitusta ei lähetetä. Liitteet indeksoidaan
kaikilla asetuksilla. Jos varoitustavalle ei ole vielä tallennettua valintaa,
kanavavaroituksessa näkyvät valintapainikkeet. Vain varoituksen saanut käyttäjä
voi valita seuraavien varoitusten tavan. Painikkeet ovat käytössä 10 minuuttia,
ja valinta näkyy uudelleen seuraavassa varoituksessa, jos asetusta ei tallennettu.
Discordissa ohjeen saa komennolla `OHJE ASETUKSET`.

Varoitus näyttää
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
uudelleen asetuksen muuttamisen jälkeen. Täsmälliset SHA-256-osumat eivät riipu
samankaltaisuusrajasta. `/duplikaatit`-haun kuvavertailun raja on 90 %.

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

## GUI:n SoundCloud-videoasetukset

Avaa hallintapaneelista **SoundCloud-videon asetukset…**. Ikkunasta voi säätää
FPS-tavoitetta (1–60), neliövideon resoluutiota (320–1920 px), äänen bittinopeutta
(48–320 kbit/s), CRF-laatua, enkoodausnopeutta, taajuuskaistojen määrää (1–30),
otsikon näyttöaikaa, viivan paksuutta (1–12 px), aaltomuodon taustan peittävyyttä, aaltojen korkeutta ja
aikaikkunaa sekä renderöinnin aikarajaa ja automaattista pakkausta.

**Tallenna** ottaa asetukset käyttöön seuraavassa leikepöytälatauksessa ja säilyttää
ne myös uudelleenkäynnistyksessä. **Peruuta** hylkää muutokset; **Palauta oletukset**
palauttaa alkuperäiset arvot lomakkeeseen, jonka jälkeen ne voi tallentaa.
Asetukset koskevat GUI:n leikepöytälatauksia. Äänen laatua rajoittaa myös lähde.
Jos video ylittää 150 MB:n rajan, automaattinen pakkaus voi laskea resoluutiota ja
bittinopeuksia. Ilman automaattista pakkausta kokorajan ylittävä lataus epäonnistuu.

Aaltomuodon piirto käyttää reunojen pehmennystä, näytteiden välistä interpolointia
ja FPS:n mukaan säätyvää suodatusta välkkymisen vähentämiseksi. Uusien asetusten
FPS-oletus on 30. Jos olet tallentanut aiemmin 15 FPS:n asetuksen, vaihda se
asetusikkunasta 30:een tai 60:een saadaksesi sulavamman liikkeen.

Aaltomuodot piirretään vain yläreunan viivoina ilman täyttöä tai alapuolista
peilausta. Viivan paikallinen peittävyys seuraa taajuuskaistan voimakkuutta;
hiljaiset kohdat jäävät himmeiksi. Hillitty väripaletti poimitaan kansikuvasta,
bassoa sävytetään punertavaksi ja korkeita taajuuksia viileämmiksi.

Aaltomuotoalue kattaa koko videon leveyden. Viivat häipyvät läpinäkyviksi ulomman 10 %:n matkalla kummassakin reunassa. Taustapaneeli on oletuksena pois käytöstä; sen voi kytkeä päälle SoundCloud-videon asetuksista ja säätää peittävyyttä.

Viivan paksuus määritetään 640 px:n peruskoossa ja skaalautuu videon mukana.
Kaistamäärä tukee myös yli kahdeksaa bändiä: analyysi ei käytä kaiutinkanavien
asettelua. Suuri kaistamäärä kasvattaa analyysin muistinkäyttöä ja renderöintiaikaa.

Kaistojen pystysijoittelu huomioi aaltojen enimmäiskorkeuden ja viivan paksuuden,
jotta myös basson huiput mahtuvat piirtoalueelle 30 bändillä. Viivojen peittävyyttä
on nostettu noin 30 % ja voimakkuusvaste käyttää neliöjuurikäyrää, jolloin myös
hiljaisempi ääni erottuu selvemmin; voimakkaimmat kohdat ovat täysin peittäviä.

## Leikepöytälatausten äänimerkit

GUI toistaa omat lyhyet WAV-äänimerkit, kun leikepöydältä käynnistetty lataus
alkaa, valmistuu tai epäonnistuu. Ne toimivat myös ikkunan ollessa piilossa.
Virhemerkki kuuluu myös silloin, kun taustaprosessia ei voida käynnistää tai se
kaatuu. Valmismerkki kuuluu vasta, kun tiedosto on tarkistettu ja siirretty
leikepöydälle (tai tallennettu, jos seuranta on sillä välin poistettu käytöstä).

Äänet voi poistaa käytöstä hallintapaneelin **Leikepöytälatausten äänimerkit**
-valinnasta. Valinta säilyy käyttökertojen välillä. Äänet ovat projektin omia,
eivät käyttöjärjestelmän ilmoitusääniä. Ne löytyvät `static/sounds/`-kansiosta:
`started.wav`, `finished.wav` ja `error.wav`. Voit vaihtaa ne omiin saman nimisiin
PCM WAV -tiedostoihin ja käynnistää GUI:n uudelleen. Äänien toisto ei pysäytä GUI:ta.

## GUI:n latauksen tilannekuva

Hallintapaneeli näyttää leikepöytälatauksen nykyisen työvaiheen, kokonaisajan,
vaiheen keston ja ajan viimeisestä tilapäivityksestä. Päättyneiden vaiheiden
kestot säilyvät näkyvissä seuraavan latauksen alkuun asti. SoundCloudin lataus
raportoi nopeuden, prosentit ja aika-arvion silloin, kun ne ovat saatavilla.
Videon muodostuksessa näkyvät valmistuneet ruudut, ruutujen käsittelynopeus ja
vaiheen etenemisprosentti. Prosentti koskee nykyistä vaihetta, ei koko latausta.
Vaiheet ilman mitattavaa prosenttia näyttävät liikkuvan odotuspalkin. Muiden
palvelujen verkkolataus näyttää vaihe- ja aikatiedot ilman tarkkaa prosenttia.

Tilapäivitykset kulkevat taustaprosessista GUI:hin vain `--progress`-valitsimella;
botin tavallinen toiminta ei tulosta niitä. Viimeisin päivitys -aika auttaa
havaitsemaan pitkän odotuksen, mutta ei yksin tarkoita prosessin jumittumista.

Aaltomuotojen piirto käyttää nyt renderöinnin sisäistä kuvapalavälimuistia:
kukin aikajakso piirretään kerran ja seuraavat ruudut kootaan vierittämällä
valmiita viivoja. Kunkin bändin muistissa säilytetään korkeintaan kolme
1024 pikselin kuvapalaa sekä nykyinen vieritysnäkymä; koko kappaletta tai
kaikkia videoruutuja ei varastoida kuviksi. Osapikselivieritys, reunahäivytys,
voimakkuuteen perustuva peittävyys ja kansikuvan värit säilyvät.

Renderöinnin **jumittumisraja** (oletuksena 300 s) mittaa aikaa viimeisestä
FFmpegille syötetystä ruudusta. Edistyvä renderöinti saa kestää tätä pidempään.
Sama raja suojaa myös viimeistelyä ruutujen syöttämisen jälkeen. Kokorajan
lisäpakkauksen kummallakin kierroksella on edelleen asetuksen mukainen aikaraja.
