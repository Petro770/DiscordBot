# Leikepöydän äänimerkit

Projektia varten syntetisoidut alkuperäiset äänet, ilman ulkopuolisia näytteitä
 tai käyttöjärjestelmän ääniä. Ei ulkopuolista attribuutiovaatimusta.

- started.wav: lyhyt kaksisävelinen aloitus
- finished.wav: nouseva kolmisävelinen valmistuminen
- error.wav: laskeva kolmisävelinen virhe

Muoto: mono PCM WAV, 44,1 kHz, 16 bit. Kesto alle sekunti.
Tiedostot voi vaihtaa omiin saman nimisiin PCM WAV -tiedostoihin.
Uudelleenluonti: `python -m tools.generate_notification_sounds`.
