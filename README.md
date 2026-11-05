# School RMM

Rozpoczęta aplikacja do zarządzania komputerami szkolnymi Windows 10/11 Home/Pro.
Stan: **działający lokalny etap 1 — panel ewidencji i oceny zgodności**.
Kod znajduje się w tym repozytorium; wdrożenie na Proxmox nie zostało jeszcze wykonane.

## Co działa

- Logowanie imiennym kontem Django, ochrona CSRF i ograniczenie prób logowania.
- Szkoła → budynek → piętro → sala → komputer.
- Ręczne dodawanie komputerów, inwentaryzacja i import raportów JSON.
- Rozdzielenie dostępu między szkołami; administrator główny, administrator szkoły i technik.
- Macierz możliwości Home/Pro, podgląd zgodności polityk i powody ograniczeń.
- Ostrzeżenia dla Windows 10 bez ESU, osobny stan niepotwierdzonego ESU, termin ważności i źródło weryfikacji.
- Filtry urządzeń, sal i raportu CSV, tylko do odczytu API oraz historia dodawania/importu.
- Dane demonstracyjne czterech wariantów Windows, wyraźnie oznaczone TEST.

## Uruchomienie lokalne

Wymagany Python 3.12+. Polecenia wykonuj w katalogu repozytorium:

```sh
python3 -m venv .venv
.venv/bin/pip install --require-hashes -r requirements.txt
export SCHOOL_RMM_DEBUG=true
.venv/bin/python manage.py migrate
.venv/bin/python manage.py createsuperuser
.venv/bin/python manage.py runserver 127.0.0.1:8000 --noreload
```

`createsuperuser` pyta o dane w terminalu. Nie ma domyślnego konta ani hasła.
Lokalny klucz sesji powstaje w ignorowanym `var/`, z ograniczonym dostępem do pliku.
Tryb DEBUG służy wyłącznie do izolowanych testów, nigdy do udostępnienia w sieci szkoły.

Po zalogowaniu administrator główny tworzy szkołę i salę w administracji.
Zwykłe konta dodaje się do `Membership`, z rolą i szkołą. Nie nadaje się im
uprawnień superużytkownika. Panel nauczyciela jest osobnym przyszłym etapem;
rola nauczyciela nie daje obecnie dostępu do panelu ewidencji.

Opcjonalne, powtarzalne dane testowe (nie tworzą kont):

```sh
SCHOOL_RMM_DEBUG=true .venv/bin/python manage.py seed_demo
```

## Inwentaryzacja testowego Windows

W PowerShell 5.1+ na **upoważnionej testowej VM**:

```powershell
.\scripts\Collect-Inventory.ps1 -OutputPath "$env:TEMP\school-rmm-inventory.json"
```

Skrypt odczytuje dane systemu i sprzętu oraz zapisuje nowy plik. Nie zmienia
ustawień Windows, nie instaluje agenta i nie przesyła danych przez sieć.
Nie nadpisuje istniejącego raportu. Wykonanie na Windows wymaga jeszcze testu
w pilotażu — w tym środowisku dostępny jest Linux.

Po kontrolowanym przeniesieniu raportu do serwera (ID sali znajdziesz w administracji):

```sh
SCHOOL_RMM_DEBUG=true .venv/bin/python manage.py import_inventory /path/to/report.json --room 1
```

Import jest atomowy i aktualizuje wpis według sali i nazwy. Zmiana systemu lub
kompilacji unieważnia wcześniejsze potwierdzenie ESU. Raport nie może nadawać
uprawnień, potwierdzać ESU ani deklarować dostępności zdalnych funkcji.
W środowisku produkcyjnym polecenia uruchamia się z konfiguracją produkcyjną,
bez `SCHOOL_RMM_DEBUG=true`.

## Sprawdzenie działania

```sh
SCHOOL_RMM_DEBUG=true .venv/bin/python manage.py test
SCHOOL_RMM_DEBUG=true .venv/bin/python manage.py check
SCHOOL_RMM_DEBUG=true .venv/bin/python manage.py makemigrations --check --dry-run
.venv/bin/pip check
```

`GET /healthz/` sprawdza połączenie z bazą. Uwierzytelnione `GET /api/devices/`
zwraca dane wyłącznie z dozwolonych szkół. API korzysta z sesji Django.
Obsługuje filtry `q`, `school`, `room`, `os_version`, `os_edition`, `support_status`,
`policy` i `compliance`, wspólne dla panelu i `GET /reports/devices.csv`.
`capabilities` jest wyliczane na serwerze, a `connection_status` pozostaje
`not_connected` do czasu rzeczywistego podłączenia integracji.

## Dalsze prace i wdrożenie

Plan i kryteria odbioru: [docs/ROADMAP.md](docs/ROADMAP.md).
Weryfikacja komponentów i licencji: [docs/COMPONENTS.md](docs/COMPONENTS.md).
Wymagania i kontrakt Windows: [docs/WINDOWS.md](docs/WINDOWS.md).
Przygotowanie Proxmoxa: [docs/PROXMOX.md](docs/PROXMOX.md).

Zdalny pulpit, terminal, wykonanie skryptów, restart, automatyczna rejestracja
agentów i wdrażanie polityk **nie są jeszcze zaimplementowane**. Panel pokazuje
ten stan wprost. MFA, pełny audyt operacji zdalnych, TLS na serwerze, kopie
zapasowe z odtwarzaniem i bezpieczna integracja agentów są wymagane przed pilotażem
w szkolnej sieci. Obecna wersja nie jest gotowa do produkcyjnego zarządzania flotą.
