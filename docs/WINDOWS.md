# Zakres Windows i kontrakt danych

Obsługiwany cel: Windows 10 Home/Pro 22H2 z aktywnym ESU oraz Windows 11 Home/Pro
w okresie obsługi konkretnego wydania. Windows 10 bez ESU można ewidencjonować;
jest oznaczany jako zagrożony. Nie zakładamy dostępności Enterprise, Intune ani AD.

| Pole urządzenia | Znaczenie |
|---|---|
| os_family | Windows |
| os_version | 10 albo 11 |
| os_release | np. 22H2 albo 25H2; nie utożsamiać z numerem rodziny |
| os_edition | Home, Pro albo Unknown |
| os_build | kompilacja i opcjonalna rewizja |
| support_status | supported, at_risk, unknown, unsupported; wyliczane, nie przyjmowane z raportu |
| esu_status | active, inactive, unknown, not_applicable |
| capabilities | wyliczona mapa możliwości, dostępności i uzasadnień |

Potwierdzenie ESU obejmuje źródło, datę weryfikacji i koniec uprawnienia. Sam
status aktywacji Windows nie dowodzi ESU. Niepotwierdzony stan nigdy nie jest
automatycznie traktowany jako aktywny; po 30 dniach dowód wymaga ponownej kontroli.
Ta ostrożna reguła produktu nie zastępuje weryfikacji aktualizacji bezpieczeństwa.
Testowe ESU w danych demonstracyjnych jest fikcyjne, oznaczone jako TEST.

Na obecnym etapie inwentaryzacja jest dostępna dla wszystkich czterech wariantów.
Lokalne zasady grupy i wbudowany host RDP wymagają Pro; jest to dostępność funkcji
systemu, a nie potwierdzenie konfiguracji lub możliwości wykonania w School RMM.
Zdalny pulpit przez agenta nie jest utożsamiany z hostem RDP. MeshCentral może
zapewnić pulpit dla Home po rzeczywistym sprawdzeniu integracji.
Nie używamy obejść rejestru imitujących Pro na Home.

Podgląd polityki zwraca compatible, partial lub incompatible i listę brakujących
możliwości. Wykonywanie pozostaje wyłączone do wdrożenia adaptera, uprawnień i audytu.
W pierwszym etapie zgodność jest oceną wymagań, nie potwierdzeniem wdrożenia polityki.

Tabela wydań Windows 11 w kodzie jest konserwatywna: 23H2/22631 do 2025-11-11,
24H2/26100 do 2026-10-13, 25H2/26200 do 2027-10-12 dla Home/Pro. Nierozpoznane
wydanie lub sprzeczna kompilacja daje unknown. Przed pilotażem trzeba porównać
tabelę z bieżącym cyklem Microsoft i dodać nowe wydania, jeśli występują.
Źródło referencyjne: https://learn.microsoft.com/lifecycle/products/windows-11-home-and-pro
Nie przeprowadzono w tej sesji odczytu tego źródła; daty wymagają weryfikacji przed wdrożeniem.

Do odbioru na rzeczywistych VM: po jednej maszynie z każdego wariantu, z ESU
aktywnym, wygasłym i niepotwierdzonym, różne kompilacje, instalacja agenta,
poprawna rodzina/edycja/wydanie, podgląd i blokowanie niewspieranych polityk.
Skrypt PowerShell odczytuje EditionID i kompilację (ProductName może mylnie
mówić Windows 10 na Windows 11); nie rozstrzyga ESU.
