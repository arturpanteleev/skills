#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Генератор страницы Flash Sprint (шаблон скилла flash-sprint).

Запуск:  python3 build.py [ПАПКА_СПРИНТА] [--out sprint.html]

В папке спринта лежат данные (описания) и состояние отдельно:
  tasks.json         groups, batches, globalHuman, tasks[]  — см. README.md рядом
  intro.json         number, lead, story[], focus[], details[], keywords[]
  sprint_status.json {updatedAt, statuses{ID: 0..6}} — состояние, генератор его не меняет
Оформление и скрипт берутся из sprint.css и sprint.js рядом с этим файлом.
"""
import argparse
import html
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
JIRA = "https://jira.propellerads.net/browse/"
STATUS_LABELS = ["Не взято", "В работе", "Ревью", "Смержено", "На проде", "Готово без PR", "Нужен человек"]
STEPS = [(0, "Не взято"), (1, "В работе"), (2, "Ревью"), (3, "Смержено"), (4, "На проде")]
# Приоритет для людей: три ступени. P0 — максимальный, P1 — средний, P2 и P3 — минимальный.
TIER_OF = {"P0": 1, "P1": 2, "P2": 3, "P3": 3}
TIER_NAME = {1: "Максимальный", 2: "Средний", 3: "Минимальный"}
TIER_WHY = {
    1: "Делаем первыми: от этого зависят другие задачи или горят сроки.",
    2: "Основная работа спринта. Берём по порядку после максимальных.",
    3: "Берём, когда освободятся руки. Можно переносить на следующий спринт.",
}
# Ключевые слова, которые выделяются жирным в описаниях (первое вхождение в абзаце). Можно переопределить в intro.json.
DEFAULT_KEYWORDS = [
    r"планировщик\w*", r"аналитик\w*", r"круг\w* добора", r"баз\w* зоны", r"карт\w* свидетельств", r"диспетчер\w*",
    r"каталог\w* проверок", r"триаж\w*", r"лаборатори\w*", r"карточк\w* агента", r"схем\w* агента",
]

e = lambda s: html.escape(str(s), quote=True)

_CODE = re.compile(
    r"(?<![\w/`.-])("
    r"[\w./-]+\.(?:ts|tsx|md|yml|json|py|sql|html|css|mjs)\b"
    r"|(?:src|docs|scripts|tests|deploy)/[\w./-]+"
    r"|[a-z][a-z0-9]*(?:_[a-z0-9]+)+"
    r"|[a-z]+[A-Z][A-Za-z0-9]+"
    r"|[A-Z][A-Z0-9]*(?:_[A-Z0-9]+){1,}"
    r"|\w+\(\)"
    r"|(?:GET|POST) /[\w/.-]+"
    r"|make [a-z][a-z-]*"
    r")(?![\w`])")
_LABEL = re.compile(r"^([А-ЯЁ][^:.\n]{2,45}):")


def make_md(keywords):
    kw = [re.compile(r"(?<![а-яёА-ЯЁ])(" + k + r")(?![а-яё])", re.I) for k in keywords]

    def md(text, code=True, bold_kw=True):
        """`код`, **жирный**, *курсив*, автоссылки NX-NN / CD-NNN / AR-NNN; идентификаторы — как код."""
        out = []
        for i, part in enumerate(re.split(r"(`[^`]+`)", str(text))):
            if i % 2 == 1:
                out.append("<code>" + e(part[1:-1]) + "</code>")
                continue
            seg = e(part)
            if bold_kw:
                for r in kw:
                    seg = r.sub(lambda m: "<b>" + m.group(1) + "</b>", seg, count=1)
            if code:
                seg = _CODE.sub(lambda m: "<code>" + m.group(1) + "</code>", seg)
            out.append(seg)
        t = "".join(out)
        t = re.sub(r"\*\*([^*]+?)\*\*", r"<b>\1</b>", t)
        t = re.sub(r"(?<![\w*])\*([^*\s][^*]*?)\*(?![\w*])", r"<i>\1</i>", t)
        t = re.sub(r'(?<![\w#"/>-])(NX-\d\d)(?![\w"-])', r'<a href="#\1">\1</a>', t)
        t = re.sub(r'(?<![\w#"/>-])((?:CD|AR)-\d+)(?![\w"-])',
                   lambda m: '<a href="' + JIRA + m.group(1) + '" target="_blank" rel="noopener">' + m.group(1) + "</a>", t)
        return t

    def para(p):
        """Абзац подробностей: метка в начале («Сейчас:», «Приёмка:») — жирным, остальное обычным текстом."""
        m = _LABEL.match(p)
        if m and not re.search(r"[`*<>/]", m.group(1)):
            return "<p><b>" + e(m.group(1)) + ":</b>" + md(p[m.end():]) + "</p>"
        return "<p>" + md(p) + "</p>"

    return md, para


def addressee(text):
    head = text.split(":", 1)[0] if ":" in text[:90] else ""
    low = text.lower()
    if low.startswith(("проверка по времени", "перепроверить", "дождаться")):
        return "Проверка по времени"
    if low.startswith("подтолкнуть") or "ar-1" in low[:40]:
        return "Заявки и доступы"
    if head.startswith("Артур") or low.startswith(("решение:", "решение владельца")):
        return "Артур"
    if head.startswith("Владелец") or low.startswith("владелец"):
        return "Владелец"
    if any(w in head.lower() for w in ("ревьюер", "автор", "второй человек")):
        return "Ревьюеры"
    return "Команды и другие люди" if head else "Общее"


HUMAN_ORDER = ["Артур", "Владелец", "Ревьюеры", "Команды и другие люди", "Заявки и доступы", "Проверка по времени", "Общее"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir", nargs="?", default=".")
    ap.add_argument("--out", default="sprint.html")
    a = ap.parse_args()
    root = Path(a.dir).resolve()
    tasks_data = json.loads((root / "tasks.json").read_text(encoding="utf-8"))
    intro = json.loads((root / "intro.json").read_text(encoding="utf-8")) if (root / "intro.json").exists() else {}
    state_path = root / "sprint_status.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {"updatedAt": 0, "statuses": {}}
    md, para = make_md(intro.get("keywords", DEFAULT_KEYWORDS))

    groups = {g["id"]: g for g in tasks_data["groups"]}
    batches = {b["id"]: b for b in tasks_data.get("batches", [])}
    tasks = tasks_data["tasks"]
    ids = [t["id"] for t in tasks]
    if len(ids) != len(set(ids)):
        sys.exit("дубли ID")
    for t in tasks:
        if t["group"] not in groups:
            sys.exit(f"{t['id']}: неизвестная группа {t['group']}")
        if t["priority"] not in TIER_OF:
            sys.exit(f"{t['id']}: неизвестный приоритет {t['priority']}")
        if t.get("batch") and t["batch"] not in batches:
            sys.exit(f"{t['id']}: неизвестный пакет {t['batch']}")
        if not t.get("what"):
            print(f"предупреждение: у {t['id']} нет поля what (описание простым языком)", file=sys.stderr)
    statuses = dict(state.get("statuses", {}))
    orphans = sorted(set(statuses) - set(ids))
    if orphans:
        print("осиротевшие статусы:", ", ".join(orphans), file=sys.stderr)
    for i in ids:
        statuses.setdefault(i, 0)
        if statuses[i] not in range(len(STATUS_LABELS)):
            sys.exit(f"{i}: неизвестный статус {statuses[i]}")
    statuses = {i: statuses[i] for i in ids}

    gpos = {g["id"]: i for i, g in enumerate(tasks_data["groups"])}
    order = sorted(tasks, key=lambda t: (TIER_OF[t["priority"]], gpos[t["group"]], t["id"]))
    members = {b: [t["id"] for t in order if t.get("batch") == b] for b in batches}
    by = {t["id"]: t for t in tasks}

    # пункты «нужно от людей»
    hitems, hids = [], {}
    for text in tasks_data.get("globalHuman", []):
        hitems.append((f"H-{len(hitems) + 1:02d}", None, text))
    for t in order:
        for text in t.get("human", []):
            hid = f"H-{len(hitems) + 1:02d}"
            hitems.append((hid, t, text))
            hids.setdefault(t["id"], []).append(hid)

    def jira_links(keys):
        return " ".join(f'<a class="jira" href="{JIRA}{e(k)}" target="_blank" rel="noopener">{e(k)}</a>' for k in keys)

    def batch_line(t):
        b = t.get("batch")
        if not b:
            return '<div class="batch">Без пакета: берётся отдельно.</div>'
        others = ", ".join(f'<a href="#{e(m)}">{e(m)}</a>' for m in members[b] if m != t["id"]) or "нет"
        return (f'<div class="batch">Пакет <b>{e(b)} · {e(batches[b]["title"])}</b>: задачи пакета делаем одним PR. '
                f'Вместе с: {others}</div>')

    def card(t, n):
        tier = TIER_OF[t["priority"]]
        g = groups[t["group"]]
        what = f'<p class="what">{md(t["what"], code=False)}</p>' if t.get("what") else ""
        needs = ""
        if t["id"] in hids:
            needs = '<div class="needs">Нужно от человека: ' + ", ".join(f'<a href="#{e(h)}">{e(h)}</a>' for h in hids[t["id"]]) + "</div>"
        steps = "".join(
            f'<button class="step" type="button" data-s="{i}"><span class="pin"></span>{e(l)}</button>' for i, l in STEPS)
        det = "".join(para(p) for p in t["body"])
        jr = jira_links(t.get("jira", [])) or '<span class="jira">Jira: заведём после согласования</span>'
        return f"""
<article class="card" id="{e(t['id'])}" data-tier="{tier}" data-theme="{e(t['group'])}" data-status="0">
  <div class="chead"><span class="tid">{e(t['id'])}</span><span class="tier t{tier}">{TIER_NAME[tier]}</span><span class="type">{e(t['type'])}</span>{jr}<span class="theme">{e(g['title'])}</span></div>
  <h3 class="ctitle">{md(t['title'], code=False, bold_kw=False)}</h3>
  {what}{needs}
  <div class="path" role="group" aria-label="Статус {e(t['id'])}">{steps}</div>
  <div class="side"><button class="okb" type="button" data-s="5">Готово без PR</button><button type="button" data-s="6">Нужен человек</button></div>
  <details class="more"><summary>Подробности для исполнителя</summary>
    {det}
    {batch_line(t)}
  </details>
</article>"""

    cards = "".join(card(t, n) for n, t in enumerate(order, 1))

    # шапка
    number = intro.get("number", "")
    title = f"Flash Sprint {number}".strip()
    story = "".join(f"<p>{md(p, code=False)}</p>" for p in intro.get("story", []))
    titles_of = lambda idl: "".join(f'<li><a href="#{e(i)}">{e(i)}</a> {md(by[i]["title"], code=False, bold_kw=False)}</li>' for i in idl if i in by)
    focus = "".join(
        f'<section class="focus"><h3>{e(f["title"])}<span class="n">{len(f["ids"])}</span></h3><p>{md(f["text"], code=False)}</p>'
        f'<details><summary>Задачи</summary><ul>{titles_of(f["ids"])}</ul></details></section>'
        for f in intro.get("focus", []))
    tiers = ""
    for tier in (1, 2, 3):
        idl = [t["id"] for t in order if TIER_OF[t["priority"]] == tier]
        if not idl:
            continue
        chips = "".join(f'<a class="chip" href="#{e(i)}" title="{e(by[i]["title"])}">{e(i)}</a>' for i in idl)
        tiers += (f'<div class="tier-row tier-{tier}"><div><h3><span class="dot"></span>{TIER_NAME[tier]} · {len(idl)}</h3>'
                  f'<div class="why">{TIER_WHY[tier]}</div></div><div class="chips">{chips}</div></div>')
    theme_opts = "".join(f'<option value="{e(g["id"])}">{e(g["title"])}</option>' for g in tasks_data["groups"])

    # люди
    grouped = {}
    for h, t, text in hitems:
        grouped.setdefault(addressee(text), []).append((h, t, text))
    horder = [g for g in HUMAN_ORDER if g in grouped] + [g for g in grouped if g not in HUMAN_ORDER]
    hsec = ""
    for g in horder:
        rows = ""
        for h, t, text in grouped[g]:
            ref = "<i>общее</i>"
            if t:
                ref = f'<a href="#{e(t["id"])}">{e(t["id"])}</a> ' + jira_links(t.get("jira", [])) + f'<span class="tt">{md(t["title"], code=False, bold_kw=False)}</span>'
            rows += f'<li id="{e(h)}"><label><input type="checkbox" data-h="{e(h)}"> <span class="hid">{e(h)}</span></label> {ref}<div class="tx">{md(text)}</div></li>'
        hsec += f'<div class="hg"><h3>{e(g)} <small>{len(grouped[g])}</small></h3><ol>{rows}</ol></div>'

    det = "".join(f"<p>{md(p)}</p>" for p in intro.get("details", []))
    anchors = lambda idl: ", ".join('<a href="#%s">%s</a>' % (e(m), e(m)) for m in idl)
    blist = "".join(
        f'<li><b>Пакет {e(b["id"])} · {e(b["title"])}</b>: {anchors(members[b["id"]])}'
        f'<br><span class="sub">{md(b["files"])}</span></li>' for b in tasks_data.get("batches", []))
    pack = ('<section class="block"><h2>Как делаем</h2>'
            '<p class="intro sub" style="margin:10px 0 0">Задачи, которые правят одни и те же файлы, объединяем в <b>пакеты</b>. Один пакет — один PR. Пакеты не пересекаются по файлам, поэтому их можно делать параллельно.</p>'
            f'<div class="hg" style="margin-top:14px"><details open><summary>Какие пакеты и какие в них задачи</summary><ul>{blist}</ul>{det}</details></div></section>')

    state_json = json.dumps({"version": 1, "sprintId": tasks_data["sprintId"], "updatedAt": state.get("updatedAt", 0), "statuses": statuses},
                            ensure_ascii=False).replace("</", "<\\/")
    css = (HERE / "sprint.css").read_text(encoding="utf-8")
    js = (HERE / "sprint.js").read_text(encoding="utf-8")
    page = f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Golos+Text:wght@400;500;600;700&family=Unbounded:wght@500;600;700&family=JetBrains+Mono:wght@400;500&display=swap">
<style>{css}</style></head>
<body><main>
<div class="eyebrow">{e(tasks_data.get("product", ""))}</div>
<h1>{e(title)}</h1>
<p class="lead">{md(intro.get("lead", ""), code=False)}</p>
<div class="progress" id="bar" role="img" aria-label="Прогресс спринта"></div><div class="pkey" id="pkey"></div>

<section class="block intro"><h2>На чём концентрируемся</h2>{story}</section>
<div class="focusgrid">{focus}</div>

<section class="block"><h2>В каком порядке</h2><p class="sub" style="margin:8px 0 0">Приоритет считается по трём ступеням. Внутри ступени задачи идут по темам.</p><div class="tiers">{tiers}</div></section>

<div class="toolbar">
  <div class="frow"><span class="lbl">Приоритет</span>
    <button type="button" data-f="tier" data-v="all" aria-pressed="true">Все</button>
    <button type="button" data-f="tier" data-v="1" aria-pressed="false">Максимальный</button>
    <button type="button" data-f="tier" data-v="2" aria-pressed="false">Средний</button>
    <button type="button" data-f="tier" data-v="3" aria-pressed="false">Минимальный</button>
    <span class="lbl" style="margin-left:12px">Статус</span>
    <button type="button" data-f="st" data-v="all" aria-pressed="true">Все</button>
    <button type="button" data-f="st" data-v="open" aria-pressed="false">Не закончены</button>
    <button type="button" data-f="st" data-v="done" aria-pressed="false">На проде или готовы</button>
    <span class="count" id="count"></span></div>
  <div class="frow"><span class="lbl">Тема</span><select id="theme" aria-label="Тема"><option value="all">Все темы</option>{theme_opts}</select>
    <button type="button" id="toggleAll" style="margin-left:12px">Развернуть подробности</button><a href="#human">Что нужно от людей ({len(hitems)})</a><button type="button" id="export" style="margin-left:auto">Скачать статусы</button></div>
</div>
<div class="cards">{cards}</div>

<section class="block" id="human"><h2>Что нужно от людей</h2><p class="sub" style="margin:8px 0 0">Сгруппировано по адресату. Галочки сохраняются только в этом браузере.</p><div class="humangrid">{hsec}</div></section>
{pack}
</main>
<script id="state" type="application/json">{state_json}</script>
<script>{js}</script>
</body></html>
"""
    out = root / a.out
    out.write_text(page, encoding="utf-8")
    print(f"ok: {len(tasks)} карточек, {len(hitems)} пунктов для людей -> {out}")


if __name__ == "__main__":
    main()
