# Haarat ja julkaisut

Noudata tätä ohjetta kaikissa projektin haaroissa.

## Työhaara

- Tarkista lähtöhaara ja nykyinen julkaisuversio (`BOT_VERSION` tiedostossa
  `config.py`) ennen työn aloittamista.
- Päivitä muuttuneen toiminnon ohje README.md:ssä ja uudet tai muuttuneet
  ympäristöasetukset tiedostossa `example.env`. Päivitä tarvittaessa myös
  Discordin komento-ohjeet (`core/help.py`) ja AI:n käyttöohjeet
  (`instructions/discord-assistant.md`).
- Kirjaa käyttäjälle näkyvät ominaisuudet, korjaukset ja toimintatapojen muutokset
  haaran yhteenvedossa tai pull requestissa. Kerro mitä testattiin.
  Kehityshaaran testaus ei itsessään nosta julkaisuversiota.

## Ennen yhdistämistä päähaaraan

- Vertaa yhdistettävää sisältöä uusimpaan `main`-haaraan. Varmista, että ohjeet
  vastaavat tulosta ja mahdolliset käyttöönottovaiheet on kirjattu.
- Nosta käyttäjälle näkyvän julkaisun `BOT_VERSION` kerran yhdistettävässä
  muutoksessa. Käytä korjaukselle seuraavaa patch-versiota, yhteensopivalle
  uudelle ominaisuudelle seuraavaa minor-versiota ja rikkovalle muutokselle
  seuraavaa major-versiota. Pelkät sisäiset muutokset eivät vaadi versionnostoa.
- Lisää sama versio `changelog.json`-tiedoston `versions`-listan loppuun
  julkaisupäivällä muodossa `YYYY-MM-DD`. Kirjaa vain kyseisessä julkaisussa
  mukana olevat muutokset. Kirjoita lyhyet suomenkieliset kuvaukset ja käytä
  tyyppiä `feat`, `fix`, `improve` tai `break`. Botti käyttää näitä
  versiosaatteita käyttäjäilmoituksissaan.
- Tarkista JSONin kelvollisuus, version ja uusimman changelog-merkinnän
  vastaavuus sekä muuttuneiden toimintojen testit ennen yhdistämistä.
  Tarkista yhdistämisen jälkeen, että oikea commit näkyy etävaraston
  `main`-haarassa.
