# Weryfikacja pierwszego etapu

Środowisko: Linux w izolowanym środowisku chmurowym, Python 3.12.14.
Data: 5 listopada 2026. Nie wykonywano połączeń do Proxmoxa ani poleceń na szkolnych komputerach.

- Migracje bazy utworzone i wykonane na lokalnym SQLite.
- `manage.py check`: brak problemów.
- `manage.py makemigrations --check --dry-run`: brak niezapisanych zmian modelu.
- `pip check`: brak niespełnionych zależności.
- Instalacja z `requirements.txt` i `--require-hashes`: poprawna dla bieżącego środowiska.
- 28 testów modeli i widoków: poprawne. Sprawdzają cztery warianty Windows,
  ESU, granice szkół i ról, CSRF, XSS, raport CSV, atomowy import,
  powtarzalne dane testowe, logowanie i blokadę wielokrotnych błędnych prób.
- Test przez prawdziwy lokalny serwer HTTP: poprawny. Logowanie, dodanie wpisu
  dla każdego z czterech wariantów systemu i odczyt filtrowanego API.
- Uruchomiony serwer lokalny: `GET /healthz/` zwraca HTTP 200,
  `status=ok` i `meshcentral=not_connected`.

W sandboxie gniazda sieciowe są zablokowane; po uzyskaniu uprawnienia do lokalnego
serwera ponowiono test HTTP i uruchomienie usługi z powodzeniem. Nie zmieniano
polityki sieciowej ani weryfikacji TLS.

Niewykonane: instalacja i działanie agentów Windows, uruchomienie PowerShell na
Windows, wykrywanie ESU z systemu, zdalne operacje, testy 5–10 VM, wdrożenie
Proxmox, pełne odtworzenie VM, obciążenie 300 urządzeń i odtworzenie środowiska
z opublikowanego snapshotu. Przekazanie tej wersji nie oznacza gotowości produkcyjnej.

## Pakiet wdrożeniowy

- Łącznie 41 testów: 29 dotychczasowych i 12 nowych dotyczących MFA, proxy i kopii SQLite.
  Pełny przebieg pierwszego logowania, wygenerowania QR i potwierdzenia TOTP sprawdzono dodatkowo.
- Zbudowano obraz Docker z przypiętym digestem Pythona i hashowanymi zależnościami;
  weryfikacja TLS pozostała aktywna, publiczny pakiet CA podano tymczasowo przez BuildKit.
- Uruchomiono Gunicorn i Caddy w osobnych kontenerach; tylko HTTPS proxy jest publikowane.
- Test prawdziwego HTTPS zweryfikował certyfikat przez zaufany CA, style,
  logowanie hasłem + TOTP oraz uwierzytelnione API. Tymczasowe konto kontrolne usunięto.
- Odtworzenie obu kontenerów zachowało bazę, klucz sesji, CA i uwierzytelnioną sesję MFA.
- `check --deploy`: jedna uwaga W021 o braku HSTS preload. Prywatny DNS i prywatny CA
  nie są przeznaczone do publicznej listy preload; ustawienie pozostaje wyłączone świadomie.
- Test kopii SQLite zweryfikował integralność, odczyt zachowanego rekordu i odmowę nadpisania.
- Proxmox pozostaje niedostępny: proxy zwróciło CONNECT 403; nie dotarto do jego API.
  Nie ma tu klucza/agenta SSH ani VPN. Sam wskazany adres i dane VM nie zapewniają połączenia.
