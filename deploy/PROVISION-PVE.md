# Instalator i wznowienie VM 104 na pve

`provision_pve.py` uruchamia operator w istniejącym terminalu `root@pve`.
To alternatywa dla dostępu SSH z sesji chmurowej. Skrypt nie jest wykonany przez
samo zapisanie go w repozytorium ani przez lokalne testy.

Przygotowano go na podstawie raportu właściciela z 5 listopada 2026:
VM 100 GENAI, 101 cdu i 103 ai-server działają; local-zfs ma wolną przestrzeń,
vmbr0 jest mostem, adres zarządzania pve wynosi 192.168.0.250, a wolny VMID wynosił 104.
Interfejs veth102 wskazuje także kontener — instalator sprawdza wszystkie VM i LXC.
Późniejszy odczyt z Maca potwierdził 192.168.17.206 z maską 255.255.252.0,
czyli szkolny LAN **192.168.16.0/22**, brama 192.168.16.1. VM 104 otrzymała
192.168.18.2. Oba adresy klientów należą do tego LAN; adres zarządzania pve
nie określa sieci klientów DHCP. Pierwszy instalator zatrzymał się po wypakowaniu
źródeł z powodu błędnego warunku 192.168.0.x. VM i jej dysk zachowano.

## Co robi

- Ponownie sprawdza zajęte ID, storage, sieć, aktualny RAM i sumę ustawionych limitów RAM.
- Wymaga 3 GiB rezerwy poza limitami działających gości; nie zmniejsza RAM serwera AI.
- W zwykłym trybie tworzy wyłącznie nową VM 104: 2 vCPU, 2 GiB RAM, 40 GiB na local-zfs, DHCP na vmbr0.
  W trybie `--resume` pracuje na istniejącej VM oznaczonej przez ten instalator.
- Przed utworzeniem gościa pobiera obraz Ubuntu 24.04 z oficjalnego HTTPS,
  sprawdza SHA256SUMS oraz format obrazu. Niezgodność zatrzymuje pracę.
- Pobieranie na pve używa curl --ipv4, a APT w nowej VM otrzymuje Acquire::ForceIPv4.
  Wynik diagnostyki właściciela: IPv4 i HTTPS działają, AF_UNSPEC zwraca EAI_AGAIN,
  proxy HTTPS nie jest skonfigurowane. Nie zmienia to DNS ani ustawień IPv6 hosta pve.
  Zachowuje weryfikację TLS, podpisy pakietów i kontrolę SHA256.
- Używa przypiętej, sprawdzonej wersji aplikacji 32f52e4 oraz SHA256 archiwum.
- Dodaje odrębny storage wyłącznie na snippet cloud-init tej VM; nie zmienia local/local-zfs.
- Zapisuje raport stanu, tworzy snapshot nowej VM przed jej pierwszym uruchomieniem.
- Instaluje Docker i agenta QEMU wewnątrz nowej VM przez podpisane repozytoria Ubuntu.
- Przenosi wyłącznie publiczne wpisy z /root/.ssh/authorized_keys do konta utrzymaniowego
  rmmadmin w nowej VM; prywatne klucze pozostają na swoich komputerach. Gdy pliku nie ma,
  obsługa jest dostępna przez agenta QEMU. Logowanie hasłem i SSH root w VM są wyłączone.
- Uruchamia HTTPS i MFA; panel i SSH nowej VM przyjmują wyłącznie klientów
  z jawnie wskazanej sieci szkolnej `--school-lan` (tutaj 192.168.16.0/22).
  Nie dopuszcza automatycznie klienta SSH spoza LAN,
  adresów VPN ani publicznych IP. Zarządzanie po IPv6 jest zablokowane w tym profilu IPv4.
- Zapora jest wymagana przed startem Dockera i jest odtwarzana przy jego restarcie.
  Wykorzystuje DOCKER-USER, ponieważ samo filtrowanie INPUT nie chroni portów Dockera.
  Zmienia wyłącznie zaporę nowej VM, nie hosta Proxmox ani innych gości.
- Weryfikuje HTTPS wewnątrz VM przez agenta QEMU, z właściwym CA, i pyta w terminalu o imienne konto aplikacji.
  Nie wymaga wyjątku w zaporze dla adresu zarządzania pve poza szkolnym LAN.
  Hasło przechodzi przez stdin agenta do Django, nie przez argumenty procesu ani plik cloud-init.

## Uruchomienie i ograniczenia

Pobrać plik instalatora z konkretnego commita, sprawdzić podaną SHA256 i uruchomić
`python3 /ścieżka/do/instalatora --school-lan 192.168.16.0/22`, z wejściem z terminala. Skrypt potrzebuje dostępu
do Internetu na Proxmoxie i w nowym gościu na czas pobrania systemu i pakietów
oraz DHCP na vmbr0. Zarządzanie komputerami odbywa się w LAN, bez usługi chmurowej,
tunelu zewnętrznego i przekierowania portów z Internetu. Nie zgaduje wolnego IP.
DHCP należy następnie zarezerwować w routerze. Adres MAC nowej VM jest w `qm config 104`.
Nie dodawać przekierowania ani SNAT/VPN, które przedstawiałyby klienta zewnętrznego
jako adres z sieci szkolnej. Instalator nie zmienia i nie sprawdza routera.

Z Maca należy uruchamiać blok zawierający `ssh -t root@proxmox-pve.taila141c0.ts.net`
(sprawdzony przez operatora dostęp Tailscale spoza LAN). Adres `root@192.168.0.250`
pozostaje lokalną ścieżką SSH. Zmiana sieci Maca nie zmienia `--school-lan 192.168.16.0/22`.
School RMM nie jest publikowany przez Tailscale. Nie zmieniać vmbr0, VLAN-aware,
głównego interfejsu ani accept-dns=false; nie resetować Tailscale bez dostępu alternatywnego.
Polecenia instalatora wykonują się na pve. Samodzielne uruchomienie bloku z /root
na Macu kończy się błędem mktemp przed jakąkolwiek zmianą na Proxmoxie.

Nowy certyfikat CA pobrać na Maca przez istniejące, zweryfikowane SSH; dokładną
ścieżkę na pve poda instalator. Zaufać publicznemu CA w Pęku kluczy przed otwarciem
podanego HTTPS. Nie wyłączać weryfikacji certyfikatów.

Logi instalacji gościa są w `/var/log/school-rmm-install.log`:

```sh
qm guest exec 104 -- /usr/bin/tail -n 80 /var/log/school-rmm-install.log
```

### Wznowienie zatrzymanej instalacji

Z istniejącego terminala `root@pve`, po pobraniu i sprawdzeniu nowego instalatora:

```sh
python3 /ścieżka/do/instalatora --resume --school-lan 192.168.16.0/22
```

Tryb wznowienia sprawdza znacznik VM w stanie instalatora i opisie VM, zakończenie
cloud-init, adres DHCP, sumę cached archiwum i zgodność istniejących źródeł.
Zmieniony kod zatrzymuje pracę; pliki lokalne `.env`, klucz Django i dane pozostają
zachowane. Następnie tworzy snapshot VM 104 i kopię plików instalatora wewnątrz
VM w `/var/backups/school-rmm/`, aktualizuje własne skrypty i zaporę, po czym
wznawia budowę kontenerów. Nie pobiera ponownie systemu ani archiwum aplikacji,
nie odtwarza dysku i nie usuwa wolumenów. Konto i hasło istniejącego administratora
pozostają zachowane. Wznowienie działa jako odrębna usługa systemd; historyczny
błąd cloud-init nie zatrzymuje poprawnie trwającego wznowienia. Błąd nowej usługi
jest zgłaszany od razu wraz z końcówką logu, zamiast czekać 25 minut.

Jeśli instalacja trwa albo jest gotowa, ale ustawienie konta przerwano, ponowić
plik z `--finish --school-lan 192.168.16.0/22`. Ten tryb czeka na gotowość i kończy
konfigurację konta bez ponownej budowy. Nie usuwać VM przy błędzie.
Ponowne uruchomienie bez --finish/--resume odrzuca zajęty VMID. Skrypt nie ma operacji destroy,
delete, stop ani reset dla istniejących VM i nie dotyka /srv/school-ai.

Testy lokalne używają symulowanych odpowiedzi Proxmoxa. Sprawdzają odrzucanie
kolizji z VM/LXC, rezerwę RAM i dysku, wybór właściwego wolumenu, snapshot przed
startem, przekazanie sekretu przez stdin oraz blokowanie operacji na innych ID.
Sprawdzają też dopuszczenie klientów 192.168.16.0/22, odrzucenie innych sieci,
adresów VPN i publicznych IP oraz kolejność startu zapory przed Dockerem.
Testy wznowienia sprawdzają snapshot przed naprawą, odrzucenie obcej VM,
brak nadpisania zmienionych źródeł, zachowanie ustawień, klucza i danych oraz
rozróżnienie aktualnej instalacji od historycznego błędu cloud-init.
Nie stanowią wykonania instalatora na rzeczywistym pve. Pierwsze rzeczywiste
uruchomienie i ewentualną diagnostykę kończymy na wynikach z terminala właściciela.

MVP obejmuje panel ewidencji i zgodności. MeshCentral i operacje na Windows
pozostają następnym etapem. Nie przedstawiać instalacji panelu jako ukończenia pełnego RMM.
