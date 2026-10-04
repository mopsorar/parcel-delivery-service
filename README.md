# parcel-delivery-service

Асинхронный сервис международной доставки на FastAPI. Регистрирует посылки,
изолирует данные по клиентской сессии и рассчитывает стоимость доставки в рублях
по курсу USD/RUB из внешнего API с Redis-кэшем.

Реализована parcel-часть задания и дополнительное задание №3: конкурентно-безопасная
привязка своей посылки к транспортной компании. RAG, Vector DB и LLM намеренно
не реализованы.
README содержит инструкции, архитектурные решения и известные ограничения проекта.

## Стек и структура

Python 3.13+, FastAPI, Pydantic, pydantic-settings, SQLAlchemy asyncio, asyncpg,
PostgreSQL, httpx и redis.asyncio. Зависимости управляются только через uv и
зафиксированы в `uv.lock`. Для проверок используются pytest, Ruff и pre-commit.

```text
src/parcel_delivery/
  api/                  HTTP endpoints, schemas, session dependency, request logging
  db/                   AsyncEngine, session factory, dependencies, ORM models
  integrations/         HTTP exchange-rate client и общий async Redis client
  services/             Операции с посылками, cache-aside, расчёт стоимости
  tasks/                Периодический asyncio loop
  config.py             Settings из environment / .env
  logging_config.py     Единая конфигурация стандартного logging
  main.py               FastAPI и lifespan ресурсов
alembic/                Схема БД и справочные данные
tests/                  API, PostgreSQL, Redis, unit-тесты и mocked integrations
.github/workflows/      CI: тесты и Docker smoke test
```

Router отвечает за HTTP, валидацию и вызов service. SQL выполняется в service,
а не в router. Для чтения посылок один JOIN с ParcelType возвращает имя типа,
без relationship и N+1. Ошибка неизвестного типа или отсутствующей своей посылки
преобразуется из доменного исключения в HTTP 404.

## Запуск через Docker Compose

Нужны Docker Engine / Docker Desktop с Linux containers и Docker Compose v2.
Все команды выполняются из каталога с `pyproject.toml` и `compose.yaml`.

1. Создайте `.env` из `.env.example`, **только если своего `.env` ещё нет**:

   ```powershell
   Copy-Item .env.example .env
   ```

   На Linux/macOS: `cp .env.example .env`.

2. Укажите собственный непустой `DB_PASSWORD`. Он не хранится в Git и не попадает
   в образ. Не используйте CI-пароли из workflow для своего окружения.

3. Соберите и запустите сервис:

   ```bash
   docker compose config --quiet
   docker compose up --build --detach --wait --wait-timeout 120
   docker compose ps --all
   ```

   Обычный `docker compose up --build` также работает, выводя логи в терминал.

Приложение: <http://localhost:8000>. Swagger: <http://localhost:8000/docs>.
OpenAPI: <http://localhost:8000/openapi.json>.

Compose поднимает PostgreSQL, официальный Redis, одноразовый `migrate` и `app`.
Healthcheck PostgreSQL проверяет TCP, чтобы не принять временный сервер начальной
инициализации за готовую БД. `migrate` выполняет `alembic upgrade head` после готовности
PostgreSQL; `app` ждёт готовности PostgreSQL и успешного завершения миграций.
Ошибка миграций блокирует запуск приложения. Redis — необязательный кэш, поэтому
его healthcheck не является условием запуска `app`; при недоступности используется
внешний API. Команда `compose up --wait` всё же может сообщить об unhealthy Redis:
она проверяет все сервисы, хотя само приложение продолжает работать.

Миграции не запускаются в lifespan или в entrypoint каждой реплики. На одно
Compose-развёртывание есть один migration job. При обновлении схемы пересоздайте
его: `docker compose up --build --force-recreate --detach --wait --wait-timeout 120`.
Для нескольких app-реплик нужен отдельный override публикации портов и балансировщик;
фиксированный host-порт базового Compose рассчитан на одну реплику. При общем внешнем
PostgreSQL миграции разных deployment jobs необходимо сериализовать на уровне deployment.

PostgreSQL хранит данные в named volume `postgres_data`. Redis хранит только
восстанавливаемый кэш, без persistence и без публикации порта на хост. PostgreSQL
также не публикует порт. Внутри контейнеров используются `postgres:5432` и `redis:6379`:
Compose явно переопределяет локальные `DB_HOST`/`REDIS_HOST` из `.env`.

HTTP-порт по умолчанию привязан к `127.0.0.1:8000`. Его номер можно изменить переменной
окружения `APP_PORT` при запуске Compose; для публичного размещения настройте reverse proxy
и HTTPS. Не добавляйте `APP_PORT` в общий `.env`: этот файл также читает строгий Settings
приложения, в котором такой настройки нет.

```bash
docker compose logs --follow app migrate
docker compose exec app alembic current
docker compose exec app alembic check
docker compose down
```

`down` сохраняет данные. **`docker compose down --volumes` удаляет PostgreSQL volume**:
используйте только для намеренного сброса тестового окружения, не для обычной остановки.
Изменение `DB_PASSWORD` в `.env` не меняет пароль уже инициализированной БД;
для существующего volume пароль нужно менять в PostgreSQL.

### Образ приложения

`Dockerfile` использует Python `3.13.16-slim-bookworm` и uv `0.11.8` в builder.
Сначала устанавливаются locked runtime-зависимости, затем копируется исходный код:
изменение приложения не инвалидирует слой зависимостей. `uv sync --locked --no-dev`
проверяет актуальность lockfile, а `--no-editable` устанавливает пакет независимо от
исходного дерева. В runtime копируются только venv и Alembic; uv, dev-зависимостей,
локального `.venv`, тестов и `.env` в нём нет.

Процесс работает с UID/GID 10001. Compose включает read-only filesystem, временный
`/tmp`, сброс capabilities и `no-new-privileges`. Uvicorn запускается без reload.
Теги образов закреплены по версиям; для побитовой воспроизводимости registry-образов
в будущем можно дополнительно закрепить digests и регулярно обновлять их.
Рекомендации по сборке: [uv Docker guide](https://docs.astral.sh/uv/guides/integration/docker/).
Порядок запуска: [Compose startup order](https://docs.docker.com/compose/how-tos/startup-order/).

## Локальный запуск без Docker

Нужны uv, Python 3.13+ и работающий PostgreSQL. Для кэша рекомендуется обычный Redis;
без него приложение использует внешний API. Redis можно запускать
на Linux/WSL. Production-код не использует Memurai API, Windows services или платформенные
пути; Docker и CI используют официальный Redis image.

Создайте PostgreSQL database и пользователя. Например, при настроенном административном
доступе к PostgreSQL:

```bash
createuser --pwprompt parcel_delivery
createdb --owner=parcel_delivery parcel_delivery
```

Создайте `.env` из шаблона, не перезаписывая имеющийся файл, и заполните настройки:

| Переменная | Назначение / значение в шаблоне |
| --- | --- |
| `LOG_LEVEL` | Уровень логов, `INFO` |
| `DB_HOST`, `DB_PORT` | Локальный PostgreSQL, `localhost`, `5432` |
| `DB_NAME`, `DB_USER` | БД и пользователь, `parcel_delivery` |
| `DB_PASSWORD` | Собственный пароль; в шаблоне пустой |
| `REDIS_HOST`, `REDIS_PORT`, `REDIS_DB` | `127.0.0.1`, `6379`, `0` |
| `EXCHANGE_RATE_CACHE_TTL_SECONDS` | TTL курса, `3600` секунд |
| `DELIVERY_COST_BATCH_SIZE` | Максимум посылок за один расчёт, `100` (1–10000) |

Settings читает `.env` относительно текущего рабочего каталога. Environment имеет
приоритет над `.env`; неизвестные поля в `.env` не принимаются.
Settings сразу проверяет TTL > 0, порты 1–65535, Redis DB >= 0 и размер batch.
LOG_LEVEL принимает DEBUG, INFO, WARNING, ERROR, CRITICAL, NOTSET без учёта регистра;
WARN/FATAL нормализуются в WARNING/CRITICAL. Некорректная конфигурация останавливает
запуск при создании Settings, а не обнаруживается посреди запроса.

```bash
uv sync --locked
uv run --locked alembic upgrade head
uv run --locked uvicorn parcel_delivery.main:app --host 127.0.0.1 --port 8000
```

Для разработки можно добавить `--reload`. Для доступа к курсу нужен исходящий HTTPS
к `www.cbr-xml-daily.ru`; регистрация и чтение посылок не зависят от этого API.

## Миграции и PostgreSQL

```bash
uv run --locked alembic current
uv run --locked alembic heads
uv run --locked alembic upgrade head
uv run --locked alembic check
```

Цепочка: `38e6bf8af41d` создаёт `parcel_types`/`parcels`, `6586eaff6f0e` добавляет
`clothes`, `electronics`, `misc`, `a7c1e42b9d60` добавляет nullable transport_company_id
и CHECK положительного конечного целого; `b4f7c29d8e61` добавляет partial index
`id WHERE delivery_cost_rub IS NULL` для упорядоченных ограниченных batches.
Старые посылки остаются валидными с NULL в transport_company_id.
ID типов не фиксированы: клиент получает ID через API.
Настоящие денежные значения и вес — Decimal / PostgreSQL Numeric, не float.
Есть FK на тип, ограничения положительного веса/стоимости содержимого и индекс
`(session_id, type_id)` для списков своей сессии.

Downgrade seed-миграции намеренно сохраняет справочник: удаление используемых типов
нарушило бы FK либо потребовало удаления посылок. Upgrade использует ON CONFLICT
DO NOTHING по имени, поэтому повторное применение не создаёт дублей. Только downgrade
самой схемы удаляет таблицы. Новая индексная миграция использует обычный CREATE INDEX;
для большой рабочей таблицы её следует применять в согласованное окно обслуживания.

`alembic check` проверяет отсутствие изменений ORM metadata относительно текущей
схемы, но не заменяет review самих миграций и не проверяет справочные данные.
Для изменения схемы используйте `uv run alembic revision --autogenerate -m "description"`
и проверьте созданную миграцию вручную. `downgrade` может удалить данные — не выполняйте
его на рабочей БД без отдельного решения и резервной копии.

## Сессии и API

Полноценной auth нет. Клиент идентифицируется UUID-cookie `session_id`. Если cookie
отсутствует или некорректна, создаётся UUID4 с `HttpOnly` и `SameSite=Lax`. Отдельной
таблицы сессий и TTL сессии нет: UUID хранится в `Parcel.session_id`, cookie сессионная.
Клиент должен сохранять cookie между запросами. Swagger в том же браузере делает это
автоматически; для curl используйте cookie jar (`-c` / `-b`).

Все чтения пользовательских посылок фильтруются по текущему UUID. Для одной посылки
условие включает **одновременно** ID и session_id. Чужая и отсутствующая посылки
возвращают одинаковый 404, без раскрытия принадлежности. Знание только parcel ID
недостаточно, но украденная session cookie даёт доступ: это идентификация, не auth.

| Метод и путь | Поведение |
| --- | --- |
| `GET /health` | `200`, `{"state": "healthy"}`; liveness, не проверка внешних зависимостей |
| `GET /parcel-types` | Публичный список `id`/`name`, по ID, без создания сессии |
| `POST /parcels` | Регистрация, `201`, `{"id": int}` |
| `GET /parcels` | Список только своей сессии, пустой список допустим |
| `GET /parcels/{parcel_id}` | Своя посылка либо `404`; ID в диапазоне PostgreSQL INTEGER |
| `POST /parcels/{parcel_id}/transport-company` | Первая привязка компании — `200`; повторная — `409`; чужая/отсутствующая — `404` |
| `POST /parcels/calculate-delivery-costs` | Debug: один ограниченный batch, `{"processed_count": int}` |

Пример JSON регистрации (используйте существующий `type_id` из `/parcel-types`):

```json
{
  "name": "Laptop",
  "weight": "1.250",
  "type_id": 1,
  "content_value_usd": "500.00"
}
```

Название не пустое после trim, вес и стоимость содержимого > 0, type_id > 0;
лишние поля запрещены. Точность соответствует Numeric в БД: вес — до 10 цифр всего
и 3 после запятой, USD стоимость — до 12 цифр всего и 2 после запятой. Значения,
которые БД округлила бы до нуля или не смогла сохранить, отклоняются заранее.
Неизвестный тип — 404, ошибки валидации — 422.
ID посылки и типа ограничены 1–2147483647 во всех path/query/body параметрах;
offset — 0–2147483647, в соответствии с INTEGER bind текущего SQLAlchemy/asyncpg
запроса. Выход за диапазон всегда даёт 422, без отправки неподходящего числа в БД.
Это не ограничивает company_id: он хранится как NUMERIC.
ID новой посылки доступен после INSERT RETURNING при commit; expire_on_commit=False
сохраняет его в ORM-объекте, поэтому дополнительный refresh не выполняется.

`GET /parcels` принимает `limit` (1–100, по умолчанию 20), `offset` (0–2147483647, по умолчанию 0),
`type_id` (1–2147483647, необязательный) и `delivery_cost_calculated` (необязательный bool).
`true` выбирает NOT NULL стоимость, `false` — NULL; отсутствие параметра не фильтрует.
Фильтры работают вместе с сессией и пагинацией. Порядок стабильный — Parcel.id;
total/count/pages не возвращаются. Корректный type_id без подходящих посылок даёт `[]`.

В списке и отдельной посылке возвращаются `id`, `name`, `weight`, `type_id`, `type_name`,
`content_value_usd`, `delivery_cost_rub`, `delivery_cost_display` и `transport_company_id`.
ID компании — JSON integer либо null до привязки. Decimal сериализуется
строкой. Для нерассчитанной стоимости числовое поле остаётся `null`, а display равен
`"Не рассчитано"`; после расчёта display содержит сумму с двумя знаками, например `"146.25"`.
Так сохраняется машинный контракт числового поля и выполняется требование отображения.

## Дополнительное задание №3: привязка транспортной компании

У компании есть только ID; отдельной таблицы компаний нет. Пользователь может
назначить компанию только посылке своей сессии:

```http
POST /parcels/42/transport-company
Content-Type: application/json
Cookie: session_id=<UUID текущей сессии>

{"company_id": 123}
```

Успех: `200`, `{"parcel_id": 42, "transport_company_id": 123}`. company_id должен
быть положительным JSON integer: bool, дроби, строки и null дают 422, лишние поля
запрещены. parcel_id должен быть в диапазоне 1–2147483647. Повторная привязка, даже той же компанией,
даёт 409: endpoint не позволяет менять или сбрасывать назначенную компанию.
Отсутствующая и чужая посылки одинаково дают 404, даже если чужая уже привязана.
Низкоуровневые DB/server ошибки остаются 500.

Race condition при `SELECT -> проверка -> UPDATE`: два запроса могут одновременно
увидеть NULL и оба решить, что выиграли; обычный UPDATE второго перезапишет первого.
Python/asyncio Lock не решает это между разными workers или процессами.

Service сразу выполняет один атомарный условный UPDATE:

```sql
UPDATE parcels
SET transport_company_id = :company_id
WHERE id = :parcel_id
  AND session_id = :session_id
  AND transport_company_id IS NULL
RETURNING id, transport_company_id;
```

Приложение явно использует READ COMMITTED. PostgreSQL блокирует изменяемую строку;
конкурентный UPDATE ждёт окончания первой транзакции и после её commit повторно
проверяет WHERE на актуальной строке. Условие IS NULL уже ложно — второй запрос
ничего не изменяет. Если первая транзакция откатывается, другой запрос может выиграть.
Подтверждение успеха возвращается только после commit, не после одного RETURNING.
Гарантия обеспечивается PostgreSQL, работает между разными процессами приложения
и не зависит от локальных Python locks.
[Механизм UPDATE при READ COMMITTED](https://www.postgresql.org/docs/current/transaction-iso.html#XACT-READ-COMMITTED).

Только после UPDATE без результата выполняется SELECT по id **и session_id**, чтобы
различить 404 и 409; он не определяет победителя. На DB-ошибке выполняется rollback;
транзакция также закрывается rollback перед доменными 404/409. Отдельный SELECT/refresh
на успешном пути не нужен: данные ответа получены через RETURNING.

company_id не ограничен искусственным диапазоном 32/64 бит: PostgreSQL NUMERIC
хранит большие значения точно, локальный SQLAlchemy TypeDecorator преобразует
int в Decimal при записи и обратно в int при чтении, без float. CHECK разрешает
NULL либо положительное конечное целое, запрещая дроби, NaN и Infinity.
Изменений таблицы компаний, foreign keys или новых архитектурных слоёв нет.

Конкурентный integration test использует два отдельных request/AsyncSession контекста
и два PostgreSQL backend PID. Третье соединение временно блокирует тестовую строку;
`pg_blocking_pids` подтверждает, что оба UPDATE реально ждут, затем блокировка снимается.
Проверяется ровно один 200, один 409 и company_id победителя в новой DB-сессии.
PostgreSQL не мокируется. Этот тест намеренно использует настоящие commits для
видимости строки между транзакциями и удаляет только собственную запись в finally.

## Курс и расчёт доставки

Источник USD/RUB: <https://www.cbr-xml-daily.ru/daily_json.js>. httpx.AsyncClient
использует timeout 5 секунд и `raise_for_status()`. Курс одной единицы — `Value / Nominal`,
парсинг и вычисление через Decimal; курс должен быть конечным и положительным.

Redis используется как cache-aside, ключ `exchange_rate:usd_rub`:

- cache hit: проверенный Decimal из Redis, без HTTP-запроса;
- cache miss / некорректное значение: внешний API, затем SET с TTL;
- GET упал, в том числе на декодировании повреждённых bytes: warning и внешний API;
- SET упал: warning, успешно полученный курс всё равно возвращается;
- Redis socket/connect timeout — 5 секунд; retry отключены;
- stale/fallback-курс не используется. TTL означает срок кэширования, не возраст данных
  самого ЦБ: источник обновляет котировки по своему расписанию.

Если API недоступен, но кэш содержит курс, расчёт работает. При cache miss и ошибке
API выбрасывается `ExchangeRateError`: ручной endpoint отвечает 503, транзакция
откатывается и освобождает блокировки. Фоновый цикл логирует сбой и продолжает
следующие запуски. Неожиданные DB/server ошибки дают 500, а не 400/404.

```text
delivery_cost_rub = (weight * 0.5 + content_value_usd * 0.01) * usd_rub_rate
```

Все операнды — Decimal. Итог округляется до двух знаков через `ROUND_HALF_UP`.
Обрабатываются только `delivery_cost_rub IS NULL`; уже рассчитанная, включая нулевую,
стоимость не пересчитывается. Сначала выполняется дешёвая проверка наличия pending-строк
без row locks; при отсутствии работы возвращается `processed_count=0` без запроса курса.
Затем курс получается один раз, **до захвата row locks**. Только после этого выбираются
не более DELIVERY_COST_BATCH_SIZE строк по id и обрабатываются за одну транзакцию
с одним commit. Manual endpoint и один периодический запуск обрабатывают ровно один batch,
а не неограниченно осушают очередь. Остаток ждёт следующего запуска или ручного вызова.
Если pending-строки есть, но все заблокированы конкурентами, курс может быть запрошен,
а результат после SKIP LOCKED будет 0; пустая транзакция закрывается rollback.

Выборка использует `SELECT FOR UPDATE SKIP LOCKED`: строки блокируются до commit/rollback,
а другой обработчик пропускает уже занятые строки. Это защищает ручной/фоновый запуск
и разные app-процессы от одновременного расчёта одних посылок. `processed_count=0`
может означать, что доступных незаблокированных строк нет, а не отсутствие работы у других.
Partial index по pending id полезен, когда большая часть истории уже рассчитана:
выборка не сканирует все обработанные посылки. Для маленькой таблицы PostgreSQL может
обоснованно выбрать sequential scan. При DB-ошибке или отмене задачи выполняется rollback;
блокировки освобождаются, и следующий worker может обработать строку.

Lifespan создаёт asyncio task с интервалом 300 секунд. Первый запуск — через 300 секунд
после старта; следующий — через 300 секунд после завершения предыдущего (fixed delay).
Каждый запуск имеет свою AsyncSession. При shutdown задача отменяется и ожидается,
активная сессия закрывается, Redis client закрывается, затем engine.dispose().

## Ошибки и логи

Используется формат ошибок FastAPI с общим полем `detail`: строка для 404/409/503/500,
список описаний валидации для 422. Неожиданный 500 содержит только
`{"detail": "Internal server error"}`, без traceback клиенту.

Стандартный logging конфигурируется через `LOG_LEVEL` при startup. `X-Request-ID`
клиента сохраняется только для 1–128 ASCII-символов: первая позиция — буква/цифра,
остальные — буквы, цифры, `.`, `_`, `-`. Пустое, слишком длинное или некорректное
значение заменяется UUID4; заголовок возвращается в HTTP
response, включая ошибки. ContextVar связывает service/integration-логи с запросом;
у фоновых задач request_id равен `-`.

Access-лог включает method, path, status code, duration_ms и request_id. `/health`
не пишет обычные access-логи. События создания посылки пишут только parcel_id;
расчёт логирует запуск и processed_count; ошибки Redis/API/background task логируются.
Cookies, полный session_id, query string и body не логируются. SQL parameters скрыты,
а SQLAlchemy traceback форматируется без исходного текста ошибки/SQL, который может
содержать чувствительные данные. Для request_id/path применяется escaped representation.

## Тесты и проверки

Используйте отдельную тестовую PostgreSQL БД с применёнными миграциями и работающий Redis.
Не направляйте тесты в production. API-тесты используют внешнюю транзакцию и SAVEPOINT:
service commit не мешает откату тестовых записей. Исключение — PostgreSQL-тесты
конкурентной привязки и расчёта: им нужны видимые независимым сессиям commits и
адресная очистка собственных строк в finally. Тесты расчёта используют независимые
соединения и настоящие row locks; проверяют SKIP LOCKED и освобождение после
rollback/cancellation при всё ещё открытой первой сессии. Курс в них замокирован.
Seed upgrade/downgrade проверяется на временных PostgreSQL-таблицах с настоящим FK.
Старые API-тесты гарантированно вызывают engine.dispose() перед закрытием event loop,
даже при падении assertion; это исключает повторное использование соединений чужого loop.
PostgreSQL sequences не откатываются,
поэтому после тестов ID могут иметь пропуски. ASGITransport-тесты не запускают scheduler.
Внешний API в тестах mock-ируется: интернет для pytest не нужен.

На Linux/macOS для отдельных команд:

```bash
DB_NAME=parcel_delivery_test uv run --locked alembic upgrade head
DB_NAME=parcel_delivery_test uv run --locked pytest
```

В PowerShell задайте переменную в отдельном терминале перед командами:

```powershell
$env:DB_NAME = "parcel_delivery_test"
uv run --locked alembic upgrade head
uv run --locked pytest
```

Тестовая БД должна быть предварительно создана с доступом для указанного DB_USER.
При необходимости переопределите также DB_HOST/PORT/USER/PASSWORD. Остальные настройки
берутся из `.env`. Проверяются API, изоляция, pagination/filters, display стоимости,
расчёт, cache hit/miss и отказы Redis/API, request_id, scheduler/shutdown, Redis PING,
привязка компании, 409/404/422, DB CHECK и реальная конкуренция двух назначений.

```bash
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked pre-commit run --all-files
uv run --locked pre-commit install
```

Последняя команда устанавливает локальный Git hook и не обязательна для запуска приложения.
Локальные pre-commit hooks запускают Ruff lint с `--fix` и форматирование, поэтому могут
изменить файлы; CI выполняет проверки без исправлений.

GitHub Actions проверяет push в dev/main и pull requests. Test job устанавливает
locked-зависимости через uv, запускает PostgreSQL/Redis services с healthchecks,
применяет/проверяет Alembic, выполняет полный pytest и оба Ruff checks. Docker job
валидирует Compose, собирает runtime image, ожидает healthy app и проверяет API,
Swagger, schema consistency, non-root user и отсутствие dev-инструментов/.env.
Он использует одноразовые CI-пароли и не нуждается в локальных секретах. Файл workflow
сам по себе не доказывает успешный remote run: его результат нужно смотреть в Actions.

## Известные ограничения

- RAG/Vector DB/LLM, их ошибки и тесты не реализованы по текущему ограничению scope.
  Дополнительное задание №3 выполнено; MongoDB и RabbitMQ не добавлены.
- Manual calculation endpoint публичный и работает по всем сессиям. Это debug-инструмент:
  перед публичным production-размещением ограничьте доступ на reverse proxy или отключите путь.
- Cookie не имеет подписи, Secure и серверного TTL; при HTTPS нужна дальнейшая настройка
  безопасности. Нет полноценной auth, rate limiting или защиты от кражи session cookie.
- Один worker обрабатывает один batch каждые 300 секунд плюс время расчёта. Это
  ограничивает память/время row locks, но и пропускную способность при большом backlog;
  непрерывное осушение очереди или отдельный scheduler пока не добавлены.
- Смещения OFFSET становятся дорогими при больших страницах. Keyset pagination пока нет.
- `GET /health` — только liveness. Готовность БД/миграций контролируется Compose при старте,
  а не каждым health-запросом. Нет гарантии доступности внешнего API после startup.
- Нет retry, stale fallback и распределённого scheduler. Интервал расчёта — fixed delay,
  а не cron по точным границам минут.
- Формат 422 сохраняет штатные детали FastAPI, остальные ошибки — строку `detail`;
  общего каталога error codes и интеграций с мониторингом пока нет.

Это состояние готово к отдельному критическому review parcel-части, но не означает
завершение всего TASK.md или готовность публичного сервиса без перечисленных ограничений.
