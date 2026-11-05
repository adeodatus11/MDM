# Laboratorium Proxmox — przygotowanie do wdrożenia

Stan według wyników i aktualizacji operatora z 5 listopada 2026:
węzeł pve, Proxmox VE 9.2.24, lokalny adres 192.168.0.250. Operator utworzył
osobną VM 104 school-rmm (2 vCPU, 2 GiB RAM, 40 GiB local-zfs) przez instalator
z repozytorium. VM otrzymała 192.168.18.2; instalacja panelu nie jest ukończona.
Pierwszy start zatrzymał się na błędnym sprawdzeniu podsieci, a próba wznowienia
zakończyła się timeoutem guest-exec przed potwierdzeniem odczytu stanu gościa.
Nie odtwarzać VM 104; używać trybu wznowienia po diagnostyce agenta QEMU.

Chronione zasoby: VM 100 GENAI, VM 101 cdu i VM 103 ai-server (192.168.0.84).
Nie modyfikować tych VM ani /srv/school-ai i /srv/school-ai/stack/compose.yaml.
School RMM ma osobną VM 104; nie używać aiadmin/sudo do instalacji w VM 103.
Nie rezerwować innych VMID ani adresów przed odczytem stanu.

## Połączenie operatora przez Tailscale

Operator potwierdził działające SSH kluczem spoza szkolnej sieci:

```sh
ssh root@proxmox-pve.taila141c0.ts.net
```

- Urządzenie Tailscale: proxmox-pve, prywatny adres 100.113.160.27.
- Panel Proxmox: https://proxmox-pve.taila141c0.ts.net/ przez Tailscale Serve
  do localhost:8006, z prawidłowym certyfikatem według operatora.
- Funnel jest wyłączony. Router nie przekierowuje portów 22 ani 8006.
- Połączenie używa szyfrowanego relay waw, ponieważ sieć blokuje bezpośredni UDP.
- Zachować accept-dns=false. Nie włączać przejmowania DNS bez analizy wpływu na LXC.
- Nie zmieniać zdalnie vmbr0, VLAN-aware ani głównego interfejsu: host ma jeden aktywny NIC.
- Nie usuwać ani nie resetować Tailscale bez przygotowania alternatywnego dostępu.

Ten dostęp służy utrzymaniu infrastruktury. School RMM pozostaje dostępny wyłącznie
z LAN 192.168.16.0/22. Nie publikować go przez Serve, Funnel ani tunel SSH.
Zmiana sieci Maca nie zmienia docelowego --school-lan. Timeout guest-exec dotyczy
komunikacji pve z gościem przez agenta QEMU; wolniejszy relay nie potwierdza jego
przyczyny. Najpierw odczytać stan VM, guest-ping i proste guest-exec, bez resetu VM.

## Dostęp z sesji chmurowej

Ostatni odczyt konfiguracji tej sesji: vpn_configured=false, brak grantów TCP,
brak skonfigurowanych poświadczeń oraz agenta SSH. Nie oznacza to awarii dostępu
operatora. Można kontynuować przez jego Maca i sprawdzone SSH powyżej.
Ewentualne połączenie bezpośrednio z chmury wymaga odrębnego dołączenia środowiska
do Tailscale, grantu TCP na wskazany host i bezpiecznego powiązania klucza/zweryfikowanego
wpisu SSH. Nie wysyłać klucza prywatnego w czacie ani zapisywać go w repozytorium.
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

- Istniejąca osobna VM 104 Ubuntu Server 24.04 LTS, 2 vCPU, 2 GiB RAM, 40 GiB dysku.
- Oddzielna sieć testowa i cztery VM Windows z legalnymi licencjami.
- Usługa School RMM jako użytkownik nieuprzywilejowany, Gunicorn za reverse proxy TLS.
- Osobna usługa MeshCentral, niezależne wersje, katalog danych i backup.
- Panel School RMM dostępny wyłącznie z LAN 192.168.16.0/22; Proxmox ma odrębny dostęp Tailscale.
- Snapshot przed instalacją i potwierdzony backup z odtworzeniem.

Właściciel zlecił instalację i naprawę osobnej VM School RMM. Zachowujemy dane,
wykonujemy snapshot przed naprawą i nie kasujemy istniejących VM.

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
