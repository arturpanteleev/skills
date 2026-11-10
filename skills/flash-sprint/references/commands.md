# Команды

Сантехника спринта. Имена подставляй под проект; сами проверки всегда берутся из репозитория,
а не отсюда. Команды разведки и аудита — в `discovery.md` и `probes.md`.

## Предусловия перед правкой кода

```sh
git status --porcelain        # определить параллельные изменения и не затронуть их
git fetch --prune
git log --oneline -10
```

## Ветка в основном чекауте (вариант по умолчанию)

```sh
git switch -c <branch> origin/<base>
```

## Worktree (только параллельные задачи или рискованный рефактор)

Worktree — это чистый чекаут: всё, что в `.gitignore`, туда не приезжает. Прежде чем верить
любой проверке, запущенной внутри него, убедись, что окружение воспроизведено:

```sh
git -C <repo> check-ignore -v node_modules .env   # что будет отсутствовать
git worktree add ../wt-<item> -b <branch> origin/<base>
# затем: воспроизвести зависимости и разрешённую конфигурацию по правилам проекта; не копировать секреты автоматически.
# Если этот первый прогон падает по причинам окружения — worktree непригоден: возвращайся
# к ветке в основном чекауте и скажи об этом.
git worktree remove ../wt-<item>                   # когда задача дошла до терминального статуса
```

## Обязательные проверки

Ищи их, а не угадывай: `package.json` scripts, `Makefile`, `justfile`, `pyproject.toml`,
файлы CI-workflow. Отсутствие гейта — само по себе finding.

```sh
gh pr checks <pr>                                        # или CLI своего хостинга
gh pr view <pr> --json state,mergeable,statusCheckRollup,headRefOid
```

## Ожидание CI вне модели

```sh
# Только переходы состояния (CLEAN / BEHIND / DIRTY / fail / MERGED), выход при MERGED всех.
# Запускать у оркестратора через Monitor или в фоне, а не в цикле внутри агента.
<путь к скилу>/scripts/pr-watch.sh -i 90 <pr> [<pr> ...]
gh run rerun <run-id> --failed       # флейк — перезапуск без агента
```

## Свежесть ветки

```sh
git rev-list --left-right --count origin/<base>...HEAD   # левое число > 0 — база уехала
```

База уехала — проверь требования проекта к актуальности ветки. Если для изменения нужен rebase/merge базы, сохрани чужую работу и перезапусти требуемые проверки на итоговом commit. Не переписывай опубликованную ветку без учёта её владельца.

## Перед одобрением

```sh
git diff --check
git diff origin/<base>...HEAD --stat
```

## Возобновление

```sh
git branch -vv
git worktree list
gh pr list --state open
gh pr view <pr> --json state,statusCheckRollup,headRefOid
```

Сверь запомненный статус каждой задачи с тем, что показывают эти команды, и поправь статус.
