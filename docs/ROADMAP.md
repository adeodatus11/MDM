# Etapy realizacji School RMM

Aktualizacja: 5 listopada 2026. Użytkownik upoważnił do rozpoczęcia budowy;
pierwsze testy wykonujemy wyłącznie na maszynach testowych.

## 1. Działający fundament — zbudowany lokalnie

- Django 5.2 LTS, serwerowe szablony po polsku, SQLite do lokalnego rozwoju.
- Standardowe konta i sesje Django, blokada prób logowania, CSRF i granice dostępu szkół.
- Szkoły, sale, ręczna ewidencja i import sprzętu; macierz Home/Pro i ESU.
- Filtry, raport CSV, API do odczytu, podgląd zgodności polityk i testy.
- Ocena sześciu kandydatów, w tym pięciu z licencjami open source.

Odbiór: poprawne testy aplikacji, działający proces HTTP i odpowiedź funkcjonalna.
Testy modeli nie są dowodem działania agentów na rzeczywistym Windows.

## 2. Izolowane laboratorium na Proxmox — wymaga dostępu

- Odnaleźć konfigurację z projektu PROXMOX AI; ta sesja nie ma do niego dostępu.
- Sprawdzić serwer i zasoby operacjami do odczytu; użyć osobnej VM i testowej sieci.
- Utworzyć VM Linux, nadać jej adres i nazwę oraz zainstalować usługę School RMM.
- Włączyć TLS, MFA dla administratorów i backup z próbą odtworzenia.
- Uruchomić oddzielną usługę MeshCentral; wyłączyć publiczną rejestrację,
  włączyć MFA i ograniczyć panel do sieci administratorów.
- Oddzielić dane i wersje usług. Sekrety pozostają poza Git i dokumentacją.

Odbiór: logowanie z MFA przez HTTPS, restart VM nie gubi danych, odtworzenie
kopii w drugim środowisku, brak dostępu z niedozwolonych sieci.

## 3. Podłączenie agentów i ewidencji automatycznej

- Użyć oryginalnego agenta MeshCentral; nie tworzyć własnego agenta zdalnego dostępu.
- Zweryfikować i przypiąć wersje serwera i agentów oraz aktualizacje z integralnością.
- Na czterech testowych VM Windows sprawdzić instalację, enrollment, heartbeat,
  odnowienie połączenia i inwentaryzację Windows 10/11 Home/Pro.
- Adapter backendu korzysta z udokumentowanego MeshCtrl/API; w pierwszej kolejności
  tylko odczyt. Kontrolować uprawnienia konta integracyjnego po stronie MeshCentral.
- Przypisać identyfikatory agentów do szkoły i sali; odrzucać kolizje i obce urządzenia.
- Status ESU potwierdzać osobnym, zweryfikowanym mechanizmem; brak danych to unknown.

Odbiór: cztery warianty Windows widoczne z aktualnymi danymi i stanem połączenia,
brak dostępu między szkołami zarówno w School RMM, jak i w MeshCentral.

## 4. Zdalna pomoc i kontrolowane operacje

- Udostępnić pulpit i terminal istniejącego silnika, bez obchodzenia uwierzytelnienia.
- Dodać kolejkę zadań, statusy, timeout, idempotencję i audyt wykonania.
- Uruchamianie zatwierdzonych skryptów, restart i wyłączenie wymagają jawnego
  wyboru urządzeń i potwierdzenia w panelu; role i szkoła sprawdzane także w backendzie.
- Przed zadaniem wyliczać zgodność i dostępność agenta; błędy raportować per komputer.
- Nie dodawać arbitralnej ścieżki wykonania komend przed tymi zabezpieczeniami.

Odbiór: zadanie na jednym testowym komputerze działa i ma audyt;
operacja na niedozwolonym urządzeniu jest odrzucana, a ponowienie nie dubluje zadania.

## 5. Polityki i oprogramowanie

- Zacząć od kilku udokumentowanych polityk o niewielkim ryzyku, z odczytem stanu,
  podglądem zmian, zastosowaniem, weryfikacją i wycofaniem.
- Każda polityka deklaruje możliwości; Home otrzymuje wyłącznie wspierane mechanizmy.
- Pakiety oprogramowania przypisane do sal, z weryfikacją podpisów/źródeł,
  wyniku i inwentaryzacji po instalacji. Office wymaga legalnych uprawnień szkoły.
- Windows Update: osobne okna serwisowe, obsługa restartu i różnic Home/Pro.

Odbiór: Home nie otrzymuje polityki wymagającej Pro; poprawne wyniki częściowego
wdrożenia i wycofania; błędy nie są pokazywane jako sukces.

## 6. Pilotaż i skalowanie

- Najpierw 5–10 testowych maszyn; szkolne urządzenia dopiero po osobnym uzgodnieniu.
- Próby awarii, aktualizacji, odtwarzania i utraty połączenia; test obciążenia 300 agentów.
- Przed udostępnieniem wielu szkołom: PostgreSQL, pełny przegląd RBAC i audytu,
  polityka retencji, rozdzielenie danych, monitoring i dokumentacja administratora.
- Panel nauczyciela i Veyon dopiero jako późniejszy moduł, po weryfikacji API/licencji.

## Decyzje potrzebne od właściciela

Teraz: udostępnienie połączenia do PROXMOX AI w tej sesji, nie sekretów w czacie.
Po inspekcji Proxmoxa: przydział zasobów i testowej sieci, nazwa DNS/certyfikat.
Przed rozpowszechnianiem: licencja własnego kodu i model udostępniania innym szkołom.
Resztę zwykłych decyzji implementacyjnych podejmujemy w ramach powyższego planu.
