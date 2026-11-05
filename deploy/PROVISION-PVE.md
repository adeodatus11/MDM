# Instalator nowej VM 104 na pve

`provision_pve.py` uruchamia operator w istniejącym terminalu `root@pve`.
To alternatywa dla dostępu SSH z sesji chmurowej. Skrypt nie jest wykonany przez
samo zapisanie go w repozytorium ani przez lokalne testy.

Przygotowano go na podstawie raportu właściciela z 5 listopada 2026:
VM 100 GENAI, 101 cdu i 103 ai-server działają; local-zfs ma wolną przestrzeń,
vmbr0 jest mostem sieci 192.168.0.0/24, a wolny VMID wynosił 104.
Interfejs veth102 wskazuje także kontener — instalator sprawdza wszystkie VM i LXC.

## Co robi

- Ponownie sprawdza zajęte ID, storage, sieć, aktualny RAM i sumę ustawionych limitów RAM.
- Wymaga 3 GiB rezerwy poza limitami działających gości; nie zmniejsza RAM serwera AI.
- Tworzy wyłącznie nową VM 104: 2 vCPU, 2 GiB RAM, 40 GiB na local-zfs, DHCP na vmbr0.
- Przed utworzeniem gościa pobiera obraz Ubuntu 24.04 z oficjalnego HTTPS,
  sprawdza SHA256SUMS oraz format obrazu. Niezgodność zatrzymuje pracę.
- Używa przypiętej, sprawdzonej wersji aplikacji 32f52e4 oraz SHA256 archiwum.
- Dodaje odrębny storage wyłącznie na snippet cloud-init tej VM; nie zmienia local/local-zfs.
- Zapisuje raport stanu, tworzy snapshot nowej VM przed jej pierwszym uruchomieniem.
- Instaluje Docker i agenta QEMU wewnątrz nowej VM przez podpisane repozytoria Ubuntu.
- Przenosi wyłącznie publiczne wpisy z /root/.ssh/authorized_keys do konta utrzymaniowego
  rmmadmin w nowej VM; prywatne klucze pozostają na swoich komputerach. Gdy pliku nie ma,
  obsługa jest dostępna przez agenta QEMU. Logowanie hasłem i SSH root w VM są wyłączone.
- Uruchamia HTTPS i MFA, ogranicza wejście do panelu do IP bieżącego klienta SSH
  oraz hosta Proxmox. Reguła dotyczy tylko nowego gościa i jest odtwarzana po starcie Dockera.
- Weryfikuje HTTPS z właściwym CA i pyta w terminalu o imienne konto aplikacji.
  Hasło przechodzi przez stdin agenta do Django, nie przez argumenty procesu ani plik cloud-init.

## Uruchomienie i ograniczenia

Pobrać plik instalatora z konkretnego commita, sprawdzić podaną SHA256 i uruchomić
`python3 /ścieżka/do/instalatora`, z wejściem z terminala. Skrypt potrzebuje dostępu
do Internetu na Proxmoxie i w nowym gościu oraz DHCP na vmbr0. Nie zgaduje wolnego IP.
DHCP należy następnie zarezerwować w routerze. Adres MAC nowej VM jest w `qm config 104`.

Nowy certyfikat CA pobrać na Maca przez istniejące, zweryfikowane SSH; dokładną
ścieżkę na pve poda instalator. Zaufać publicznemu CA w Pęku kluczy przed otwarciem
podanego HTTPS. Nie wyłączać weryfikacji certyfikatów.

Logi instalacji gościa są w `/var/log/school-rmm-install.log`:

```sh
qm guest exec 104 -- /usr/bin/tail -n 80 /var/log/school-rmm-install.log
```

Jeśli instalacja jest gotowa, ale ustawienie konta przerwano, ponowić ten sam plik
z `--finish`. Weryfikuje on znacznik właściciela w stanie instalatora i konfiguracji VM;
nie odtwarza dysków ani nie nadpisuje istniejącego konta. Nie usuwać VM przy błędzie.
Ponowne uruchomienie bez --finish odrzuca zajęty VMID. Skrypt nie ma operacji destroy,
delete, stop ani reset dla istniejących VM i nie dotyka /srv/school-ai.

Testy lokalne używają symulowanych odpowiedzi Proxmoxa. Sprawdzają odrzucanie
kolizji z VM/LXC, rezerwę RAM i dysku, wybór właściwego wolumenu, snapshot przed
startem, przekazanie sekretu przez stdin oraz blokowanie operacji na innych ID.
Nie stanowią wykonania instalatora na rzeczywistym pve. Pierwsze rzeczywiste
uruchomienie i ewentualną diagnostykę kończymy na wynikach z terminala właściciela.

MVP obejmuje panel ewidencji i zgodności. MeshCentral i operacje na Windows
pozostają następnym etapem. Nie przedstawiać instalacji panelu jako ukończenia pełnego RMM.
