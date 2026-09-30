#!/data/data/com.termux/files/usr/bin/sh
# Вставить DNS-обход в ~/bin/dsh-web (идемпотентно).
#
# ЗАЧЕМ: системный резолвер bionic на устройстве сломан — dns.lookup() отдаёт
# ENOTFOUND примерно через 24 секунды, тогда как dns.resolve4() (c-ares) работает.
# Из-за этого dsh не может подключиться к провайдеру моделей, хотя ключ валиден
# и API доступен. dsh штатно читает HTTPS_PROXY и ставит undici ProxyAgent,
# поэтому достаточно направить исходящие запросы через локальный прокси на c-ares.
#
# Использование (на телефоне):
#     sh fix-dshweb-proxy.sh
#
# ВНИМАНИЕ: не вставляйте этот блок инлайн через `python3 -c` внутри SSH-команды —
# вложенные кавычки и `$` съедаются, и переменные становятся пустыми.
# Именно поэтому это отдельный файл.

F="$HOME/bin/dsh-web"
PROXY_JS="$HOME/dnsfix/proxy.mjs"

if [ ! -f "$F" ]; then
    echo "нет файла: $F" >&2
    exit 1
fi
if [ ! -f "$PROXY_JS" ]; then
    echo "нет прокси: $PROXY_JS (скопируйте assets/proxy.mjs)" >&2
    exit 1
fi

cp -a "$F" "$F.bak-proxy-$(date +%Y%m%d-%H%M%S)"

python3 - "$F" << 'PYEOF'
import sys

path = sys.argv[1]
src = open(path, encoding="utf-8", errors="surrogateescape").read()

BLOCK = """    # DNS-обход: системный резолвер bionic сломан (dns.lookup -> ENOTFOUND
    # через ~24 c, тогда как c-ares работает). Поднимаем локальный прокси на
    # c-ares и направляем через него запросы к API моделей: dsh штатно читает
    # HTTPS_PROXY и ставит undici ProxyAgent.
    #
    # Проверяем живость прокси по ЛЮБОМУ внешнему хосту — он нужен лишь как
    # индикатор, что резолвинг через прокси работает. Замените на хост своего
    # провайдера, если хотите проверять именно его доступность.
    DNSFIX_PORT="${DNSFIX_PORT:-8899}"
    DNSFIX_PROBE="${DNSFIX_PROBE:-https://example.com/}"
    if ! curl -sS -x "http://127.0.0.1:$DNSFIX_PORT" -o /dev/null -m 3 \\
         "$DNSFIX_PROBE" 2>/dev/null; then
        setsid nohup "$NODE" "$HOME/dnsfix/proxy.mjs" \\
            >"$HOME/dnsfix/proxy.log" 2>&1 </dev/null &
        sleep 3
    fi
    export HTTPS_PROXY="http://127.0.0.1:$DNSFIX_PORT"
    export HTTP_PROXY="http://127.0.0.1:$DNSFIX_PORT"
    export NO_PROXY="127.0.0.1,localhost,::1,[::1]"
    export no_proxy="127.0.0.1,localhost,::1,[::1]"

"""

ANCHOR = "    if command -v setsid >/dev/null 2>&1; then"

# Убрать ранее вставленный блок (в том числе сломанный), чтобы не дублировать.
if "DNS-обход" in src:
    start = src.index("    # DNS-обход")
    end = src.index(ANCHOR, start)
    src = src[:start] + src[end:]
    print("прежний блок удалён")

if src.count(ANCHOR) != 1:
    print("ЯКОРЬ НЕ НАЙДЕН, вхождений:", src.count(ANCHOR))
    sys.exit(1)

src = src.replace(ANCHOR, BLOCK + ANCHOR, 1)
open(path, "w", encoding="utf-8", errors="surrogateescape").write(src)
print("блок вставлен")
PYEOF

echo "--- проверка синтаксиса ---"
sh -n "$F" && echo "dsh-web: OK"
echo "--- вставленный блок ---"
sed -n "/DNS-обход/,/no_proxy/p" "$F"
echo
echo "дальше: dsh-web stop-all && dsh-web start"
