# Wdrożenie testowej aplikacji na VM w Proxmox

Gotowy instalator dla nowej VM 104 na wskazanym hoście pve:
[PROVISION-PVE.md](PROVISION-PVE.md) i `provision_pve.py`.
Profil startowy tego instalatora to 2 vCPU, 2 GiB RAM i 40 GiB dysku;
ponownie sprawdza zasoby i chroni istniejące VM oraz kontenery.

Pakiet uruchamia panel School RMM, Gunicorn i Caddy z HTTPS oraz obowiązkowym MFA.
Nie instaluje jeszcze MeshCentral ani nie wykonuje zadań na komputerach Windows.
Kontenery aplikacji uruchamia się wewnątrz osobnej VM Linux, nie na hoście Proxmox.

## Stan połączenia z Proxmox

Węzeł wskazany przez właściciela: `pve`, API `https://192.168.0.250:8006`.
Próba odczytu API zatrzymała się na proxy środowiska (CONNECT 403), przed
połączeniem z Proxmox. Nie utworzono VM, nie zmieniono sieci ani istniejących maszyn.
Użytkownik wskazał SSH root@192.168.0.250:22 z istniejącym kluczem, jednak ten
klucz ani agent SSH nie są dostępne w tej sesji. Wymagane są połączenie VPN,
grant TCP 192.168.0.250/32, klucz/agent oraz zweryfikowany wpis hosta SSH.
Wcześniej zapisany wymóg tokenu API nie jest potrzebny przy wybranej ścieżce SSH.
Nie wystawiać panelu Proxmox do Internetu w celu obejścia tego wymagania.

## Przygotowanie nowej VM

Po uzyskaniu dostępu sprawdzić dostępne zasoby, storage, mosty i wolny VMID.
Chronić VM 100 GENAI, 101 cdu i 103 ai-server wraz z /srv/school-ai.
Skrypt `deploy/proxmox_preflight.py` zbiera stan na pve bez zmian w VM.
Użyć osobnej VM Ubuntu Server 24.04 LTS (4 vCPU, 8 GB RAM, 64 GB dysku),
o ile zasoby na to pozwolą. Nazwa i adres aplikacji są odrębne od adresu Proxmoxa.
Nie używać `192.168.0.250` jako adresu nowej aplikacji i nie instalować jej na hypervisorze.
Zainstalować Docker Engine z wtyczką Compose i Git ze zweryfikowanego źródła.
Instrukcja dostawcy: https://docs.docker.com/engine/install/ubuntu/.
Tych kroków nie wykonano jeszcze na zdalnym serwerze.

## Start na VM

Pobrać repozytorium i wejść do jego katalogu. Przy repozytorium prywatnym
użyć istniejącego bezpiecznego mechanizmu Git; nie umieszczać tokenów w URL.
Wybrać nazwę DNS kierującą do **nowej VM** albo jej przydzielony adres IP.

```sh
python3 deploy/init_deployment.py --hostname school-rmm.school.lan --bind-address 0.0.0.0
docker compose -f deploy/compose.yaml build
docker compose -f deploy/compose.yaml up -d --no-build --wait --wait-timeout 90
docker compose -f deploy/compose.yaml exec app python manage.py createsuperuser
```

Przykładowa nazwa school-rmm.school.lan nie jest założonym istniejącym DNS.
Parametr `--bind-address 0.0.0.0` udostępnia HTTPS na interfejsach VM; wcześniej
ograniczyć dostęp firewallem VM/Proxmox do sieci administratorów. Skrypt domyślnie
wiąże wyłącznie loopback. Nie modyfikuje firewalla ani konfiguracji Proxmoxa.

Konto jest imienne; hasło ustawia operator w terminalu. Przy pierwszym logowaniu
aplikacja wymaga skonfigurowania TOTP przez kod QR i potwierdzenia poprawnym kodem.
Zapisz kody odzyskiwania w bezpiecznym miejscu. Brak kont i haseł domyślnych.
Po konfiguracji samo hasło nie odblokowuje panelu ani Django admin.
Wyłączenie MFA przez WWW jest zablokowane; odzyskanie utraconego urządzenia wymaga
upoważnionego operatora serwera lub kodu odzyskiwania.

## Certyfikat HTTPS

Pakiet korzysta z prywatnego CA Caddy (`tls internal`), odpowiedniego dla laboratorium
i prywatnego DNS. W certyfikatach urządzeń administratorów należy zaufać temu CA.
Pobrać tylko **publiczny certyfikat główny**, po weryfikacji połączenia z VM:

```sh
docker compose -f deploy/compose.yaml cp proxy:/data/caddy/pki/authorities/local/root.crt ./school-rmm-ca.crt
```

Nie eksportować klucza prywatnego CA i nie wyłączać weryfikacji TLS w przeglądarce
ani w testach. Przed szerszym pilotażem można zastąpić prywatny CA istniejącym
zaufanym certyfikatem szkoły. Klucz CA i dane Caddy są trwałe w wolumenie.

## Sekrety, dane i aktualizacje

`deploy/.env` zawiera wyłącznie nazwę, adres nasłuchiwania i port. Wygenerowany
klucz aplikacji znajduje się w `deploy/runtime/django.key`, poza Git i obrazem.
Katalog runtime ma uprawnienia 0700, a sam plik 0444, by proces UID 10001 mógł
odczytać zamontowany sekret. Bez dostępu do katalogu inny użytkownik hosta nie
odczyta tego pliku. Nie udostępniać katalogu i nie drukować klucza.
Ponowne wykonanie init zachowuje klucz i odrzuca niezgodną istniejącą konfigurację.

Baza i konfiguracja TLS są w nazwanych wolumenach. Nie uruchamiać
`docker compose down --volumes`, ponieważ usuwa dane. Zwykły restart i odtworzenie
kontenerów zachowują dane. Przed aktualizacją wykonać backup, następnie build i up.
Migracje są wykonywane podczas startu; niepowodzenie zatrzymuje start aplikacji.
Rewersja obrazu nie cofa migracji — do odtworzenia poprzedniej wersji potrzebna
jest kopia bazy zgodna z tą wersją.

Proces aplikacji nie działa jako root, port 8000 nie jest wystawiony na hosta,
kod jest tylko do odczytu. Tylko Caddy przyjmuje ruch z sieci i zastępuje
zaufane nagłówki HTTPS i adresu klienta. Nazwy app/proxy i loopback są wyłączone
z ruchu przez ewentualne zewnętrzne proxy wyłącznie dla komunikacji lokalnej stosu.
Oba obrazy bazowe są przypięte digestem,
a pakiety Pythona wersją i hashami. Brak połączeń do CDN dla formularzy MFA.

## Kopia i odtworzenie

Po wybraniu unikalnej nazwy pliku (polecenie odrzuca nadpisanie):

```sh
docker compose -f deploy/compose.yaml exec app python manage.py backup_database --output /data/backup-YYYYMMDD.sqlite3
docker compose -f deploy/compose.yaml cp app:/data/backup-YYYYMMDD.sqlite3 ./backup-YYYYMMDD.sqlite3
```

Plik zawiera także sekrety TOTP i hashe haseł. Po skopiowaniu ustawić uprawnienia
0600 i przenieść zaszyfrowaną kopię poza VM. Osobno zachować klucz aplikacji i
dane Caddy w bezpiecznym magazynie. Kopia SQLite jest spójna mimo działającej bazy.
Retencję i automatyczne wysyłanie kopii należy skonfigurować po wyborze magazynu szkoły.

Próbę odtworzenia wykonać na drugiej, izolowanej VM: odtworzyć plik jako
`/data/school-rmm.sqlite3` z właścicielem UID/GID 10001 i trybem 0600 w jej
wolumenie, skonfigurować osobny adres, uruchomić właściwą wersję aplikacji,
sprawdzić integralność, logowanie MFA i dane. Nie nadpisywać działającej bazy.
Backup pliku przetestowano lokalnie; całej procedury odtworzenia VM jeszcze nie wykonano.

## Odbiór wdrożenia

Sprawdzić odpowiedź /healthz/, formularz logowania i style przez HTTPS ze
zweryfikowanym certyfikatem, pełny przebieg hasło + TOTP, blokadę bez TOTP,
tworzenie szkoły/sali/komputera, restart kontenerów, zachowanie danych i kopię.
Test środowiska Django: `docker compose -f deploy/compose.yaml exec app python manage.py check --deploy`.
Gotowość pakietu lokalnego nie oznacza jeszcze wykonania wdrożenia na Proxmox.

Lokalny test pełnego HTTPS i MFA z tymczasowym, automatycznie usuwanym kontem:
`.venv/bin/python deploy/verify_local.py` (po skopiowaniu publicznego CA do
`deploy/runtime/test-ca.crt`). Skrypt akceptuje wyłącznie adresy loopback;
nie służy do tworzenia kont kontrolnych na produkcji.
Opcja `--recreate` odtwarza oba lokalne kontenery i weryfikuje zachowanie sesji,
bazy oraz CA; ten scenariusz również przeszedł poprawnie.

W środowisku chmurowym do builda dostarczono tymczasowo publiczny pakiet CA
przez sekret BuildKit `proxy_ca` i PIP_CERT. Pakiet zaufania nie jest zapisywany
w warstwach obrazu. Zwykłe wdrożenie na VM z normalnym zaufaniem TLS nie wymaga
tego sekretu. W sieci z własnym proxy należy dostarczyć właściwy pakiet CA,
zachowując weryfikację TLS.
