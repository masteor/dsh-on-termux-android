# dsh на Android/Termux

Как развернуть и обновить [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness)
(`@deepseek-ai/dsh`) на Android-смартфоне в [Termux](https://termux.dev/), когда
официальный npm-пакет не встаёт из-за отсутствия `android-arm64` сборок нативных
модулей.

Инструкция собрана по реальной отладке: обновление `0.1.5-rc.1` → `0.2.0-rc.2`,
шесть последовательных падений и рабочий экземпляр на порту 3080 в итоге.

**Проверенное окружение:**

| Параметр | Значение |
|---|---|
| Устройство | arm64, Android 13 (API 33) |
| Termux | F-Droid |
| Node | v26.4.0 |
| npm | 11.19.1 |
| dsh | 0.1.5-rc.1 → **0.2.0-rc.2** |

> **Главная мысль.** `@deepseek-ai/dsh` — чистый JS. «Собрать под телефон» не нужно.
> Проблема всегда в трёх нативных модулях (**koffi**, **node-pty**, **sharp**) и в
> платформо-зависимых ветках кода. Собрав их один раз, версию dsh меняешь обычным
> `npm i -g` — JS перезаписывается, нативные сборки переиспользуются.

## Содержание

- [Когда использовать](#когда-использовать)
- [Источники](#источники-что-читать-если-что-то-не-сходится)
- [Порядок работы](#порядок-работы) — 12 шагов с командами
- [Сводка граблей](#грабли-сводка) — таблица «симптом → причина → фикс»
- [Что ломается при обновлении](#что-ломается-при-обновлении)
- [Известные ограничения](#известные-ограничения)
- [Артефакты](#артефакты) — готовые скрипты в `assets/`

## Когда использовать

- Ставишь dsh на телефон впервые.
- Поднимаешь версию (`0.1.5-rc.1` → `0.2.0-rc.2` и далее).
- Установка падает: `ETARGET`, `statx`, `spawn.h`, `pty.node`, `sharp`,
  `node-addon-require-builtin-android-arm64`.
- После `npm update -g` dsh перестал стартовать.

## Источники (что читать, если что-то не сходится)

Проверенные community-проекты. **Ни один не собирает под 0.2.0-rc.2** — все отстают,
но описания грабель актуальны:

| Источник | Целевая версия | Чем полезен |
|---|---|---|
| [mermergi/deepseek-harness-termux](https://github.com/mermergi/deepseek-harness-termux) | 0.1.6-alpha.2 | **17 патчей с root cause по каждому.** Лучшая диагностика. Именно он описал boot-blocker №10 |
| [Vengisk/deepseek-harness-termux](https://github.com/Vengisk/deepseek-harness-termux) | 0.1.0-rc.6 | Prebuilt `node-pty`/`koffi` (Plan B), 66★ |
| [ErEbusE/dsh-termux](https://github.com/ErEbusE/dsh-termux) | 0.1.5-alpha.1 | Другой подход: официальный glibc-Node под `glibc-runner`. Есть `dsh update -t next` |
| [gist fldlqu](https://gist.github.com/fldlqu/62417d335be4ff3a8bdf5c44f879ddf8) | 0.1.0-rc.6 | Пошаговый разбор 9 проблем с диффами |
| [npm @deepseek-ai/dsh](https://www.npmjs.com/package/@deepseek-ai/dsh) | — | Проверка реальных версий и `dist-tags` |

**Дисциплина:** сначала спроси npm, что реально есть (`npm view @deepseek-ai/dsh versions`),
и только потом верь README любого форка. Форки мертвы относительно апстрима.

## Порядок работы

### 0. Точка отката (не пропускать)

```bash
D="$(npm root -g)/@deepseek-ai/dsh"
cp -a "$D" "$HOME/dsh-backup-$(node -e "console.log(require('$D/package.json').version)")"
```

Плюс сохрани `~/.dsh/` (настройки, сессии, ключи) — он **вне** пакета и `npm` его не трогает.

### 1. Проверить сеть и DNS до npm (грабля №1)

**Симптом:** `npm i -g @deepseek-ai/dsh@X` падает с `ETARGET: No matching version found`,
хотя версия в реестре есть.

**Причина:** на телефоне сломан системный резолвер. Проверка:

```bash
node -e 'const d=require("dns");d.lookup("registry.npmjs.org",(e,a)=>console.log("lookup:",e?e.code:a));d.resolve4("registry.npmjs.org",(e,a)=>console.log("resolve4:",e?e.code:a[0]))'
```

| Путь | Что означает |
|---|---|
| `resolve4` OK, `lookup` `ENOTFOUND` (виснет ~24 с) | **сломан bionic `getaddrinfo`** |
| ping/curl по IP работает | сеть в порядке, дело только в DNS |

`resolv.conf` при этом может быть корректным (8.8.8.8). Bionic читает
`/system/etc/hosts`, а не Termux-овский — **запись в `$PREFIX/etc/hosts` НЕ помогает**.

**Обход** — локальный прокси, который резолвит рабочим c-ares и коннектит по IP.
Готовый файл: `~/dnsfix/proxy.mjs` (см. раздел «Артефакты»). Запуск:

```bash
setsid node ~/dnsfix/proxy.mjs > ~/dnsfix/proxy.log 2>&1 < /dev/null &
sleep 3
export npm_config_proxy=http://127.0.0.1:8899
export npm_config_https_proxy=http://127.0.0.1:8899
curl -sS -x http://127.0.0.1:8899 -o /dev/null -w "%{http_code}\n" https://registry.npmjs.org/   # ждём 200
```

> `nohup ... &` в неинтерактивной SSH-сессии **не выживает**. Нужен `setsid`.

> **Тот же сломанный DNS ломает и работу с моделями** — см. граблю №8. Симптом
> другой («не может подключиться к провайдеру»), а корень тот же.

### 2. Установка с `--ignore-scripts`

```bash
npm i -g --ignore-scripts @deepseek-ai/dsh@0.2.0-rc.2
```

`--ignore-scripts` обязателен: иначе npm попытается собрать `koffi` и упадёт
(грабля №2), откатив всю транзакцию. Нативные модули ставим отдельно и осознанно.

### 3. `spawn.h` (грабля №2)

**Симптом:** сборка `koffi` падает на
`fatal error: 'spawn.h' file not found`.

**Причина:** Termux-пакет `libandroid-spawn` — это **только симлинк на libc**
(`$PREFIX/lib/libandroid-spawn.so`), **заголовка в нём нет**. Bionic поддерживает
`posix_spawn` с API 28 (здесь API 33), но `spawn.h` не поставляет.

**Фикс** — создать шим (файл в «Артефактах»):

```bash
cat > $PREFIX/include/spawn.h << 'EOF'
/* Minimal spawn.h shim for Termux/bionic (API >= 28 has posix_spawn in libc) */
#ifndef _SPAWN_H_SHIM
#define _SPAWN_H_SHIM
#include <sys/types.h>
#include <signal.h>
#ifdef __cplusplus
extern "C" {
#endif
typedef struct { void *__data[16]; } posix_spawn_file_actions_t;
typedef struct { void *__data[16]; } posix_spawnattr_t;
int posix_spawn(pid_t *, const char *, const posix_spawn_file_actions_t *,
                const posix_spawnattr_t *, char *const[], char *const[]);
int posix_spawn_file_actions_init(posix_spawn_file_actions_t *);
int posix_spawn_file_actions_destroy(posix_spawn_file_actions_t *);
int posix_spawn_file_actions_adddup2(posix_spawn_file_actions_t *, int, int);
int posix_spawn_file_actions_addclose(posix_spawn_file_actions_t *, int);
int posix_spawn_file_actions_addopen(posix_spawn_file_actions_t *, int, const char *, int, mode_t);
int posix_spawnattr_init(posix_spawnattr_t *);
int posix_spawnattr_destroy(posix_spawnattr_t *);
int posix_spawnattr_setflags(posix_spawnattr_t *, short);
int posix_spawnp(pid_t *, const char *, const posix_spawn_file_actions_t *,
                 const posix_spawnattr_t *, char *const[], char *const[]);
#ifdef __cplusplus
}
#endif
#endif
EOF
```

Проверка (в Termux **нет `/tmp`** — пиши в `$HOME`):

```bash
printf '#include <spawn.h>\nint main(){posix_spawn_file_actions_t f;posix_spawn_file_actions_init(&f);posix_spawn_file_actions_destroy(&f);return 0;}\n' > ~/t.c
clang ~/t.c -o ~/t && ~/t && echo OK
```

> `spawn.h` может исчезнуть при обновлении Termux-пакетов. Если сборка снова
> ругается — пересоздай.

### 4. koffi: патч `statx` и сборка (грабля №3)

**Симптом:** `base.cc: cannot initialize a member subobject of type '__u32' with an
lvalue of type 'const char *'`.

**Причина:** `StatAt()` вызывает `statx(2)` под `#if defined(__linux__)`. В bionic
`statx` — **имя типа структуры**, а не функция. У koffi есть рабочий fallback на
`fstatat`, надо лишь не входить в эту ветку.

**Важно:** версия koffi зависит от версии dsh!

| dsh | koffi | node-pty |
|---|---|---|
| 0.1.5-rc.1 | 3.2.1 | 1.1.0 |
| **0.2.0-rc.2** | **3.1.1** | **1.2.0-beta.15** |

У 3.2.1 в апстриме уже стоит `#if defined(__linux__) && defined(STATX_TYPE)` (патч не
нужен), у 3.1.1 — голый `#if defined(__linux__)` (патч нужен).

**Патч** в `$D/node_modules/koffi/lib/native/base/base.cc`:

```diff
 static StatResult StatAt(int fd, bool fd_is_directory, const char *filename, unsigned int flags, FileInfo *out_info)
 {
-#if defined(__linux__)
+// statx(2) unavailable on Android/bionic; use the fstatat fallback.
+#if defined(__linux__) && !defined(__ANDROID__)
     const char *pathname = filename;
```

Универсальный вариант (работает для обеих версий) — скрипт `patch-koffi.py` из «Артефактов».

**Сборка:**

```bash
cd "$D/node_modules/koffi"
node ./cnoke.cjs -P . -D src/koffi --prebuild --release
# ждём: [100%] Linking CXX shared library Output/koffi.node
```

> ABI-путь включает версию Node: `build/koffi/android_arm64/v26.4.0_native/...`.
> После смены мажорной версии Node пересобирай.

### 5. node-pty (грабля №4)

**Симптом:** `Failed to load native module: pty.node`.

**Причина:** у `node-pty` нет android-arm64 prebuild (только darwin/win32/linux).

```bash
NG="$(npm root -g)/npm/node_modules/node-gyp/bin/node-gyp.js"
cd "$D/node_modules/node-pty" && node "$NG" rebuild     # ждём: gyp info ok
node -e 'console.log(typeof require("node-pty").spawn)'  # function
```

Нужны `pkg install python clang make` (обычно уже стоят).

### 6. sharp (грабля №5)

**Симптом:** старт падает с `Could not load the "sharp" module` — **до** подъёма сервера.

**Причина:** у sharp нет android-arm64 prebuild, но есть встроенный WASM-fallback.

```bash
SV=$(node -e "console.log(require('$D/node_modules/sharp/package.json').version)")
cd "$D" && npm install --no-save @img/sharp-wasm32@$SV    # версия строго в версию!
```

### 7. Boot-blocker `node-addon-require-builtin` (грабля №6, главная)

**Симптом:**

```
dsh: host preparation failed: No usable native binding found for
     node-addon-require-builtin-android-arm64 (auto)
```

**Причина:** в 0.2.0-rc.2 апстрим завёл платформо-зависимую нативную зависимость в
boot-путь **всех** платформ — для пакета, у которого `android-arm64` сборки **не
существует никогда**. Это архитектурная проблема, а не «забыли собрать».

Аддон нужен лишь как fallback для доступа к internal-модулям Node, когда процесс
запущен **без** `--expose-internals`. У нас флаг есть — значит, можно использовать
штатный `require`.

**Фикс** — `patch-addon.py` из «Артефактов», правит три файла:

- `dsh-app-boot/lib/index.js`
- `dsh-app-boot/lib/worker/profile-resolution-bootstrap.js`
- `cordis-plugin-loader/lib/index.js`

Суть: `addon.requireBuiltin(id)` → штатный `require(id)`, с сохранением аддона как
предпочтительного пути, если он всё-таки есть:

```js
let _rb;
try {
    _rb = createRequire(import.meta.url)("node-addon-require-builtin").requireBuiltin;
} catch {
    _rb = (id) => createRequire(import.meta.url)(id);
}
```

**Проверка, что путь рабочий** (до патча):

```bash
node --expose-internals -e 'const{createRequire}=require("node:module");const r=createRequire(process.cwd()+"/x.js");r("internal/modules/esm/loader");console.log("OK")'
```

> **Критично:** флаг `--expose-internals` должен быть в `process.execArgv`, иначе
> `createRequire` не увидит `internal/...`. Поэтому dsh запускают **явно**
> `node --expose-internals .../bin.js`, а не через shebang.

### 8. flock: сессии не пишутся (грабля №7)

**Симптом в UI:** каждый ход падает с

```
This turn failed: flock is not supported on android-arm64
```

Сервер при этом **стартует нормально** и UI открывается — падает только сам ход.

**Причина:** `@deepseek-ai/node-addon-system/lib/flock.js` жёстко проверяет
`platform !== 'linux' && platform !== 'darwin'` и бросает
`ERR_FLOCK_UNSUPPORTED_PLATFORM`. Termux отдаёт `platform === 'android'`, а сборки
`node-addon-system-android-arm64` не существует. Ветка glibc/musl тоже не подходит —
Termux на bionic, и `glibcVersionRuntime` в отчёте Node отсутствует.

flock нужен `dsh-session-persistence-jsonl` для эксклюзивной блокировки журнала сессии.

**Фикс:** вызывать `flock(2)` прямо из libc через **koffi**, который на Android уже
собран (он и так зависимость dsh). Семантика идентична нативной обёртке.
Скрипт — `assets/patch-flock.py`.

Проверка семантики перед применением (должно дать OK / EAGAIN(11) / OK):

```bash
node -e '
const koffi=require("'"$D"'/node_modules/koffi"), fs=require("fs");
const libc=koffi.load("libc.so"), flock=libc.func("int flock(int fd, int op)");
const p=process.env.HOME+"/locktest"; fs.writeFileSync(p,"x");
const a=fs.openSync(p,"r+"), b=fs.openSync(p,"r+");
console.log("a:", flock(a,2|4)===0?"OK":"нет");          // LOCK_EX|LOCK_NB
console.log("b:", flock(b,2|4)!==0?"EAGAIN "+koffi.errno():"ОШИБКА");
flock(a,8); console.log("b после UNLOCK:", flock(b,2|4)===0?"OK":"ОШИБКА");
fs.closeSync(a); fs.closeSync(b); fs.unlinkSync(p);'
```

**Патч читается при импорте модуля — обязателен перезапуск dsh.**

### 8a. Запись сессии падает с EACCES на link (грабля №8, вылезает сразу после flock)

**Симптом в UI:**

```
This turn failed: EACCES: permission denied,
  link '.../session.v4.jsonl.zstd.XXXX.tmp' -> '.../session.v4.jsonl.zstd'
```

Сервер работает, предыдущие грабли закрыты — а ход всё равно валится.

**Причина:** Android SELinux запрещает untrusted-приложениям вызывать `link(2)`
(termux-app issue #837). Проверяется на устройстве за секунду:

```bash
ln a b          # ln: failed to create hard link: Permission denied
mv a c          # OK
node -e 'const fs=require("fs");fs.writeFileSync("a","x");try{fs.linkSync("a","b")}catch(e){console.log("link:",e.code)};try{fs.renameSync("a","c");console.log("rename: OK")}catch(e){console.log(e.code)}'
# link: EACCES ; rename: OK
```

dsh использует `link(tmp -> final)` для «атомарной публикации без перезаписи».
Таких мест **пять в трёх пакетах** — они проявляются по очереди, по мере
прохождения хода:

| Пакет | Место | Что ломается |
|---|---|---|
| `dsh-session-persistence-jsonl` | `materializePosix` | запись журнала сессии |
| `dsh-session-persistence-jsonl` | `publishCurrentExclusive` | публикация current-поколения |
| `dsh-attachment-local` | `publishImmutableAlias` | вложения |
| `dsh-attachment-local` | `publishStagedObject` | вложения |
| `dsh-fs-local` | `writeFileAtomic` (createIfAbsent) | **инструмент write** |

**Фикс:** `assets/patch-link.py` — заменяет `link` на `rename` при `EACCES`/`EPERM`,
перепроверяя существование цели, чтобы сохранить «не перезаписывать».

```bash
python3 patch-link.py "$(npm root -g)/@deepseek-ai/dsh"
```

> **Обязательно проверяй синтаксис после патча** — этот фикс добавляет вложенные
> `try`/`catch` и легко получить незакрытую скобку:
>
> ```bash
> for p in dsh-session-persistence-jsonl dsh-attachment-local dsh-fs-local; do
>   node --check "$D/node_modules/@deepseek-ai/$p/lib/index.js" && echo "$p OK"
> done
> ```
>
> Именно так и вышло при первом применении: `attachment-local` сломался на
> незакрытом `else {`, диагностировался `node --check` и правился вручную.

> **Не берите чистую копию из бэкапа** для отката этого патча: версии пакетов
> между релизами dsh различаются (`dsh-attachment-local` 0.1.5-rc.2 против
> 0.2.0-rc.2), файл не подойдёт.

### 8b. Не подключается к провайдеру моделей (грабля №9)

**Симптом в UI:** «не может подключиться к провайдеру»; отправляешь `hi` — запрос
к модели не уходит. Сервер при этом работает, UI открывается.

**Причина — та же, что у npm (грабля №1): сломанный bionic-резолвер.** Но симптом
выглядит иначе, поэтому связь не очевидна. Подставьте хост своего провайдера
моделей и проверьте:

```bash
export PROVIDER_HOST=api.example.com   # ← хост вашего провайдера
node -e 'const h=process.env.PROVIDER_HOST,d=require("dns");d.lookup(h,(e,a)=>console.log("lookup:",e?e.code:a));d.resolve4(h,(e,a)=>console.log("resolve4:",e?e.code:a[0]))'
# lookup: ENOTFOUND (висит ~24 c)   resolve4: <IP>   ← диагноз подтверждён
```

При этом ключ валиден и API живой — проверяется в обход DNS:

```bash
IP=$(node -e 'const h=process.env.PROVIDER_HOST;require("dns").resolve4(h,(e,a)=>{console.log(a[0]);process.exit(0)})')
curl -sS --resolve "$PROVIDER_HOST:443:$IP" -o /dev/null -w "%{http_code}\n" \
     "https://$PROVIDER_HOST/api/v1/models"
# 200 — значит дело НЕ в авторизации, а именно в резолвинге
```

**Фикс:** dsh штатно читает `HTTPS_PROXY` и сам ставит undici `ProxyAgent`
(пакет `dsh-http-proxy`, вызов `installProxyFromEnvironment` в `profile-boot`).
Достаточно экспортировать переменные **перед запуском** dsh:

```bash
export HTTPS_PROXY=http://127.0.0.1:8899
export HTTP_PROXY=http://127.0.0.1:8899
export NO_PROXY=127.0.0.1,localhost,::1,[::1]
```

`NODE_USE_ENV_PROXY` здесь **не нужен** — в отличие от npm, dsh не полагается на
встроенный `EnvHttpProxyAgent`, а ставит `ProxyAgent` явно на `globalDispatcher`.
Проверка, что переменные доехали до процесса:

```bash
tr '\0' '\n' < /proc/$(dsh-web status | grep -o 'pid=[0-9]*' | cut -d= -f2)/environ | grep HTTPS_PROXY
```

**Постоянное решение** — вписать блок в `~/bin/dsh-web` перед строкой запуска,
чтобы прокси поднимался и экспортировался автоматически. Готовый скрипт вставки:
`assets/fix-dshweb-proxy.sh` (идемпотентный, сам чистит прежнюю версию блока).

> **Грабля при патче:** правка `dsh-web` через `python3 -c` с `<<` внутри SSH-команды
> съедает `$` и `\\` — переменные превращаются в пустые строки (`DNSFIX_PORT="\8899"`).
> Вставляй блок **отдельным файлом-скриптом**, а не инлайн-командой.

### 9. Проверка и запуск

**Shebang** (полезно, но полагаться только на него нельзя):

```bash
sed -i "1s|.*|#!$PREFIX/bin/node --expose-internals|" "$D/lib/bin.js"
```

**Смоук-тест на другом порту** — живой экземпляр не трогаем:

```bash
node --expose-internals "$D/lib/bin.js" web --no-open --port 3599
# ждём: dsh web: http://127.0.0.1:3599/?token=...
```

Проверка полного цикла (простой `curl` даст **401** — это норма, нужен токен):

```bash
TOK=$(grep -o 'token=[A-Za-z0-9_-]*' log | head -1 | cut -d= -f2)
curl -sS -c c.txt -L -o page.html -w "%{http_code} %{size_download}\n" "http://127.0.0.1:3599/?token=$TOK"
grep -o '<title>[^<]*</title>' page.html   # DeepSeek Harness
grep -c __DSH_BOOT__ page.html             # 1
```

Ожидаем: `200`, ~35 КБ, `__DSH_BOOT__` присутствует, выдана cookie `dsh-auth-*`.

### 10. Перевод на рабочий порт

**На этом устройстве есть свой менеджер** `~/bin/dsh-web` (команды
`start|stop|stop-all|restart|status|url|log|proxy|autostart on|off`). Он сам запускает
с `--expose-internals` и сам берёт `BIN_JS` из `$PREFIX/lib/node_modules/...` — то есть
**новый пакет подхватывается без правки скриптов**.

```bash
dsh-web stop-all        # ВНИМАНИЕ: останавливает ещё и sshd
dsh-web start           # ждём: готово (HTTP 303)
```

> **Грабля:** `dsh-web restart` отрабатывает ненадёжно — пишет «остановлен», но старый
> процесс остаётся жив («уже работает pid=...»). Используй `stop-all` + `start`.

> `stop-all` гасит **sshd**. `dsh-web start` поднимает его обратно — проверяй
> `dsh-web status`.

## Грабли-сводка

| № | Симптом | Причина | Фикс |
|---|---|---|---|
| 1 | `ETARGET` | сломан bionic `getaddrinfo` (`lookup` ENOTFOUND, `resolve4` OK) | прокси на c-ares, `npm_config_proxy` |
| 2 | `spawn.h not found` | `libandroid-spawn` = только `.so`, без заголовка | создать `$PREFIX/include/spawn.h` |
| 3 | `statx` / `__u32` | bionic: `statx` — тип, не функция | `&& !defined(__ANDROID__)` в koffi |
| 4 | `pty.node` | нет android-arm64 prebuild | `node-gyp rebuild` |
| 5 | `sharp` module | нет android-arm64 prebuild | `@img/sharp-wasm32@<версия sharp>` |
| 6 | `node-addon-require-builtin-android-arm64` | аддон без android-сборки в boot-пути | `patch-addon.py` → нативный `require` |
| 7 | `This turn failed: flock is not supported on android-arm64` (сервер стартует, падает **ход**) | `flock.js` пускает только linux/darwin | `patch-flock.py` → `flock` через libc/koffi |
| 8 | `This turn failed: EACCES ... link '…tmp' -> '…zstd'` (вылезает сразу после №7) | SELinux запрещает `link(2)`; 5 мест в 3 пакетах | `patch-link.py` → `rename` при EACCES |
| 9 | «не может подключиться к провайдеру», `hi` не уходит (сервер жив) | **тот же сломанный bionic-DNS**, что и в №1 | `HTTPS_PROXY=127.0.0.1:8899` + `fix-dshweb-proxy.sh` |
| 10 | `dsh restart` не помогает | старый процесс не убивается | `stop-all` + `start` |
| 11 | `nohup ... &` умирает | неинтерактивная SSH-сессия | `setsid ... < /dev/null &` |
| 12 | `/tmp` не существует | Termux | писать в `$HOME` |

## Что ломается при обновлении

- **`npm update -g` стирает ВСЕ патчи в `node_modules`** (koffi, addon, loader, flock, link).
  Переприменяй по порядку: `patch-koffi.py` → `patch-addon.py` → `patch-flock.py` → `patch-link.py`.
  После каждого — `node --check` на тронутых файлах.
- **Прокси для моделей** живёт в `~/bin/dsh-web` (не в `node_modules`) — при обновлении
  самого `dsh-web` переприменяй `fix-dshweb-proxy.sh`.
- **`spawn.h`** может исчезнуть при `pkg upgrade`. Если сборка ругается — пересоздай.
- **ABI koffi** привязан к версии Node (`v26.4.0_native`). Сменился мажор — пересобирай.
- **`--expose-internals`** помечен экспериментальным. Проверяй после апгрейда Node.
- Версии нативных зависимостей **меняются между релизами dsh** — сверяйся с
  `npm view @deepseek-ai/dsh-subprocess-local@<версия> dependencies`.

## Известные ограничения

- **Sandbox недоступен.** На Android нет ни `bubblewrap`, ни Landlock. Режим
  `workspace-write` не стартует вовсе — выбирай `danger-full-access` (файловые
  инструменты защищены in-process политикой, а bash — нет).
- **Плагины отваливаются.** При смене версии peer-зависимости не сходятся, и плагин
  скипается с предупреждением (здесь: `dsh-voice@0.8.28` на 0.2.0-rc.2). Лечится
  обновлением плагина или `dsh plugin allow-version <плагин>@<версия>`.
- **HMR/`patchReload: live`** в профиле требует `--expose-internals`. Для Android
  надёжнее `startup` (патч 4 у mermergi).
- **Форки отстают.** Готовой сборки под новейшую версию обычно нет и не будет —
  обновляйся через `npm`, пересобирая только нативные модули.

## Артефакты

Готовые скрипты лежат рядом со скиллом, в `assets/`. Скопируй их на телефон
(например, в `~/dnsfix/`) и запускай оттуда:

| Файл | Назначение |
|---|---|
| `assets/proxy.mjs` | DNS-обход: резолв через c-ares + HTTP CONNECT-прокси на `127.0.0.1:8899` |
| `assets/patch-addon.py` | Патч `node-addon-require-builtin` (3 файла, идемпотентный) |
| `assets/patch-flock.py` | Патч `flock` для Android через libc/koffi (идемпотентный) |
| `assets/patch-link.py` | Патч `link(2)` → `rename(2)` в 3 пакетах (сессии, вложения, write) |
| `assets/fix-dshweb-proxy.sh` | Вставка DNS-обхода в `~/bin/dsh-web` (идемпотентный) |
| `assets/patch-koffi.py` | Патч `statx` в koffi (обе версии, идемпотентный) |
| `assets/spawn.h` | Шим-заголовок → `$PREFIX/include/spawn.h` |

Все проверены на реальном дереве: повторный запуск печатает «уже пропатчен» и
ничего не меняет.

Копирование с хоста на телефон (через adb-проброс SSH):

```bash
SSH="ssh -p 8022 -i ~/.ssh/id_ed25519_phone \
     -o StrictHostKeyChecking=no -o BatchMode=yes $USER@127.0.0.1"
mkdir -p ~/dnsfix 2>/dev/null
for f in assets/*; do
  b=$(basename "$f")
  cat "$f" | $SSH "cat > \$HOME/dnsfix/$b"
done
```

На устройстве уже лежат рабочие копии: `~/dnsfix/proxy.mjs`, `~/dnsfix/patch-addon.py`,
`~/dnsfix/patch-koffi.py`. Резервная копия пакета: `~/dsh-backup-<версия>` (286 МБ).

> **Откат.** Скопировать бэкап обратно. Учти: новая версия могла записать сессии в
> формате, который старая не прочитает.

## Итог проверки

```
dsh web: РАБОТАЕТ  pid=16815  порт=3080
версия:  0.2.0-rc.2
HTTP:    200, 34902 байта, <title>DeepSeek Harness</title>, __DSH_BOOT__ ✓
sshd:    РАБОТАЕТ        прокси: http://127.0.0.1:3081/ (вход без токена)
```
