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
Proxmox, MFA, backup z odtwarzaniem, obciążenie 300 urządzeń i odtworzenie środowiska
z opublikowanego snapshotu. Przekazanie tej wersji nie oznacza gotowości produkcyjnej.
