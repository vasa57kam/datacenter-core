from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

router = APIRouter(tags=["help"])

KB_HTML = """<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>База знаний ITKAM34</title>
<style>
body{font-family:-apple-system,'Segoe UI',Roboto,sans-serif;background:#0d1117;color:#e6edf3;line-height:1.65;margin:0}
main{max-width:960px;margin:0 auto;padding:32px 20px}
h1{font-size:30px}h2{font-size:22px;margin-top:36px;color:#58a6ff;border-bottom:1px solid #30363d;padding-bottom:8px}
h3{font-size:17px;margin-top:24px;color:#3fb950}
table{width:100%;border-collapse:collapse;margin:12px 0}
th,td{border:1px solid #30363d;padding:8px 12px;text-align:left;font-size:14px}
th{background:#161b22;color:#8b949e}
code,pre{background:#161b22;border:1px solid #30363d;border-radius:6px;padding:2px 6px;font-size:13px}
pre{padding:12px;overflow-x:auto}
.warn{background:#3d2e00;border:1px solid #d29922;padding:10px 14px;border-radius:8px}
.ok{background:#0f2d1a;border:1px solid #3fb950;padding:10px 14px;border-radius:8px}
a{color:#58a6ff}
</style></head><body><main>
<h1>📚 База знаний биллинга ITKAM34</h1>
<p>Как создавать тарифы, как считаются деньги, как управлять услугами и нодами.</p>

<h2>1. Деньги и единицы тарификации</h2>
<p>Все цены хранятся в <b>копейках</b> (price_minor). 1.50 ₽ = 150.</p>
<table>
<tr><th>unit</th><th>Значение</th><th>Когда списывается</th><th>Пример цены</th></tr>
<tr><td><code>second</code></td><td>посекундно</td><td>каждую секунду фактического подключения</td><td>2 = 0.02 ₽/сек</td></tr>
<tr><td><code>minute</code></td><td>поминутно</td><td>каждую минуту фактического подключения</td><td>150 = 1.50 ₽/мин</td></tr>
<tr><td><code>gb</code></td><td>по трафику</td><td>за каждый полный ГиБ принят+передан</td><td>100 = 1 ₽/ГиБ</td></tr>
<tr><td><code>mb</code></td><td>по трафику</td><td>за каждый полный МиБ</td><td>10 = 0.10 ₽/МиБ</td></tr>
<tr><td><code>month</code></td><td>помесячно</td><td>разовое списание при активации услуги</td><td>30000 = 300 ₽/мес</td></tr>
<tr><td><code>one_time</code></td><td>разовый</td><td>разовое списание при активации</td><td>любая</td></tr>
</table>
<div class="warn">Время/трафик списываются <b>только пока клиент реально подключён</b> (панель видит его online). Услуга активна, но никто не подключался = 0 ₽. Месяц/разовый списываются сразу при активации.</div>

<h2>2. Рецепт: создать тариф</h2>
<p>Админка → «Продукты и тарифы» → «+ New Продукт»:</p>
<table>
<tr><th>Поле</th><th>Пример: поминутно</th><th>Пример: посекундно</th><th>Пример: по трафику</th><th>Пример: месяц</th></tr>
<tr><td>code</td><td>vpn-vless-minute</td><td>vpn-vless-second</td><td>vpn-vless-gb</td><td>vps-month</td></tr>
<tr><td>name</td><td>VLESS Reality (NL), поминутно</td><td>VLESS Reality (NL), посекундно</td><td>VLESS Reality (NL), за трафик</td><td>VPS Базовый, месяц</td></tr>
<tr><td>service_type</td><td>vpn</td><td>vpn</td><td>vpn</td><td>vps</td></tr>
<tr><td>unit</td><td>minute</td><td>second</td><td>gb</td><td>month</td></tr>
<tr><td>price_minor</td><td>150</td><td>2</td><td>100</td><td>30000</td></tr>
<tr><td>config (JSON)</td><td>{"protocol":"vless"}</td><td>{"protocol":"vless"}</td><td>{"protocol":"vless"}</td><td>{}</td></tr>
</table>
<p>После сохранения продукт сразу появляется в кабинете на странице «Подключить услугу».</p>

<h2>3. Как добавить VPN-ноду</h2>
<p>Админка → «VPN-ноды» → «+ New»:</p>
<ul>
<li><code>code</code> — уникальный код (nl-vless-02);</li>
<li><code>api_kind</code> = 3xui, <code>api_url</code> — адрес панели с базовым путём, <code>api_user/api_key</code>;</li>
<li><code>endpoint_host/endpoint_port</code> — куда подключаются клиенты;</li>
<li><code>extra</code> (JSON): <code>{"inbound_id": 24, "sni": "amd.com", "pbk": "&lt;publicKey&gt;", "sid": "&lt;shortId&gt;", "fp": "chrome", "spider_x": "/"}</code>.</li>
</ul>
<p>inbound_id, publicKey и shortId берутся из входящего подключения панели 3x-ui.</p>

<h2>4. Жизненный цикл услуги</h2>
<table>
<tr><th>Статус</th><th>Что значит</th><th>Деньги</th></tr>
<tr><td>выдаётся</td><td>задача provisioning создаёт аккаунт в панели</td><td>—</td></tr>
<tr><td>активна</td><td>клиент может подключаться</td><td>идут списания (время/трафик) или уже списано (месяц)</td></tr>
<tr><td>приостановлена</td><td>пауза клиентом или автостоп при нехватке баланса</td><td>не списываются</td></tr>
<tr><td>завершена</td><td>удалена</td><td>—</td></tr>
</table>
<p><b>Отказ клиента:</b> кабинет → «Отказаться» — услуга, аккаунт в панели и сессии удаляются сразу. Списанные средства не возвращаются (оплачено только пользование).</p>
<p><b>Удаление админом:</b> «Услуги клиентов» → корзинка — каскадно удаляет аккаунты и сессии.</p>

<h2>5. Заявки на пополнение</h2>
<p>Клиент создаёт заявку → админка → «Заявки на пополнение» → «Одобрить и зачислить» (деньги падают в кошелёк и в ledger) или «Отклонить». Заявки можно удалять корзинкой, чтобы не мусорить. Клиент может удалить свою pending-заявку в кабинете.</p>

<h2>6. Где смотреть деньги</h2>
<ul>
<li>«Финансовый журнал (ledger)» — каждая проводка: приход/списание, сумма, баланс после, назначение (<code>vpn_usage_minute</code>, <code>vpn_traffic_gb</code>, <code>payment_cash</code>, <code>service_activation_month</code>).</li>
<li>«Сессии использования» — минуты/байты и стоимость каждой сессии.</li>
</ul>

<h2>7. Troubleshooting (из практики)</h2>
<table>
<tr><th>Симптом</th><th>Причина / лечение</th></tr>
<tr><td><code>password authentication failed for user "billing"</code></td><td>.env и том Postgres рассинхронизированы. Лечится пересозданием тома (<code>compose down -v</code>) при согласованном .env; в .env обязательны POSTGRES_USER/POSTGRES_DB.</td></tr>
<tr><td><code>role "billing" does not exist</code></td><td>Том инициализирован без POSTGRES_USER. См. выше.</td></tr>
<tr><td>Услуга висит «выдаётся»</td><td>Смотри «Задачи выдачи»: ошибка покажет причину (например 404 от панели = не тот API). Кнопка возврата зависших задач — перезапуск worker.</td></tr>
<tr><td>Админка без стилей / петля логина по HTTPS</td><td>uvicorn должен работать с <code>--proxy-headers</code> за NPM (уже в compose).</td></tr>
<tr><td>Списаний нет при активной услуге</td><td>Никто не подключён = нет сессий = нет списаний (это норма для поминутки/трафика). Проверь «Сессии использования».</td></tr>
</table>

<h2>8. Резервные копии</h2>
<p>cron ежедневно складывает pg_dump в <code>/var/backups</code> (ротация 14 дней). Восстановление: <code>docker compose exec -T db pg_restore -U billing -d billing --clean &lt; /var/backups/…dump</code>.</p>


<h2>9. Быстрый импорт ноды из конфига</h2>
<p>Скопируй JSON входящего подключения из 3x-ui (входящие → изменить → расширенный шаблон / или JSON который ты готовил для создания) и выполни на сервере:</p>
<pre>cat &gt; /tmp/inbound.json &lt;&lt;'JSON'
{сюда вставить JSON inbound}
JSON
source /root/billing-creds.env
TOKEN=$(curl -s -X POST http://127.0.0.1:8008/api/v1/auth/login -H 'Content-Type: application/json' -d "{\"email\":\"$ADMIN_EMAIL\",\"password\":\"$ADMIN_PASSWORD\"}" | sed 's/.*"access_token":"\\([^"]*\\)".*/\\1/')
python3 - &lt;&lt;'PY'
import json, os, urllib.request
payload = {"inbound": json.load(open("/tmp/inbound.json")), "country": "NL", "endpoint_host": "vps.itkam34.ru"}
# если inbound УЖЕ создан в панели и известен id — добавь: payload["inbound_id"] = 25
req = urllib.request.Request("http://127.0.0.1:8008/api/v1/admin/nodes/import",
    data=json.dumps(payload).encode(),
    headers={"Content-Type": "application/json", "Authorization": "Bearer " + os.environ["TOKEN"]},
    method="POST")
print(urllib.request.urlopen(req).read().decode())
PY</pre>
<p>Импорт сам вытащит порт, SNI, publicKey, shortId, fingerprint, spiderX и создаст ноду в биллинге. Если <code>inbound_id</code> не указан — inbound будет создан в панели этим же JSON.</p>

<h2>10. Быстрое создание тарифов</h2>
<p>Одной командой создаётся/обновляется набор: посекундно, поминутно, за ГиБ, помесячно.</p>
<pre>docker compose run --rm api python scripts/quick_tariffs.py --protocol vless --country NL</pre>
<p>Со своими ценами (копейки):</p>
<pre>docker compose run --rm api python scripts/quick_tariffs.py --protocol vless --country NL --prices '{"second":2,"minute":150,"gb":100,"month":30000}'</pre>
<p>Или через API: <code>POST /api/v1/admin/products/quick</code> с телом <code>{"protocol":"vless","country":"NL","prices":{...}}</code>. Продукты сразу появляются в кабинете на странице подключения.</p>


<h2>11. Импорт ноды и тарифы через веб-интерфейс</h2>
<p>Главная админки → кнопки «🚀 Импорт ноды из JSON» и «⚡ Быстрые тарифы» (или <code>/admin-ops/</code>).</p>
<ul>
<li><b>Импорт ноды</b>: вставь JSON inbound из 3x-ui. Если Inbound ID = 0 — inbound создастся в панели этим же JSON; иначе привяжется к указанному id. Код/название/хост опциональны (генерируются).</li>
<li><b>Тарифы</b>: 4 цены в копейках (сек/мин/ГиБ/мес) → создаётся или обновляется набор <code>vpn-&lt;proto&gt;-second|minute|gb|month</code>. Месяц списывается один раз при активации, сек/мин/ГиБ — по факту использования.</li>
</ul>

<p style="margin-top:40px"><a href="/admin">← Вернуться в админку</a> · <a href="/lk/">Кабинет</a></p>
</main></body></html>"""


@router.get("/admin-help", response_class=HTMLResponse)
def admin_help(request: Request):
    if not request.session.get("admin_uid"):
        return RedirectResponse("/admin/login", status_code=303)
    return HTMLResponse(KB_HTML)


@router.get("/admin/help", include_in_schema=False)
def admin_help_alias(request: Request):
    return RedirectResponse("/admin-help", status_code=302)
