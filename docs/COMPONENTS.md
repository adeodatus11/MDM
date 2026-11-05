# Wybór istniejących komponentów

Wstępna weryfikacja źródeł: 5 listopada 2026. Odczytano oficjalne pliki licencji
i manifest MeshCentral oraz jego interfejs MeshCtrl. Nie przeprowadzono jeszcze
audytu bezpieczeństwa, testów agentów ani pełnego porównania aktywności wydań.
Przed wdrożeniem trzeba przypiąć konkretny release/commit i ponowić przegląd
licencji wszystkich składników i zależności danej wersji.

| Projekt | Licencja sprawdzona w repozytorium | Przydatność | Decyzja |
|---|---|---|---|
| MeshCentral | Apache-2.0 | Node.js, agent zdalnego dostępu, pulpit, terminal; istniejący MeshCtrl | Wybrany silnik RMM, osobna usługa i adapter |
| Veyon | GNU GPL v2 w COPYING; warunki poszczególnych plików wymagają sprawdzenia | C++/Qt, funkcje nauczyciela i sal; nie zastępuje pełnego RMM | Kandydat na przyszły moduł edukacyjny |
| RustDesk | AGPL-3.0 w LICENCE klienta; licencje serwera i oferty Pro sprawdza się oddzielnie | Rust, zdalny pulpit; nie pełna obsługa polityk i pakietów | Alternatywa zdalnej pomocy, nie silnik całego systemu |
| Remotely | GPL-3.0 w LICENSE | .NET, zdalny dostęp i skrypty | Alternatywa, copyleft i integracja do dalszej oceny |
| Fleet | MIT poza wyjątkami: ee/ własna licencja, docs/ CC BY-SA, zależności własne | Go, osquery i zarządzanie endpointami; funkcje community/płatne trzeba rozdzielić | Kandydat do inwentaryzacji, nie cały katalog funkcji jest swobodnie dostępny |
| Tactical RMM | Tactical RMM License 1.0, jawnie „not an open-source software license” | Gotowe RMM, lecz ograniczenia komercyjne/SaaS i usług | Odrzucony jako swobodnie rozwijana podstawa |

Pięć pierwszych projektów ma otwarte komponenty; Tactical jest dodatkowym porównaniem.
GPL i AGPL dopuszczają działalność komercyjną przy spełnieniu zobowiązań.
AGPL może wymagać udostępniania odpowiedniego kodu źródłowego użytkownikom sieciowym
zmodyfikowanego programu; dystrybucja GPL wymaga m.in. spełnienia obowiązków źródłowych.
Osobny proces/API ułatwia aktualizacje, lecz nie znosi automatycznie obowiązków licencji.
Apache wymaga zachowania licencji, wymaganych not prawnych i oznaczenia zmian.
Nie skopiowano kodu żadnego z kandydatów do School RMM.

## Źródła

- MeshCentral: https://github.com/Ylianst/MeshCentral/blob/master/LICENSE
- Manifest: https://github.com/Ylianst/MeshCentral/blob/master/package.json
- MeshCtrl: https://github.com/Ylianst/MeshCentral/blob/master/meshctrl.js
- Veyon: https://github.com/veyon/veyon/blob/master/COPYING
- RustDesk: https://github.com/rustdesk/rustdesk/blob/master/LICENCE
- Remotely: https://github.com/immense/Remotely/blob/master/LICENSE
- Fleet: https://github.com/fleetdm/fleet/blob/main/LICENSE
- Tactical: https://github.com/amidaware/tacticalrmm/blob/master/LICENSE.md

## Architektura i ograniczenia rekomendacji

Przeglądarka → School RMM (Django: konta, szkoły, sale, ewidencja, zgodność, później zadania)
→ adapter MeshCtrl/API → osobny MeshCentral → oryginalne agenty Windows.
Dane lokalne przechowuje SQLite; przed wdrożeniem wieloszkolnym planowana jest migracja
na PostgreSQL. Własny backend nie implementuje transportu pulpitu ani kryptografii.

Manifest MeshCentral odczytany podczas pracy wskazywał 1.3.1, Node >=20,
Apache-2.0 oraz zależności agenta/serwera. To obserwacja źródła, a nie dowód
instalacji, jakości tego wydania lub kompatybilności czterech edycji.
MeshCtrl zawiera `ListDevices`, `DeviceInfo`, `RunCommand`, `Shell`, `DevicePower`.
W integracji należy użyć wersji interfejsu zgodnej z wybranym serwerem i dokładnie
sprawdzić autoryzację operacji. Nie zakładamy ogólnego API REST ani zgodności
protokołu pomiędzy dowolnymi wersjami.

## Stan kompatybilności Windows

| Cel | Deklaracja School RMM | Rzeczywisty test agenta |
|---|---|---|
| Windows 10 Home 22H2 + ESU | W zakresie | Niewykonany |
| Windows 10 Pro 22H2 + ESU | W zakresie | Niewykonany |
| Windows 11 Home w okresie obsługi wydania | W zakresie | Niewykonany |
| Windows 11 Pro w okresie obsługi wydania | W zakresie | Niewykonany |

Testy aplikacji sprawdzają wszystkie cztery modele danych. Nie potwierdzają
deklaracji producentów agentów. Każdy kandydat wymaga osobnej matrycy na VM:
instalacja, enrollment, pulpit, PowerShell, zasilanie, inwentaryzacja i odinstalowanie.
Start usług na VM Linux w Proxmox jest planem wdrożeniowym, nie wykonanym testem.
