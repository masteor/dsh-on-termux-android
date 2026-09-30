#!/usr/bin/env python3
"""Android-патч dsh: убрать жёсткую зависимость от node-addon-require-builtin.

Проблема (dsh >= 0.1.6-alpha.2, включая 0.2.0-rc.2): апстрим завёл
платформо-зависимую нативную зависимость `node-addon-require-builtin` в boot-путь
ВСЕХ платформ. Пакет `node-addon-require-builtin-android-arm64` не публикуется
никогда, поэтому старт падает:

    dsh: host preparation failed: No usable native binding found for
         node-addon-require-builtin-android-arm64 (auto)

Аддон нужен лишь как fallback для доступа к internal-модулям Node, когда процесс
запущен БЕЗ --expose-internals. dsh на Termux запускается С флагом, поэтому те же
модули доступны через штатный require.

Патчатся три файла:
  * dsh-app-boot/lib/index.js
  * dsh-app-boot/lib/worker/profile-resolution-bootstrap.js
  * cordis-plugin-loader/lib/index.js

Идемпотентен.

Использование:
    python3 patch-addon.py "$(npm root -g)/@deepseek-ai/dsh"
"""
import os
import sys

OLD_INTERNAL = '''function internalModules() {
\tconst addon = createRequire(import.meta.url)("node-addon-require-builtin");
\tconst esmModule = addon.requireBuiltin("internal/modules/esm/loader");
\tconst cjsModule = addon.requireBuiltin("internal/modules/cjs/loader");
\tconst cjsHelpers = addon.requireBuiltin("internal/modules/helpers");
\tconst esmUtils = addon.requireBuiltin("internal/modules/esm/utils");
\tconst esmResolve = addon.requireBuiltin("internal/modules/esm/resolve");'''

NEW_INTERNAL = '''function internalModules() {
\t// ANDROID PATCH: node-addon-require-builtin ships no android-arm64 build.
\t// This process runs with --expose-internals, so Node's own require can load
\t// the very same internal modules. Prefer the addon when it is available.
\tlet _rb;
\ttry {
\t\t_rb = createRequire(import.meta.url)("node-addon-require-builtin").requireBuiltin;
\t} catch {
\t\t_rb = (id) => createRequire(import.meta.url)(id);
\t}
\tconst esmModule = _rb("internal/modules/esm/loader");
\tconst cjsModule = _rb("internal/modules/cjs/loader");
\tconst cjsHelpers = _rb("internal/modules/helpers");
\tconst esmUtils = _rb("internal/modules/esm/utils");
\tconst esmResolve = _rb("internal/modules/esm/resolve");'''

OLD_LOADER = '''\t\ttry {
\t\t\treturn require("node-addon-require-builtin").requireBuiltin(id);
\t\t} catch {}'''

NEW_LOADER = '''\t\ttry {
\t\t\t// ANDROID PATCH: direct require first (no android build of the addon).
\t\t\treturn require(id);
\t\t} catch {}
\t\ttry {
\t\t\treturn require("node-addon-require-builtin").requireBuiltin(id);
\t\t} catch {}'''


def patch_internal(root: str) -> int:
    files = [
        root + "/node_modules/@deepseek-ai/dsh-app-boot/lib/index.js",
        root
        + "/node_modules/@deepseek-ai/dsh-app-boot/lib/worker/profile-resolution-bootstrap.js",
    ]
    rc = 0
    for path in files:
        name = os.path.basename(path)
        if not os.path.isfile(path):
            print(name, "-> нет файла:", path)
            continue
        src = open(path, encoding="utf-8", errors="surrogateescape").read()
        if "ANDROID PATCH: node-addon-require-builtin" in src:
            print(name, "-> уже пропатчен")
            continue
        n = src.count(OLD_INTERNAL)
        if n != 1:
            print(name, "-> ЯКОРЬ НЕ НАЙДЕН, вхождений:", n)
            rc = 1
            continue
        open(path, "w", encoding="utf-8", errors="surrogateescape").write(
            src.replace(OLD_INTERNAL, NEW_INTERNAL, 1)
        )
        print(name, "-> патч применён")
    return rc


def patch_loader(root: str) -> int:
    path = root + "/node_modules/@deepseek-ai/cordis-plugin-loader/lib/index.js"
    if not os.path.isfile(path):
        print("cordis-plugin-loader -> нет файла:", path)
        return 0
    src = open(path, encoding="utf-8", errors="surrogateescape").read()
    if "ANDROID PATCH: direct require" in src:
        print("cordis-plugin-loader -> уже пропатчен")
        return 0
    if src.count(OLD_LOADER) != 1:
        print("cordis-plugin-loader -> якорь не найден, вхождений:", src.count(OLD_LOADER))
        return 1
    open(path, "w", encoding="utf-8", errors="surrogateescape").write(
        src.replace(OLD_LOADER, NEW_LOADER, 1)
    )
    print("cordis-plugin-loader -> патч применён")
    return 0


def main() -> int:
    if len(sys.argv) < 2:
        print("укажите путь к @deepseek-ai/dsh")
        return 1
    root = sys.argv[1]
    rc = patch_internal(root)
    rc |= patch_loader(root)

    print()
    print("напоминание: запускать dsh с явным флагом —")
    print('  node --expose-internals "$(npm root -g)/@deepseek-ai/dsh/lib/bin.js" web')
    print("проверка, что путь рабочий:")
    print("  node --expose-internals -e 'const{createRequire}=require(\"node:module\");"
          "const r=createRequire(process.cwd()+\"/x.js\");"
          "r(\"internal/modules/esm/loader\");console.log(\"OK\")'")
    return rc


if __name__ == "__main__":
    sys.exit(main())
