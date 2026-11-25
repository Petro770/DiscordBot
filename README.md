# DiscordBot

DiscordBot on Pythonilla tehty Discord-botti, joka käsittelee kuvia ja medialinkkejä yksityisviesteissä ja määritetyllä palvelinkanavalla. Botti lataa mediaa YouTubesta, Instagramista, X:stä, TikTokista, Twitchistä ja SoundCloudista, pakkaa tarvittaessa videoita ja lähettää tuloksen Discordiin. Botti lähettää SoundCloud-kappaleen MP4-videona, jossa kansikuva näkyy koko ajan ja kappaleen nimi sekä artisti ensimmäiset viisi sekuntia. Jos videota ei saada tehtyä tai se ylittää Discordin kokorajan, botti käyttää MP3-tiedostoa. Kuvia voi myös tulostaa Windowsissa emoji-reaktiolla.

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

## Päivittäminen hallintapaneelista

Avaa hallintapaneeli ja paina **Tarkista versio…**. Paneeli hakee
`origin`-etävaraston haarat ja näyttää nykyisen haaran sekä commitin. Haarakorteissa
näkyvät viimeisimmän commitin otsikko, tekijä, päivämäärä ja tunniste.
Valitse yksi kortti ja paina **Päivitä ja käynnistä uudelleen**. Paneeli pysäyttää botin, päivittää
Git-työkopion ja avaa itsensä uudelleen samalla Python-ympäristöllä.
Botti käynnistyy uudelleen, jos se oli käynnissä ennen päivitystä.

Toiminto tarvitsee Gitin ja Gitillä kloonatun projektin. Päivitys odottaa,
että medialataus on päättynyt. Paikalliset muutokset ja etähaarasta
poikkeavat paikalliset commitit pitää käsitellä Gitillä ennen päivitystä.
Jos valittu haara tarvitsee uusia Python-riippuvuuksia, asenna ne
projektin `install.ps1`-skriptillä.

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
Kokeile Discordissa esimerkiksi `@Botti Miksi taivas on sininen?`.
Botti vastaa suoraan viestiin yksityisviesteissä ja sallituilla palvelinkanavilla.
Oletuksena sallittu kanava on `TARGET_CHANNEL_ID`. Voit antaa useita
kanavatunnisteita pilkulla eroteltuina asetuksessa `OLLAMA_CHANNEL_IDS`.
Sallittu yläkanava sallii myös sen ketjut ja foorumipostaukset.
Tyhjä `OLLAMA_CHANNEL_IDS=` sallii vain yksityisviestit. Jos rivi puuttuu,
käytetään `TARGET_CHANNEL_ID`-asetusta. Käynnistä botti uudelleen muutosten jälkeen.
Käynnistysloki näyttää käytössä olevan kanavalistan ja sen lähteen. Maininnoista
loki kertoo, hyväksyttiinkö viesti, mitä palvelimia ja malleja kokeiltiin ja
saatiinko vastaus lähetettyä Discordiin.

`OLLAMA_HOSTS` sisältää palvelinten osoitteet kokeilujärjestyksessä.
Oletusosoitteet ovat `192.168.1.11`, `192.168.1.12` ja `192.168.1.13`
portissa `11434`. Botti hakee asennetut mallit kultakin palvelimelta,
kun `OLLAMA_MODELS` on tyhjä tai sisältää vain huutomerkillä merkittyjä
poissulkuja. Esimerkiksi `OLLAMA_MODELS=!qwen3:4b,!toinen-malli:latest`
ohittaa nämä mallit kaikilla palvelimilla. Käytä tarkkoja mallinimiä
tageineen sellaisina kuin Ollama ilmoittaa ne.

Ilman huutomerkkiä annetut nimet muodostavat kokeilulistan. Jos sama nimi
on sekä kokeilulistalla että poissuljettu, poissulku voittaa. Botti käyttää
ensimmäistä onnistunutta vastausta. Seuraava tekstivuoro samassa kanavassa,
ketjussa tai yksityisviestikeskustelussa yrittää ensin viimeksi toiminutta
palvelinta ja mallia. Epäonnistuessa botti kokeilee varamalleja jäljellä
olevan aikarajan puitteissa. Kuvamallit ohitetaan tekstipyynnöissä, kun
Ollama ilmoittaa mallille kuvatukea. Lokista näkee vastanneen parin.

Botti lähettää Ollamalle ohjeet, mainintaviestin tekstin ja
tunnistettujen henkilöiden näyttönimet ja roolit. Se tunnistaa kirjoittajan,
enintään 12 Discordin ilmoittamaa mainintaa ja samassa kanavassa vastatun
viestin kirjoittajan. Maininnat välitetään mallille viitteinä, jotka botti
muuntaa vastauksessa Discord-maininnoiksi ilman pingiä. Mukaan voi tulla lyhyitä katkelmia aiemmista Ollama-vuoroista
samassa keskustelussa.

Kokeile esimerkiksi `@Botti sano @Käyttäjä että aloitetaan kahdeksalta`
tai vastaa henkilön viestiin tekstillä `@Botti kerro hänelle että aloitetaan
kahdeksalta`.
Vapaat Ollama-palvelimet käsittelevät kysymyksiä rinnakkain, enintään yksi
kysymys palvelinta kohti. Saman kanavan tai yksityisviestikeskustelun
vuorot käsitellään saapumisjärjestyksessä, jotta seuraava vastaus saa
käyttöönsä edellisen vuoron. Botti voi pitää
käsittelypaikkojen lisäksi enintään 20 viestiä jonossa tai odottamassa omaa
vastausvuoroaan. Täyden jonon merkkinä botti reagoi uuteen viestiin 🚫.
Kokonaisaika alkaa viestin päästessä käsittelyyn. Botin koneen pitää päästä
Ollama-palvelimiin lähiverkosta. Yhteyden voi tarkistaa botin koneelta
esimerkiksi PowerShellissä komennolla
`Invoke-RestMethod http://192.168.1.11:11434/api/tags`.
Jos Ollama kuuntelee vain paikallisia yhteyksiä, määritä palvelimella
`OLLAMA_HOST` kuuntelemaan lähiverkon osoitetta.

Botti hakee oletuksena enintään 12 aiempaa viestiä samasta kanavasta,
ketjusta tai yksityisviestikeskustelusta ja välittää tekstikatkelmat
Ollamalle taustatietona. Bottiviestit ja botille osoitetut AI-kysymykset
ohitetaan tässä haussa. Aseta `OLLAMA_RECENT_MESSAGES=0`, jos haluat
käyttää vain botin omia AI-vuoroja. Asetuksen vaihteluväli on 0–30.
Haku käyttää botin viestihistorian lukuoikeutta.

### AI-keskustelujen seuranta

Hallintapaneelin **AI-keskustelut…**-ikkunassa näkyvät aktiiviset ja
viimeisimmät pyynnöt, malliyritykset, aikakatkaisut ja Discord-lähetys.
Valitse keskustelu ja pyyntö nähdäksesi aikajanan. **Kopioi vianetsintätiedot**
kopioi valitun pyynnön tapahtumat ilman viestitekstejä. Tekstijäljitys näyttää
mallin syötteen, raakavastaukset ja lähetetyn tekstin, kun
`OLLAMA_TRACE_ENABLED=true`. Näkymä kerää tapahtumia paneelin käynnistyksestä.

### Ollaman jäljitysloki

Aseta `OLLAMA_TRACE_ENABLED=true` tiedostoon `.env` ja käynnistä botti
uudelleen. Toista ongelma ja etsi `core/ollama_trace.jsonl`-tiedostosta
saman `message_id`-tunnisteen rivit. Niissä näkyvät tägäys, mallille annettu
tekstisyöte ja istuntomuisti, mallivalinta, raaka vastausteksti, jäsennetty
vastaus ja Discordiin lähetetty teksti. Kuvadataa ei tallenneta.
Jäljitys kattaa Ollama-vastaukset sallituissa kanavissa ja yksityisviesteissä.

Tiedosto kiertää noin 2 Mt:n välein ja säilyttää kaksi edellistä tiedostoa.
Vaihda asetus takaisin arvoon `false` ja käynnistä botti uudelleen, kun
testi on valmis. Vanhat tiedostot voi poistaa käsin. Tarkista ja peitä
yksityiset viestit, nimet ja tunnisteet ennen jäljitysrivien jakamista.

### Kuvien tulkinta

Liitä kuva samaan viestiin botin maininnan kanssa, esimerkiksi
`@Botti mitä tässä kuvassa näkyy?`. Pelkkä maininta ja kuvaliite pyytää
lyhyen kuvauksen. Botti käyttää ensimmäistä sopivaa JPEG-, PNG- tai
WebP-liitettä, jonka koko on enintään 8 Mt.

Ollama-palvelimella pitää olla asennettuna malli, joka ilmoittaa
`vision`-tuen `/api/show`-vastauksessa. Jos käytät `OLLAMA_MODELS`-kokeilulistaa,
pidä listassa vähintään yksi kuvamalli. Botti ohittaa tekstimallit
kuvapyynnöissä. Kuvavuoro ei vaihda keskustelun tekstimallia. Kuvadata lähetetään mallille vain tämän pyynnön yhteydessä.
Keskustelumuistiin voi jäädä katkelma botin tekstivastauksesta.

### Mallien prioriteetti

`OLLAMA_CHAT_PRIORITY` ja `OLLAMA_VISION_PRIORITY` ovat erilliset, pilkulla
erotetut listat tarkoista mallinimistä. Botti kokeilee käynnissä olevan
tekstikeskustelun palvelin–malliparia ensin. Sen jälkeen se kokeilee
prioriteettilistan ensimmäistä mallia sallituilla palvelimilla ennen
listan seuraavaa mallia. Jos lista on tyhjä tai yksikään sen malleista
ei vastaa, tavallinen mallihaku jatkuu jäljellä olevan aikarajan puitteissa.

`OLLAMA_MODELS`-kokeilulista, `!malli`-poissulut ja kuvatukirajaus pätevät
myös prioriteettilistoihin. Asetusten muutokset tulevat voimaan botin
uudelleenkäynnistyksessä.

### Ollaman aikarajat

Aseta aikarajat `.env`-tiedostossa sekunteina ja käynnistä botti uudelleen.

| Asetus | Oletus | Vaikutus |
| --- | ---: | --- |
| `OLLAMA_CONNECT_TIMEOUT_SECONDS` | 3 | Yhteyden avaaminen chat-pyynnössä. |
| `OLLAMA_DISCOVERY_TIMEOUT_SECONDS` | 5 | Yhden palvelimen mallilistan haku yhteyden avauksineen. Käytössä automaattisessa mallihaussa. |
| `OLLAMA_MODEL_TIMEOUT_SECONDS` | 40 | Yksi chat-pyyntö yhteyden avauksesta valmiiseen vastaukseen. |
| `OLLAMA_TOTAL_TIMEOUT_SECONDS` | 120 | Koko Ollama-kierros, mallilistojen haut ja varayritykset mukaan lukien. |

Mallin aikarajan ylittyessä botti kokeilee seuraavaa vaihtoehtoa, jos
kokonaisaikaa on jäljellä. Jos haluat antaa kolmelle malliyritykselle
kullekin 120 sekuntia, aseta esimerkiksi
`OLLAMA_MODEL_TIMEOUT_SECONDS=120` ja `OLLAMA_TOTAL_TIMEOUT_SECONDS=400`.

### Botin persoona ja ohjeet

[instructions/discord-assistant.md](instructions/discord-assistant.md) sisältää puhetyylin ja ohjeet botin
Discord-toiminnoista. Kokeile esimerkiksi `@Botti mitä osaat?` tai
`@Botti miten laitan repostausvaroitukset yksityisviesteihin?`.
Botti saa lisäksi tiedon käytössä olevista medialatauspalveluista,
kuvatulostuksesta ja liiteindeksoinnista.

Ollama voi muotoilla keskusteluun sopivan lyhyen tyyliohjeen samalla,
kun se vastaa. Botti säilyttää kanavaa tai yksityisviestikeskustelua kohti
uusimman tyyliohjeen ja lyhyet katkelmat kahdeksasta viimeisestä onnistuneesta
AI-vuorosta. Botti lähettää katkelmat Ollamalle erillisinä käyttäjän ja
avustajan viesteinä, jotta malli voi jatkaa keskustelua. Muisti tyhjenee, kun botti
käynnistetään uudelleen.

Kirjoita Discordissa `/ai-tyyli`, niin botti näyttää kanavalla juuri tämän
keskustelun aktiiviset tyyliohjeet. Komento lukee ne suoraan botin muistista.

Jos haluat omat ohjeet, kopioi oletusohje UTF-8-tiedostoksi, muokkaa
sitä ja aseta `OLLAMA_INSTRUCTIONS_FILE=instructions/local.md` tiedostoon
`.env`. Suhteellinen polku alkaa projektikansiosta. Käynnistä botti uudelleen
ladataksesi muutokset. Git ohittaa tiedoston `instructions/local.md`.
Kirjoita Discordissa esimerkkien `@Botti`-maininnan tilalle oman bottisi maininta.

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
