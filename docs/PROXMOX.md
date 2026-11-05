# Laboratorium Proxmox — przygotowanie do wdrożenia

Nie wykonano żadnych zmian na Proxmox ani na rzeczywistych komputerach szkoły.
Węzeł: pve, adres 192.168.0.250, SSH root@192.168.0.250:22 z istniejącym kluczem.
W tej sesji nie ma tego klucza, agenta SSH ani połączenia VPN do prywatnej sieci.
Próba API https://192.168.0.250:8006 zatrzymała się na proxy środowiska: CONNECT 403.
Użytkownik wskazał projekt PROXMOX AI jako źródło dostępów, lecz jego zawartość
nie jest automatycznie dostępna z innej rozmowy/środowiska.

Chronione zasoby: VM 100 GENAI, VM 101 cdu i VM 103 ai-server (192.168.0.84).
Nie modyfikować tych VM ani /srv/school-ai i /srv/school-ai/stack/compose.yaml.
School RMM ma dostać osobną nową VM; nie używać aiadmin/sudo do instalacji w VM 103.
Nie rezerwować VMID ani adresu nowej VM przed odczytem stanu.

## Połączenie

Udostępnić tej sesji istniejący klucz/agent SSH oraz zweryfikowany wpis hosta,
bez wysyłania klucza prywatnego w czacie ani zapisywania go w repozytorium.
Wymagana jest trasa/VPN platformy i grant TCP 192.168.0.250/32 do SSH.
Klucz dostępny tylko na komputerze użytkownika lub w innym projekcie nie jest
automatycznie dostępny w tej sesji. Token API jest alternatywą, nie wymogiem
wybranej ścieżki SSH; zapisane wcześniej wymaganie PVE_API_TOKEN można usunąć
z konfiguracji środowiska przy przejściu na SSH. Dla samopodpisanego TLS
potrzebny jest właściwy certyfikat CA; nie wyłączać weryfikacji certyfikatów.
Sprawdzić najpierw stan przez pvesh po SSH lub skrypt deploy/proxmox_preflight.py
(uruchamiany na pve wyłącznie do odczytu). Nie używać
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
pakiet deploy/compose.yaml zawiera Caddy, HTTPS, pliki statyczne i MFA.
Instrukcja instalacji i kopii bazy: deploy/README.md.
Monitoring i automatyczny backup poza VM wymagają konfiguracji docelowego magazynu.
Uruchomić `manage.py check --deploy` i testy, sprawdzić logowanie,
odseparowanie szkół, restart i odtworzenie. Dopiero potem instalować agenty na VM.

Ta instrukcja jest planem wdrożenia; nie udaje przetestowanej automatyzacji Proxmoxa.
