# [AITS] 2026-08-29T00:42:01Z
# -*- coding: utf-8 -*-
# AI-GENERATED — NOT REVIEWED: SECTION START
"""Сплошная проверка корпуса архитектурной документации docs/AA.

Запуск из корня репозитория: python Servers/audit/check_docs.py

Проверки соответствуют шагам сверки системного промпта:
  * ссылочная целостность — каждая относительная ссылка резолвится в файл;
  * резолюция идентификаторов — каждое упоминание реестрового ID имеет определение;
  * пары диаграмм — у каждого исходника есть отрисовка, и она не старше исходника;
  * конвенции карточек — отметка последней правки и таблица уровня соответствия;
  * уникальность идентификаторов — один номер принадлежит одной сущности;
  * ширина таблиц — строки не расходятся с заголовком по числу ячеек;
  * двунаправленность межслойных связей карточек C1-C4;
  * объёмы файлов, заявленные карточками уровня кода;
  * отсутствие значений рабочего инвентори в отслеживаемых файлах;
  * имена юнитов systemd, названные в документации, существуют в коде;
  * изоляция эксплуатационной документации — в docs/user нет реестровых ID.

Выход: 0 — нарушений нет, 1 — есть. Итог печатается тремя числами
(выполнено / пропущено с причиной / открыто), чтобы слово «зелено» не подменяло счёт.
"""

import os
import re
import subprocess
import sys

# Вывод принудительно в UTF-8: кодировка консоли Windows по умолчанию искажает кириллицу отчёта.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Корень репозитория вычисляется от расположения скрипта: он лежит в Servers/audit.
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
AA = os.path.join(REPO, "docs", "AA")
USER_DOCS = os.path.join(REPO, "docs", "user")

# Ссылка в markdown: текст в квадратных скобках, адрес в круглых.
LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")
# Реестровый идентификатор: слой-группа-номер (C2-FR-001, DE-CF-001, GAP-042, ADR-000003).
ID_RE = re.compile(r"\b(?:C[1-4]-[A-Z]{2}-\d{3}|DE-[A-Z]{2}-\d{3}|ADR-\d{6}|GAP-\d{3}|IDEA-\d{3}|AAS-\d{3})\b")

# Артефакты, к которым конвенции карточек ещё не применены (разрыв GAP-052 реестра Ideas.md).
# Перечень поимённый: иначе отчёт молчал бы о новых нарушениях наравне с уже учтёнными.
CONVENTION_DEBT = {
    "AAD.md", "ADL-archive.md", "ADL.md", "ARR.md", "C2-META.md", "C2-PR.md",
    "C3-CR.md", "C4-SR.md", "DD.md", "Ideas.md", "README.md", "TD.md",
}


def collect_markdown(root):
    """Собирает все markdown-файлы дерева в отсортированный список абсолютных путей."""
    found = []
    for base, _dirs, files in os.walk(root):
        for name in files:
            if name.endswith(".md"):
                found.append(os.path.join(base, name))
    return sorted(found)


def read(path):
    """Читает файл в кодировке UTF-8, не падая на посторонних байтах."""
    with open(path, encoding="utf-8", errors="replace") as handle:
        return handle.read()


def check_links(docs, problems):
    """Ссылочная целостность: относительная ссылка обязана резолвиться в существующий файл."""
    for path in docs:
        base = os.path.dirname(path)
        for _text, target in LINK_RE.findall(read(path)):
            # Внешние адреса и якоря внутри страницы проверке файловой системой не подлежат.
            if target.startswith(("http://", "https://", "#", "mailto:")):
                continue
            resolved = os.path.normpath(os.path.join(base, target.split("#")[0]))
            if not os.path.exists(resolved):
                problems.append("висячая ссылка: %s → %s" % (rel(path), target))


def collect_defined_ids(docs):
    """Множество определённых идентификаторов: имя файла карточки либо заголовок первого уровня."""
    defined = set()
    for path in docs:
        stem = os.path.basename(path)[:-3]
        if ID_RE.fullmatch(stem):
            defined.add(stem)
        # Реестры перечисляют идентификаторы строками таблицы — заголовок карточки не обязателен.
        for line in read(path).split("\n"):
            if line.startswith("| "):
                cell = line.split("|")[1].strip()
                if ID_RE.fullmatch(cell):
                    defined.add(cell)
    return defined


def check_ids(docs, defined, problems):
    """Резолюция идентификаторов: каждое упоминание имеет определение в реестре либо карточке."""
    for path in docs:
        for found in set(ID_RE.findall(read(path))):
            if found not in defined:
                problems.append("идентификатор без определения: %s в %s" % (found, rel(path)))


def check_id_collisions(docs, problems):
    """Уникальность идентификаторов: один номер — одна сущность.

    Коллизия опаснее висячей ссылки: ссылка обрывается заметно, а два разных разрыва под общим
    номером выглядят исправными и расходятся в разные стороны при первой же правке.
    """
    for path in docs:
        # Определением считается строка таблицы, начинающаяся идентификатором в первой ячейке.
        seen = {}
        for number, line in enumerate(read(path).split("\n"), start=1):
            if not line.startswith("| "):
                continue
            cell = line.split("|")[1].strip()
            if not ID_RE.fullmatch(cell):
                continue
            if cell in seen:
                problems.append("повтор идентификатора: %s в %s (строки %d и %d)"
                                % (cell, rel(path), seen[cell], number))
            else:
                seen[cell] = number


def check_table_shape(docs, problems):
    """Ширина таблиц: каждая строка тела совпадает по числу ячеек со строкой заголовка."""
    for path in docs:
        header_cells = 0     # ожидаемое число ячеек текущей таблицы
        header_line = 0      # номер строки заголовка — для сообщения
        prev_was_header = False
        for number, line in enumerate(read(path).splitlines(), start=1):
            # Экранированная черта — часть содержимого ячейки, а не её граница.
            stripped = line.strip().replace("\\|", "\0")
            if not stripped.startswith("|"):
                # Таблица закончилась — следующая начнётся со своего заголовка.
                header_cells = 0
                prev_was_header = False
                continue
            cells = len(stripped.strip("|").split("|"))
            # Строка-разделитель следует сразу за заголовком и задаёт ширину таблицы.
            if set(stripped.replace("|", "").replace(" ", "")) <= set("-:") and prev_was_header:
                if cells != header_cells:
                    problems.append("ширина разделителя не совпадает с заголовком: %s строка %d "
                                    "(%d против %d)" % (rel(path), number, cells, header_cells))
                continue
            if header_cells == 0:
                header_cells = cells
                header_line = number
                prev_was_header = True
                continue
            prev_was_header = False
            if cells != header_cells:
                problems.append("ширина строки таблицы не совпадает с заголовком: %s строка %d "
                                "(%d против %d в строке %d)"
                                % (rel(path), number, cells, header_cells, header_line))


# Фразы, которыми карточка объявляет перечень охватом либо сводкой, а не родительством.
# Связь из такой строки взаимной быть не обязана — и барьер её не требует.
AGGREGATE_MARKERS = (
    "порождённые системой",
    "в области действия",
    "в области развёртывания",
    "Карточки-аспекты",
    "Связанные C4",
    "Связанные артефакты",
    "охват, а не",
)

# Карточки, которые целиком являются сводками слоя.
AGGREGATE_CARDS = {"C2-META", "C1-BC-001"}

CARD_ID_RE = re.compile(r"C[1-4]-[A-Z]{2}-\d{3}")


def collect_card_links(docs):
    """Собирает родительские и дочерние ссылки карточек слоёв C1-C4 из их шапок.

    Читается только шапка — до раздела «Описание»: дальше идут упоминания по тексту,
    которые связью родитель-ребёнок не являются.
    """
    links = {}
    for path in docs:
        parts = rel(path).split(os.sep)
        if len(parts) < 4 or parts[2] not in {"C1", "C2", "C3", "C4"}:
            continue
        stem = os.path.basename(path)[:-3]
        head = read(path).split("## Описание")[0]
        refs = set()
        for line in head.split("\n"):
            if any(marker in line for marker in AGGREGATE_MARKERS):
                continue
            refs.update(CARD_ID_RE.findall(line))
        links[stem] = refs - {stem}
    return links


def check_bidirectional(docs, problems):
    """Двунаправленность межслойных связей: обе карточки знают друг о друге.

    Односторонняя связь означает, что правка одной стороны оставит вторую расходящейся
    незаметно. Взаимности требует только связь между слоями — она выражает родительство;
    связь внутри слоя и объявленные агрегаты из проверки исключены.
    """
    links = collect_card_links(docs)
    for source in sorted(links):
        if source in AGGREGATE_CARDS:
            continue
        for target in sorted(links[source]):
            if target[:2] == source[:2] or target in AGGREGATE_CARDS:
                continue
            if target in links and source not in links[target]:
                problems.append("односторонняя связь: %s ссылается на %s, обратной ссылки нет"
                                % (source, target))


# Объём файла, заявленный карточкой: путь в обратных кавычках и число строк рядом.
# Пример: Файл `Servers/deploy/playbook.yml` (936 строк)
FILE_SIZE_RE = re.compile(r"`(Servers/[^`]+)`\s*\((?:~)?(\d+)\s+строк")

# Допуск: карточка описывает артефакт, а не считает его построчно, поэтому мелкая правка
# кода не обязана вызывать правку карточки. Расхождение свыше десятой доли означает, что
# артефакт менялся существенно, а карточка за ним не пошла.
SIZE_TOLERANCE = 0.10


def check_declared_sizes(docs, problems, skipped):
    """Сверяет объёмы файлов, заявленные карточками, с фактическими."""
    checked = 0
    for path in docs:
        for rel_target, declared in FILE_SIZE_RE.findall(read(path)):
            target = os.path.join(REPO, rel_target.replace("/", os.sep))
            if not os.path.exists(target):
                problems.append("заявлен объём несуществующего файла: %s в %s"
                                % (rel_target, rel(path)))
                continue
            actual = len(read(target).splitlines())
            checked += 1
            declared_int = int(declared)
            if abs(actual - declared_int) > max(1, actual * SIZE_TOLERANCE):
                problems.append("объём разошёлся: %s заявлено %d, фактически %d (%s)"
                                % (rel_target, declared_int, actual, rel(path)))
    if not checked:
        skipped.append("объёмы файлов: заявлений в карточках не найдено")


# Рабочий инвентори под контроль версий не попадает и служит источником значений,
# которых в отслеживаемых файлах быть не должно: адреса узлов, домены, имена хостов.
INVENTORY = os.path.join(REPO, "Servers", "deploy", "inventory.yml")

# Значения, извлекаемые из инвентори для сверки: адреса и доменные имена.
LEAK_VALUE_RE = re.compile(
    r":\s*\"?((?:\d{1,3}\.){3}\d{1,3}|[a-z0-9][a-z0-9-]*(?:\.[a-z0-9-]+)*\.[a-z]{2,})\"?\s*$")

# Имя узла в инвентори: ключ с отступом и без значения после двоеточия.
LEAK_HOST_RE = re.compile(r"^\s{4,}([a-z][a-z0-9._-]*):\s*$")

# Служебные ключи инвентори, не являющиеся именами узлов.
INVENTORY_KEYWORDS = {
    "all", "children", "hosts", "vars", "access_proxies", "upstreams",
    "allowed_domains", "allowed_domain_patterns", "dns_servers", "mtproxy_users",
    "dns_extra_clients",
}

# Значения, которые раскрытием не являются: документационные диапазоны RFC 5737 и RFC 2606,
# служебные адреса, общеизвестные публичные резолверы.
LEAK_ALLOWED = {
    "127.0.0.1", "0.0.0.0", "255.255.255.255", "1.2.3.4",
    "9.9.9.9", "8.8.8.8", "1.1.1.1",
    "example.com", "example.org", "example.net",
}
LEAK_ALLOWED_PREFIXES = ("192.0.2.", "198.51.100.", "203.0.113.", "10.", "172.16.", "192.168.")


EXAMPLE_INVENTORY = os.path.join(REPO, "Servers", "deploy", "inventory.example.yml")


def collect_example_values():
    """Собирает значения и имена из образца инвентори: они опубликованы намеренно."""
    if not os.path.exists(EXAMPLE_INVENTORY):
        return set()
    published = set()
    for line in read(EXAMPLE_INVENTORY).splitlines():
        host = LEAK_HOST_RE.match(line)
        if host:
            published.add(host.group(1))
            continue
        found = LEAK_VALUE_RE.search(line)
        if found:
            published.add(found.group(1))
    return published


def collect_working_values():
    """Собирает из рабочего инвентори значения, которые не должны попадать в репозиторий.

    Совпадающее с образцом исключается: образец публикуется намеренно, и совпадение имени
    означает, что рабочая конфигурация просто не переименовывала узлы.
    """
    if not os.path.exists(INVENTORY):
        return None
    values = set()
    for line in read(INVENTORY).splitlines():
        # Имена узлов — ключи отображения, а не значения: собираются отдельно.
        # Признак: строка вида «        имя-узла:» без значения после двоеточия.
        host = LEAK_HOST_RE.match(line)
        if host:
            name = host.group(1)
            if name not in INVENTORY_KEYWORDS:
                values.add(name)
            continue
        found = LEAK_VALUE_RE.search(line)
        if not found:
            continue
        value = found.group(1)
        if value in LEAK_ALLOWED or value.startswith(LEAK_ALLOWED_PREFIXES):
            continue
        # Односегментные имена вроде «true» или «access» доменами не являются.
        if not value.replace(".", "").replace("-", "").isdigit() and value.count(".") == 0:
            continue
        values.add(value)
    return values - collect_example_values()


def check_working_values_not_leaked(problems, skipped):
    """Проверяет, что значения рабочего инвентори не попали в отслеживаемые файлы.

    Проверка появилась после трёх случаев подряд: адреса узлов, домен маскировки MTProxy
    и имя публичного узла оказывались в отслеживаемых файлах, а часть из них — в отправленных
    коммитах. Раскрытие отправкой не отменяется перезаписью истории, поэтому дешевле
    не допускать его механически.
    """
    values = collect_working_values()
    if values is None:
        skipped.append("сверка с рабочим инвентори: файл отсутствует (нечего сверять)")
        return
    if not values:
        skipped.append("сверка с рабочим инвентори: значений для сверки не найдено")
        return
    try:
        listing = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True,
                                 text=True, timeout=30).stdout.split("\n")
    except (OSError, subprocess.SubprocessError):
        skipped.append("сверка с рабочим инвентори: git недоступен")
        return
    for rel_path in listing:
        rel_path = rel_path.strip()
        if not rel_path or rel_path.endswith((".svg", ".png", ".jar")):
            continue
        full = os.path.join(REPO, rel_path.replace("/", os.sep))
        if not os.path.isfile(full):
            continue
        content = read(full)
        for value in sorted(values):
            if value in content:
                problems.append("значение рабочего инвентори в отслеживаемом файле: "
                                "%s в %s" % (value, rel_path))


# Имя юнита в команде управления службой: systemctl <действие> <имя>.
UNIT_IN_DOC_RE = re.compile(r"systemctl\s+(?:[a-z-]+\s+)+?([a-z][a-z0-9@._-]{2,})")

# Имена, которые упоминаются как имена пакетов либо параметров, а не юнитов.
UNIT_NOT_A_SERVICE = {"show", "status", "is-active", "enable", "start", "stop", "restart"}

# Каталоги кода, где ищутся имена юнитов.
CODE_DIRS = [os.path.join(REPO, "Servers", "deploy")]


def collect_code_units():
    """Собирает имена служб, встречающиеся в коде развёртывания."""
    units = set()
    for base_dir in CODE_DIRS:
        for base, _dirs, files in os.walk(base_dir):
            for name in files:
                if not name.endswith((".yml", ".yaml", ".j2")):
                    continue
                content = read(os.path.join(base, name))
                # Имя службы задаётся полем name у модулей systemd и service,
                # а также встречается в путях юнит-файлов.
                units.update(re.findall(r"name:\s*([a-z][a-z0-9@._-]{2,})", content))
                units.update(re.findall(r"/etc/systemd/system/([a-z][a-z0-9@._-]+)\.service",
                                        content))
                units.update(re.findall(r"([a-z][a-z0-9@._-]+)\.service", content))
    return units


def check_unit_names(docs, problems, skipped):
    """Сверяет имена юнитов, названные в документации, с именами из кода.

    Имя, которого в коде нет, означает неисполнимую команду в критерии приёмки: проверяющий
    получит «юнит не найден» и станет искать неисправность там, где её нет.
    """
    code_units = collect_code_units()
    if not code_units:
        skipped.append("имена юнитов: код развёртывания не найден")
        return
    for path in docs:
        for unit in set(UNIT_IN_DOC_RE.findall(read(path))):
            if unit in UNIT_NOT_A_SERVICE or unit in code_units:
                continue
            # Имя могло быть записано с суффиксом либо без него.
            if unit + ".service" in code_units or unit.replace(".service", "") in code_units:
                continue
            problems.append("юнит из документации не найден в коде: %s в %s"
                            % (unit, rel(path)))


def check_diagrams(problems, skipped):
    """Пары диаграмм: у исходника есть отрисовка, и отрисовка не старше исходника."""
    sources = []
    for base, _dirs, files in os.walk(AA):
        for name in files:
            if name.endswith(".puml"):
                sources.append(os.path.join(base, name))
    for puml in sorted(sources):
        svg = puml[:-5] + ".svg"
        if not os.path.exists(svg):
            problems.append("нет отрисовки: %s" % rel(puml))
        elif os.path.getmtime(svg) < os.path.getmtime(puml):
            problems.append("отрисовка старше исходника: %s" % rel(svg))
    if not sources:
        skipped.append("диаграммы: исходников не найдено")
    return len(sources)


def check_conventions(docs, problems, skipped):
    """Конвенции карточек: отметка последней правки AI и таблица уровня соответствия.

    Два условия разведены намеренно. Отсутствие уровня соответствия — дефект карточки,
    устранимый её правкой. Отсутствие отметки правки устраняется не правкой файла, а сверкой
    его содержимого с источником истины: отметка утверждает, что сверка выполнена, поэтому
    проставить её оптом значило бы удостоверить непроверенное. До закрытия разрыва GAP-052
    такие артефакты считаются пропущенными с причиной, а не нарушением.
    """
    stamp_debt = 0
    level_debt = 0
    for path in docs:
        name = os.path.basename(path)
        text = read(path)
        known = name in CONVENTION_DEBT or is_known_debt(path)

        if name in {"Ideas.md", "Ideas-archive.md", "README.md"}:
            continue
        if "## Статус соответствия" not in text:
            if known:
                level_debt += 1
            else:
                problems.append("нет таблицы уровня соответствия: %s" % rel(path))

        # Журналы и указатели содержания сверке не подлежат: они описывают не систему,
        # а состояние работы над её описанием.
        if name in {"Ideas.md", "Ideas-archive.md", "README.md"}:
            continue
        if "Последняя правка AI" not in text:
            stamp_debt += 1

    if level_debt:
        skipped.append("уровень соответствия: %d артефактов учтены разрывом GAP-052" % level_debt)
    if stamp_debt:
        skipped.append("отметка правки: %d артефактов ждут сверки (разрыв GAP-052)" % stamp_debt)


def is_known_debt(path):
    """Признак артефакта из слоёв, ожидающих применения конвенций (DD, TD, CC, ADR)."""
    parts = rel(path).split(os.sep)
    return len(parts) > 2 and parts[2] in {"DD", "TD", "CC", "ADR"}


def check_user_docs_isolation(problems, skipped):
    """Изоляция эксплуатационной документации: реестровых идентификаторов в ней быть не должно."""
    if not os.path.isdir(USER_DOCS):
        skipped.append("изоляция ЭД: каталог docs/user отсутствует")
        return
    for path in collect_markdown(USER_DOCS):
        for found in set(ID_RE.findall(read(path))):
            problems.append("реестровый идентификатор в ЭД: %s в %s" % (found, rel(path)))


def check_gap_backlinks(docs, problems, skipped):
    """Карточка, названная открытым разрывом, обязана упоминать его номер.

    Иначе читатель карточки не узнает об открытом дефекте: реестр разрывов читают
    не всегда, а карточку — по определению, раз пришли за сведениями о механизме.
    """
    ideas = os.path.join(AA, "Ideas.md")
    if not os.path.isfile(ideas):
        skipped.append("обратные ссылки на разрывы: реестр Ideas.md отсутствует")
        return
    # Карта имён карточек: локус разрыва называет карточку без пути и расширения.
    by_name = {}
    for path in docs:
        by_name[os.path.basename(path)[:-3]] = path
    for line in read(ideas).splitlines():
        if not re.match(r"^\| GAP-\d+ \|", line):
            continue
        cells = [c.strip() for c in line.split("|")]
        gap, locus = cells[1], cells[2]
        # Закрытые разрывы предупреждения не требуют: дефекта больше нет.
        if "Open" not in line:
            continue
        for name in re.split(r"[,;]", locus):
            name = name.strip().strip("`")
            target = by_name.get(name)
            if target is None:
                continue
            if gap not in read(target):
                problems.append(
                    "карточка не упоминает открытый разрыв: %s не ссылается на %s"
                    % (rel(target), gap))


def check_generated_fresh(problems, skipped):
    """Производные артефакты не отстают от фактического состава корпуса.

    Реестр жизненного цикла и панель показателей порождаются генератором; расхождение
    означает, что после правок его не прогнали, и числа в панели уже не о корпусе.
    """
    gen = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gen_lifecycle.py")
    if not os.path.isfile(gen):
        skipped.append("свежесть производных: gen_lifecycle.py отсутствует")
        return
    proc = subprocess.run([sys.executable, gen, "--check"],
                          capture_output=True, text=True, encoding="utf-8")
    for line in (proc.stdout or "").splitlines():
        line = line.strip()
        if line:
            problems.append("производный артефакт устарел: %s" % line)


# Шаблоны, о которых известно, что они не разворачиваются: заготовки, ожидающие решения
# владельца — связать их с задачами либо удалить. Каждая строка несёт номер разрыва,
# и снимается она вместе с его закрытием, а не отдельно.
KNOWN_DEAD_TEMPLATES = {
    "mtg.env.j2": "GAP-141",
    "nftables-mtproxy.conf.j2": "GAP-141",
    "nginx-squid-tls-term.conf.j2": "GAP-141",
    "squid.conf.j2": "GAP-141",
}


def check_dead_templates(problems, skipped):
    """Шаблоны развёртывания связаны с задачами, которые их разворачивают.

    Шаблон без задачи попадает в документацию как рабочий механизм, не будучи им:
    директивы в нём настоящие, а на узел он не попадает никогда.
    """
    roles = os.path.join(REPO, "deploy", "roles")
    if not os.path.isdir(roles):
        roles = os.path.join(REPO, "Servers", "deploy", "roles")
    if not os.path.isdir(roles):
        skipped.append("мёртвые шаблоны: каталог ролей не найден")
        return
    # Имя шаблона ищется в задачах его роли и в плейбуках рядом с каталогом ролей.
    playbooks = []
    base = os.path.dirname(roles)
    for name in os.listdir(base):
        if name.endswith((".yml", ".yaml")):
            playbooks.append(read(os.path.join(base, name)))
    for role in sorted(os.listdir(roles)):
        role_dir = os.path.join(roles, role)
        tpl_dir = os.path.join(role_dir, "templates")
        if not os.path.isdir(tpl_dir):
            continue
        sources = list(playbooks)
        for sub in ("tasks", "handlers", "defaults", "vars"):
            d = os.path.join(role_dir, sub)
            if not os.path.isdir(d):
                continue
            for name in os.listdir(d):
                if name.endswith((".yml", ".yaml")):
                    sources.append(read(os.path.join(d, name)))
        for cur, _dirs, files in os.walk(tpl_dir):
            for name in files:
                if not name.endswith(".j2"):
                    continue
                if any(name in text for text in sources):
                    continue
                where = os.path.relpath(os.path.join(cur, name), tpl_dir)
                gap = KNOWN_DEAD_TEMPLATES.get(name)
                if gap:
                    skipped.append("шаблон не разворачивается (известно, %s): %s в роли %s"
                                   % (gap, where, role))
                    continue
                problems.append(
                    "шаблон не разворачивается ни одной задачей: %s в роли %s"
                    % (where, role))


# Пути репозитория, упоминаемые в документации в обратных кавычках. Начальные сегменты
# перечислены явно: иначе под шаблон попадут пути на узле и имена переменных.
REPO_PATH_RE = re.compile(r"`((?:Servers/deploy|deploy|docs|audit|Clients)/[A-Za-z0-9_./-]+)`")


def check_repo_paths(docs, problems):
    """Пути репозитория, названные в документации, существуют.

    Ссылка на несуществующий файл заставляет читателя искать несуществующее и подозревать
    неисправность там, где её нет.
    """
    for path in docs:
        for found in set(REPO_PATH_RE.findall(read(path))):
            target = os.path.join(REPO, found.rstrip("/").replace("/", os.sep))
            if os.path.exists(target):
                continue
            # Путь мог быть указан с шаблоном подстановки — такие не проверяем.
            if "*" in found or "{" in found:
                continue
            problems.append("путь репозитория не существует: %s в %s"
                            % (found, rel(path)))


# Обработчики, о которых известно, что их никто не вызывает. Каждый безвреден: его работу
# выполняет другой обработчик либо последующий прогон роли. Перечень поимённый — общее
# подавление правила скрыло бы будущие случаи.
KNOWN_UNUSED_HANDLERS = {
    "Reload unbound": "конфигурация применяется перезапуском, обработчик перезапуска вызывается",
    "Restart nftables": "правила применяются задачей напрямую",
    "Restart nginx": "перезапуск общей службы запрещён при совместном размещении",
    "Reload nginx after certbot": "конфигурацию с сертификатами разворачивает последующий прогон роли nginx",
}


def check_unused_handlers(problems, skipped):
    """Обработчики вызываются хотя бы одной задачей — по имени либо через listen.

    Невызываемый обработчик обещает применение изменений, которого не произойдёт.
    """
    roles = os.path.join(REPO, "deploy", "roles")
    if not os.path.isdir(roles):
        roles = os.path.join(REPO, "Servers", "deploy", "roles")
    if not os.path.isdir(roles):
        skipped.append("обработчики без вызова: каталог ролей не найден")
        return
    base = os.path.dirname(roles)
    playbooks = ""
    for name in os.listdir(base):
        if name.endswith((".yml", ".yaml")):
            playbooks += read(os.path.join(base, name))
    for role in sorted(os.listdir(roles)):
        hf = os.path.join(roles, role, "handlers", "main.yml")
        if not os.path.isfile(hf):
            continue
        raw = read(hf)
        body = playbooks
        tasks = os.path.join(roles, role, "tasks")
        if os.path.isdir(tasks):
            for name in os.listdir(tasks):
                if name.endswith((".yml", ".yaml")):
                    body += read(os.path.join(tasks, name))
        for block in re.split(r"^- name: ", raw, flags=re.M)[1:]:
            own = block.split("\n")[0].strip()
            listens = [x.strip() for x in
                       re.findall(r"listen:\s*['\"]?([^'\"\n]+)", block)]
            if own in body or any(x in body for x in listens):
                continue
            if own in KNOWN_UNUSED_HANDLERS:
                skipped.append("обработчик без вызова (известно): %s в роли %s — %s"
                               % (own, role, KNOWN_UNUSED_HANDLERS[own]))
                continue
            problems.append("обработчик не вызывается ни одной задачей: %s в роли %s"
                            % (own, role))


def rel(path):
    """Путь относительно корня репозитория — для читаемых сообщений."""
    return os.path.relpath(path, REPO)


def main():
    """Прогон всех проверок и печать итога тремя числами."""
    if not os.path.isdir(AA):
        print("корпус docs/AA не найден: %s" % AA)
        return 1

    problems = []   # нарушения, требующие правки
    skipped = []    # проверки, не выполненные с названной причиной
    docs = collect_markdown(AA)

    check_links(docs, problems)
    check_ids(docs, collect_defined_ids(docs), problems)
    check_id_collisions(docs, problems)
    check_table_shape(docs, problems)
    check_bidirectional(docs, problems)
    check_declared_sizes(docs, problems, skipped)
    check_working_values_not_leaked(problems, skipped)
    check_unit_names(docs, problems, skipped)
    diagrams = check_diagrams(problems, skipped)
    check_conventions(docs, problems, skipped)
    check_user_docs_isolation(problems, skipped)
    check_gap_backlinks(docs, problems, skipped)
    check_generated_fresh(problems, skipped)
    check_dead_templates(problems, skipped)
    check_repo_paths(docs, problems)
    check_unused_handlers(problems, skipped)

    print("Проверено: %d карточек, %d диаграмм" % (len(docs), diagrams))
    for line in skipped:
        print("  пропущено: %s" % line)
    for line in problems:
        print("  НАРУШЕНИЕ: %s" % line)
    # Итог тремя числами: выполнено — число прогнанных проверок, а не «всё хорошо».
    print("Итог: выполнено 16 / пропущено с причиной %d / открыто %d" % (len(skipped), len(problems)))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
# AI-GENERATED — NOT REVIEWED: SECTION END
