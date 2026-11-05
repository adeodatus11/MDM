# Laboratorium Proxmox — przygotowanie do wdrożenia

Nie wykonano żadnych zmian na Proxmox ani na rzeczywistych komputerach szkoły.
W tej sesji nie ma adresu Proxmoxa, sekretów, VPN ani dostępu do projektu PROXMOX AI.
Użytkownik wskazał ten projekt jako źródło dostępów, lecz jego zawartość nie jest
automatycznie dostępna z innej rozmowy/środowiska.

## Połączenie

Udostępnić w tej sesji adres API, nazwę węzła i bezpieczne połączenie sieciowe.
Poświadczenia wprowadzić przez ustawienia środowiska — nigdy do repozytorium
ani czatu. Jeżeli Proxmox jest w prywatnej sieci, wymagana jest skonfigurowana
trasa/VPN platformy i pozwolenie na konkretny cel. Dla samopodpisanego TLS
potrzebny jest właściwy certyfikat CA; nie wyłączać weryfikacji certyfikatów.
Sprawdzić najpierw odczyt API wersji, węzłów, zasobów i storage. Nie używać
przypadkowego VMID ani nie modyfikować istniejących serwerów.

## Docelowe laboratorium

Domyślny punkt startu, do sprawdzenia względem wolnych zasobów:

- Osobna VM Ubuntu Server 24.04 LTS, 4 vCPU, 8 GB RAM, 64 GB dysku.
- Oddzielna sieć testowa i cztery VM Windows z legalnymi licencjami.
- Usługa School RMM jako użytkownik nieuprzywilejowany, Gunicorn za reverse proxy TLS.
- Osobna usługa MeshCentral, niezależne wersje, katalog danych i backup.
- Panele administracyjne dostępne wyłącznie z dozwolonej sieci/VPN.
- Snapshot przed instalacją i potwierdzony backup z odtworzeniem.

Samo posiadanie dostępu nie oznacza zgody na zmiany produkcji. Tworzymy nowe,
odizolowane zasoby testowe po potwierdzeniu ich miejsca; nie kasujemy istniejących VM.

## Przed wystawieniem panelu w sieci

Ustawić SCHOOL_RMM_SECRET_KEY bezpiecznie poza repo, SCHOOL_RMM_DEBUG=false,
SCHOOL_RMM_ALLOWED_HOSTS i docelowy katalog SCHOOL_RMM_DATA_DIR. Zapewnić
HTTPS oraz poprawną obsługę nagłówka protokołu wyłącznie od zaufanego proxy;
obecna wersja nie zawiera jeszcze konfiguracji reverse proxy.
Wdrożyć MFA, konfigurację statycznych plików, monitoring i kopie zapasowe.
Uruchomić `manage.py check --deploy` i testy, sprawdzić logowanie,
odseparowanie szkół, restart i odtworzenie. Dopiero potem instalować agenty na VM.

Ta instrukcja jest planem wdrożenia; nie udaje przetestowanej automatyzacji Proxmoxa.
