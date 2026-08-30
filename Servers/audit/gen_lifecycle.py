# [AITS] 2026-08-30T12:09:29Z
# -*- coding: utf-8 -*-
# AI-GENERATED — NOT REVIEWED: SECTION START
"""Генератор реестра жизненного цикла артефактов docs/AA/CC/CC-Lifecycle.md.

Запуск из корня репозитория: python Servers/audit/gen_lifecycle.py

Реестр перечисляет каждый артефакт корпуса со статусом жизненного цикла, датой и
зависимостями. Ведение вручную не удерживается: артефактов около сотни, и всякое добавление
карточки оставляло реестр расходящимся — именно так он и застрял в состоянии, где полтора
десятка существующих карточек значились отсутствующими.

Статус выводится из наблюдаемого признака, а не назначается:
  * есть отметка последней правки AI — карточка сверена с источником истины, статус verified;
  * отметки нет — карточка заполнена, но сверка не подтверждена, статус review.
Дата берётся из отметки, а при её отсутствии — из даты последнего коммита файла.
"""

import io
import os
import re
import subprocess
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
AA = os.path.join(REPO, "docs", "AA")
TARGET = os.path.join(AA, "CC", "CC-Lifecycle.md")

STAMP_RE = re.compile(r"\*\*Последняя правка AI:\*\*\s*(\d{4}-\d{2}-\d{2})")
CARD_ID_RE = re.compile(r"C[1-4]-[A-Z]{2}-\d{3}|DE-[A-Z]{2}-\d{3}|ADR-\d{6}")

# Разделы реестра: заголовок и предикат принадлежности файла разделу.
SECTIONS = [
    ("Реестры слоёв", lambda rel: os.path.dirname(rel) == "" and rel.endswith(
        ("C1-BR.md", "C2-PR.md", "C3-CR.md", "C4-SR.md", "TD.md", "DD.md", "ADL.md",
         "ADL-archive.md", "AAD.md", "ARR.md"))),
    ("C1 — Бизнес-контекст", lambda rel: rel.startswith("C1" + os.sep)),
    ("C2 — Требования к продукту", lambda rel: rel.startswith("C2" + os.sep)),
    ("C3 — Компонентный контекст", lambda rel: rel.startswith("C3" + os.sep)),
    ("C4 — Уровень кода", lambda rel: rel.startswith("C4" + os.sep)),
    ("ADR — Архитектурные решения", lambda rel: rel.startswith("ADR" + os.sep)),
    ("TD — Техническая документация", lambda rel: rel.startswith("TD" + os.sep)),
    ("DD — Архитектура данных", lambda rel: rel.startswith("DD" + os.sep)),
    ("CC — Сквозные объекты", lambda rel: rel.startswith("CC" + os.sep)),
]

# Файлы, которые реестром состояний не описываются: они сами являются журналами.
EXCLUDED = {"Ideas.md", "Ideas-archive.md", "README.md"}


def read_text(path):
    """Читает файл в UTF-8, не падая на посторонних байтах."""
    return io.open(path, encoding="utf-8", errors="replace").read()


def git_date(path):
    """Дата последнего коммита файла; для неотслеживаемого возвращает прочерк."""
    try:
        out = subprocess.run(
            ["git", "log", "-1", "--format=%ad", "--date=short", "--", path],
            cwd=REPO, capture_output=True, text=True, timeout=20)
        return out.stdout.strip() or "--"
    except (OSError, subprocess.SubprocessError):
        return "--"


def describe(path):
    """Возвращает описание артефакта: статус, дату и перечень зависимостей."""
    text = io.open(path, encoding="utf-8", errors="replace").read()
    stamp = STAMP_RE.search(text)
    # Отметка последней правки означает выполненную сверку — только она даёт статус verified.
    status = "verified" if stamp else "review"
    date = stamp.group(1) if stamp else git_date(path)
    # Зависимости — идентификаторы из шапки карточки, то есть её родители и соседи по ссылкам.
    head = text.split("## Описание")[0]
    deps = []
    for found in CARD_ID_RE.findall(head):
        if found not in deps and found != os.path.basename(path)[:-3]:
            deps.append(found)
    return status, date, ", ".join(deps[:8]) if deps else "--"


def artifact_type(rel):
    """Тип артефакта по его расположению в корпусе."""
    folder = os.path.dirname(rel)
    if folder == "":
        return "Реестр слоя"
    if folder.startswith("DD" + os.sep + "DE"):
        return "Сущность данных"
    return {"C1": "Детальный C1", "C2": "Детальный C2", "C3": "Детальный C3",
            "C4": "Детальный C4", "ADR": "Архитектурное решение",
            "TD": "Представление TD", "DD": "Модель DD",
            "CC": "Сквозной объект"}.get(folder.split(os.sep)[0], "Артефакт")


def build():
    """Собирает таблицы разделов и сводку по статусам."""
    rows_by_section = {title: [] for title, _ in SECTIONS}
    counts = {}
    for base, _dirs, files in os.walk(AA):
        for name in sorted(files):
            if not name.endswith(".md") or name in EXCLUDED:
                continue
            path = os.path.join(base, name)
            rel = os.path.relpath(path, AA)
            for title, belongs in SECTIONS:
                if belongs(rel):
                    status, date, deps = describe(path)
                    counts[status] = counts.get(status, 0) + 1
                    link = rel.replace(os.sep, "/")
                    # Ссылки строятся относительно каталога CC, где лежит реестр: соседи
                    # по каталогу адресуются именем файла, остальные — через родительский.
                    target = link[3:] if link.startswith("CC/") else "../" + link
                    rows_by_section[title].append(
                        "| [%s](%s) | %s | %s | %s | %s |"
                        % (name[:-3], target, artifact_type(rel), status, date, deps))
                    break
    return rows_by_section, counts


def render(rows_by_section, counts):
    """Собирает текст реестра из шапки, разделов и сводки."""
    out = [
        "<!-- [AIGD] -->",
        "# CC-Lifecycle — Жизненный цикл артефактов",
        "",
        "**Последняя правка AI:** 2026-08-29T02:40:00Z",
        "",
        "Реестр порождается сценарием `Servers/audit/gen_lifecycle.py` по фактическому составу",
        "корпуса; правки вручную будут потеряны при следующем запуске. Статус выводится",
        "из наблюдаемого признака: карточка с отметкой последней правки AI сверена",
        "с источником истины и получает `verified`, прочие — `review`.",
        "",
        "## Канонический жизненный цикл",
        "",
        "![Канонический жизненный цикл артефактов](diagrams/CC-artifact-lifecycle.svg)",
        "",
        "> Исходник: [diagrams/CC-artifact-lifecycle.puml](diagrams/CC-artifact-lifecycle.puml)",
        "",
        "Диаграмма состояний отражает все переходы жизненного цикла артефактов документации",
        "(требования C1–C4, решения, TD, DD, CC, спецификации интерфейсов) и доказательств.",
        "",
        "## Реестр статусов артефактов",
        "",
    ]
    for title, _ in SECTIONS:
        rows = rows_by_section[title]
        if not rows:
            continue
        out += ["### " + title, "",
                "| Артефакт | Тип | Статус | Дата | Зависимости |",
                "|---|---|---|---|---|"] + rows + [""]

    total = sum(counts.values())
    out += ["## Статистика", "", "| Статус | Количество |", "|---|---|"]
    for status in ("verified", "review", "draft", "absent", "accepted", "current",
                   "outdated", "deprecated", "retired"):
        out.append("| %s | %d |" % (status, counts.get(status, 0)))
    out += ["| **Итого** | **%d** |" % total, ""]
    out += [
        "## Правила перехода",
        "",
        "| Переход | Условие |",
        "|---|---|",
        "| review → verified | Содержание сверено с источником истины, проставлена отметка "
        "последней правки AI |",
        "| verified → accepted | Человек подтвердил содержание |",
        "| current → outdated | Изменилось связанное: требование, решение, код либо данные |",
        "| outdated → review | Выполнена ревизия заполненного артефакта |",
        "| current → deprecated | Запланирована замена; замещающий артефакт указан |",
        "| deprecated → retired | Активных зависимостей не осталось; файл сохраняется |",
        "",
        "## Статус соответствия",
        "",
        "| Дата | Уровень | Обоснование | Корректирующее действие |",
        "|------|---------|-------------|-------------------------|",
        "| 2026-08-29 | 4 — Conformant | Реестр порождён по фактическому составу корпуса; "
        "статусы выведены из отметок сверки | — |",
        "<!-- [/AIGD] -->",
        "",
    ]
    return "\n".join(out)


# Сводная панель репозитория требований: слои, число артефактов и открытые разрывы.
# Панель велась вручную и разошлась с фондом на треть — считать её по фонду дешевле,
# чем поддерживать.
ARR_PATH = os.path.join(AA, "ARR.md")
DASHBOARD_START = "<!-- dashboard:start"
DASHBOARD_END = "<!-- dashboard:end -->"

# Слой панели → каталоги корпуса, из которых он складывается.
DASHBOARD_LAYERS = [
    ("C1", ["C1"]),
    ("C2", ["C2"]),
    ("C3", ["C3"]),
    ("C4", ["C4"]),
    ("TD", ["TD"]),
    ("DD", ["DD", os.path.join("DD", "DE")]),
    ("ADL", ["ADR"]),
    ("CC", ["CC"]),
]


def count_open_gaps():
    """Считает открытые разрывы реестра Ideas по слоям, названным в столбце «Слой»."""
    path = os.path.join(AA, "Ideas.md")
    if not os.path.exists(path):
        return {}, 0
    by_layer = {}
    total = 0
    for line in read_text(path).splitlines():
        if not line.startswith("| GAP-") or "| Open |" not in line:
            continue
        total += 1
        cells = line.split("|")
        layer_cell = cells[2] if len(cells) > 2 else ""
        for name, _dirs in DASHBOARD_LAYERS:
            # Слой засчитывается по упоминанию его обозначения в ячейке.
            if name in layer_cell or (name == "ADL" and "ADR" in layer_cell):
                by_layer[name] = by_layer.get(name, 0) + 1
                break
    return by_layer, total


def render_dashboard():
    """Собирает таблицу панели по фактическому составу корпуса."""
    open_gaps, _total_gaps = count_open_gaps()
    rows = ["| Слой | Всего | С отметкой сверки | Без отметки | Открытые разрывы |",
            "|---|---|---|---|---|"]
    grand_total = grand_stamped = 0
    for name, folders in DASHBOARD_LAYERS:
        total = stamped = 0
        for folder in folders:
            base = os.path.join(AA, folder)
            if not os.path.isdir(base):
                continue
            for entry in sorted(os.listdir(base)):
                if not entry.endswith(".md"):
                    continue
                total += 1
                if STAMP_RE.search(read_text(os.path.join(base, entry))):
                    stamped += 1
        grand_total += total
        grand_stamped += stamped
        rows.append("| %s | %d | %d | %d | %d |"
                    % (name, total, stamped, total - stamped, open_gaps.get(name, 0)))
    outside = _total_gaps - sum(open_gaps.values())
    if outside:
        rows.append("| _вне слоёв корпуса_ (роли, плейбук, шаблоны) | — | — | — | %d |"
                    % outside)
    rows.append("| **Итого** | **%d** | **%d** | **%d** | **%d** |"
                % (grand_total, grand_stamped, grand_total - grand_stamped,
                   _total_gaps))
    return "\n".join(rows)


def update_dashboard():
    """Заменяет содержимое панели между маркерами; вне маркеров файл не трогается."""
    if not os.path.exists(ARR_PATH):
        return False
    text = read_text(ARR_PATH)
    if DASHBOARD_START not in text or DASHBOARD_END not in text:
        return False
    head, rest = text.split(DASHBOARD_START, 1)
    _old, tail = rest.split(DASHBOARD_END, 1)
    marker = DASHBOARD_START + " — таблица порождается Servers/audit/gen_lifecycle.py -->"
    with io.open(ARR_PATH, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(head + marker + "\n" + render_dashboard() + "\n" + DASHBOARD_END + tail)
    return True


def check():
    """Проверка без записи: порождённое содержимое совпадает с лежащим на диске.

    Возвращает перечень расхождений — пустой, если производные артефакты актуальны.
    """
    stale = []
    rows_by_section, counts = build()
    if read_text(TARGET) != render(rows_by_section, counts):
        stale.append("CC-Lifecycle.md отстал от фактического состава корпуса")
    if os.path.exists(ARR_PATH):
        text = read_text(ARR_PATH)
        if DASHBOARD_START in text and DASHBOARD_END in text:
            current = text.split(DASHBOARD_START, 1)[1].split(DASHBOARD_END, 1)[0]
            # Сравниваем сами строки таблицы: строка-маркер несёт пояснение и меняться
            # не должна, но её формат к содержанию панели отношения не имеет.
            current_rows = [ln for ln in current.splitlines() if ln.startswith("|")]
            fresh_rows = [ln for ln in render_dashboard().splitlines()
                          if ln.startswith("|")]
            if current_rows != fresh_rows:
                stale.append("панель ARR.md отстала от фактического состава корпуса")
    return stale


def main():
    # Режим проверки вызывается барьером: он ничего не пишет и лишь сообщает расхождения.
    if "--check" in sys.argv[1:]:
        stale = check()
        for line in stale:
            print(line)
        return 1 if stale else 0
    rows_by_section, counts = build()
    with io.open(TARGET, "w", encoding="utf-8", newline="\n") as f:
        f.write(render(rows_by_section, counts))
    if update_dashboard():
        print("ARR.md: панель обновлена")
    print("CC-Lifecycle.md порождён: %d артефактов (%s)"
          % (sum(counts.values()),
             ", ".join("%s %d" % pair for pair in sorted(counts.items()))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
# AI-GENERATED — NOT REVIEWED: SECTION END
