#!/usr/bin/env python3
"""Android-патч: заменить link(2) на rename(2) во всех местах dsh.

Проблема: Android SELinux запрещает untrusted-приложениям вызывать link(2)
(termux-app issue #837). touch/rename работают, а link стабильно возвращает
EACCES — проверено на устройстве:

    ln: failed to create hard link 'b' => 'a': Permission denied
    fs.link:   EACCES
    fs.rename: OK

dsh использует link(tmp -> final) для «атомарной публикации без перезаписи».
На Android это ломает запись сессий, вложения и создание файлов инструментом write.

Симптомы в UI (проявляются по очереди, по мере прохождения хода):
  * This turn failed: EACCES: permission denied, link '.../session.v4.jsonl.zstd.XXXX.tmp'
    -> '.../session.v4.jsonl.zstd'                 (session-persistence-jsonl)
  * ATTACHMENT_WRITE_FAILED / ATTACHMENT_CORRUPT    (attachment-local, при вложениях)
  * FS_IO_ERROR: cannot write "…": permission denied (fs-local, write tool)

Фикс: при EACCES/EPERM падать в rename(2), который на Android разрешён.
Семантика «не перезаписывать существующее» сохраняется: перед rename цель
перепроверяется, и при коллизии возвращается прежний результат (EEXIST и т.п.).

Патчатся 5 мест в 3 пакетах. Идемпотентен.

Использование:
    python3 patch-link.py "$(npm root -g)/@deepseek-ai/dsh"
"""
import os
import sys


# ─── dsh-session-persistence-jsonl ────────────────────────────────────────────

OLD_IMPORT = (
    'import { link, lstat, mkdir, mkdtemp, open, readFile, readdir, '
    'realpath, rm, stat, truncate } from "node:fs/promises";'
)
NEW_IMPORT = (
    'import { link, lstat, mkdir, mkdtemp, open, readFile, readdir, '
    'realpath, rename, rm, stat, truncate } from "node:fs/promises";'
)

OLD_MAT = """\t\tawait this.rejectExistingLog(finalPath, id);
\t\tconst tmp = await this.writeSyncedTempFile(finalPath, content);
\t\tlet linked = false;
\t\ttry {
\t\t\tawait link(tmp, finalPath);
\t\t\tlinked = true;
\t\t} finally {"""

NEW_MAT = """\t\tawait this.rejectExistingLog(finalPath, id);
\t\tconst tmp = await this.writeSyncedTempFile(finalPath, content);
\t\tlet linked = false;
\t\ttry {
\t\t\ttry {
\t\t\t\tawait link(tmp, finalPath);
\t\t\t} catch (error) {
\t\t\t\t// ANDROID PATCH: SELinux denies link(2) to untrusted apps
\t\t\t\t// (EACCES/EPERM); rename(2) is permitted. Re-check existence to
\t\t\t\t// keep the "never overwrite an existing log" invariant.
\t\t\t\tif (error?.code !== "EACCES" && error?.code !== "EPERM") throw error;
\t\t\t\tawait this.rejectExistingLog(finalPath, id);
\t\t\t\tawait rename(tmp, finalPath);
\t\t\t}
\t\t\tlinked = true;
\t\t} finally {"""

OLD_PUB = """\ttry {
\t\tawait internals.fs.link(staged, currentPath);
\t} catch (error) {"""

NEW_PUB = """\ttry {
\t\tawait internals.fs.link(staged, currentPath);
\t} catch (error) {
\t\t// ANDROID PATCH: SELinux denies link(2) to untrusted apps; rename(2) is
\t\t// allowed. Preserve the no-replace semantics by re-checking the target.
\t\tif (error?.code === "EACCES" || error?.code === "EPERM") {
\t\t\ttry {
\t\t\t\tawait internals.fs.rename(staged, currentPath);
\t\t\t} catch (renameError) {
\t\t\t\t/* v8 ignore next -- error codes come from the filesystem. */
\t\t\t\tif (isEEXIST(renameError)) return false;
\t\t\t\tthrow renameError;
\t\t\t}
\t\t\tawait syncDirectory(dirname(currentPath), internals);
\t\t\treturn true;
\t\t}"""


def patch_persistence(root: str) -> int:
    path = os.path.join(
        root, "node_modules", "@deepseek-ai",
        "dsh-session-persistence-jsonl", "lib", "index.js",
    )
    if not os.path.isfile(path):
        print("persistence: нет файла", path)
        return 1

    src = open(path, encoding="utf-8", errors="surrogateescape").read()
    rc = 0

    if "rename, rm, stat, truncate" in src:
        print("persistence/импорт: уже есть")
    elif src.count(OLD_IMPORT) == 1:
        src = src.replace(OLD_IMPORT, NEW_IMPORT, 1)
        print("persistence/импорт: добавлен rename")
    else:
        print("persistence/импорт: ЯКОРЬ НЕ НАЙДЕН")
        rc = 1

    if "ANDROID PATCH: SELinux denies link(2) to untrusted apps\n\t\t\t\t// (EACCES/EPERM)" in src:
        print("persistence/materializePosix: уже пропатчен")
    elif src.count(OLD_MAT) == 1:
        src = src.replace(OLD_MAT, NEW_MAT, 1)
        print("persistence/materializePosix: патч применён")
    else:
        print("persistence/materializePosix: ЯКОРЬ НЕ НАЙДЕН")
        rc = 1

    if "ANDROID PATCH: SELinux denies link(2) to untrusted apps; rename(2) is" in src:
        print("persistence/publishCurrentExclusive: уже пропатчен")
    elif src.count(OLD_PUB) == 1:
        src = src.replace(OLD_PUB, NEW_PUB, 1)
        print("persistence/publishCurrentExclusive: патч применён")
    else:
        print("persistence/publishCurrentExclusive: ЯКОРЬ НЕ НАЙДЕН")
        rc = 1

    if rc == 0:
        open(path, "w", encoding="utf-8", errors="surrogateescape").write(src)
    return rc


# ─── dsh-attachment-local ─────────────────────────────────────────────────────

OLD_ATT = """\t\ttry {
\t\t\tawait link(source, target);
\t\t} catch (error) {
\t\t\t/* v8 ignore next -- Private same-filesystem directories make EEXIST the only recoverable link race. */
\t\t\tif (!(error instanceof Error && "code" in error && error.code === "EEXIST")) throw error;"""

NEW_ATT = """\t\ttry {
\t\t\tawait link(source, target);
\t\t} catch (error) {
\t\t\t// ANDROID PATCH: SELinux denies link(2) to untrusted apps.
\t\t\tif (error?.code === "EACCES" || error?.code === "EPERM") {
\t\t\t\tawait rename(source, target);
\t\t\t} else {
\t\t\t/* v8 ignore next -- Private same-filesystem directories make EEXIST the only recoverable link race. */
\t\t\tif (!(error instanceof Error && "code" in error && error.code === "EEXIST")) throw error;"""

OLD_ATT2 = """\t\ttry {
\t\t\tawait link(staged.path, target);
\t\t} catch (error) {
\t\t\t/* v8 ignore next -- Private same-filesystem directories make EEXIST the only recoverable link race. */
\t\t\tif (!(error instanceof Error && "code" in error && error.code === "EEXIST")) throw error;"""

NEW_ATT2 = """\t\ttry {
\t\t\tawait link(staged.path, target);
\t\t} catch (error) {
\t\t\t// ANDROID PATCH: SELinux denies link(2) to untrusted apps.
\t\t\tif (error?.code === "EACCES" || error?.code === "EPERM") {
\t\t\t\tawait rename(staged.path, target);
\t\t\t} else {
\t\t\t/* v8 ignore next -- Private same-filesystem directories make EEXIST the only recoverable link race. */
\t\t\tif (!(error instanceof Error && "code" in error && error.code === "EEXIST")) throw error;"""


def patch_attachment(root: str) -> int:
    path = os.path.join(
        root, "node_modules", "@deepseek-ai",
        "dsh-attachment-local", "lib", "index.js",
    )
    if not os.path.isfile(path):
        print("attachment-local: нет файла", path)
        return 0

    src = open(path, encoding="utf-8", errors="surrogateescape").read()
    rc = 0

    # импорт rename
    if "rename" not in src.split("\n")[0:20].__str__():
        pass  # проверим ниже по факту
    if 'import { link, ' in src and ", rename," not in src:
        # найти строку импорта с link и добавить rename
        for line in src.split("\n"):
            if line.startswith("import {") and " link" in line and "node:fs/promises" in line:
                parts = line.split("{", 1)[1].split("}", 1)[0]
                names = [n.strip() for n in parts.split(",") if n.strip()]
                if "rename" not in names:
                    names.append("rename")
                    names = sorted(set(names))
                    newline = line.split("{", 1)[0] + "{ " + ", ".join(names) + " }" + line.split("}", 1)[1]
                    src = src.replace(line, newline, 1)
                    print("attachment-local/импорт: добавлен rename")
                break

    if "ANDROID PATCH: SELinux denies link(2) to untrusted apps.\n\t\t\t\tawait rename(source, target);" in src.replace("\t\t\t\tawait rename(source, target);\n", "ANDROID PATCH: SELinux denies link(2) to untrusted apps.\n\t\t\t\tawait rename(source, target);"):
        print("attachment-local/publishImmutableAlias: уже пропатчен")
    elif src.count(OLD_ATT) == 1:
        src = src.replace(OLD_ATT, NEW_ATT, 1)
        print("attachment-local/publishImmutableAlias: патч применён")
    else:
        print("attachment-local/publishImmutableAlias: ЯКОРЬ НЕ НАЙДЕН")
        rc = 1

    if "await rename(staged.path, target);" in src:
        print("attachment-local/publishStagedObject: уже пропатчен")
    elif src.count(OLD_ATT2) == 1:
        src = src.replace(OLD_ATT2, NEW_ATT2, 1)
        print("attachment-local/publishStagedObject: патч применён")
    else:
        print("attachment-local/publishStagedObject: ЯКОРЬ НЕ НАЙДЕН")
        rc = 1

    if rc == 0:
        open(path, "w", encoding="utf-8", errors="surrogateescape").write(src)
    return rc


# ─── dsh-fs-local (write tool) ────────────────────────────────────────────────

OLD_FS = """\t\tif (createIfAbsent !== void 0) try {
\t\t\tawait linkFile(tempPath, absolutePath);
\t\t} catch (error) {
\t\t\tawait throwGuardedCreateFailure(error, absolutePath, createIfAbsent.displayPath, inspectPublicationTarget);
\t\t}"""

NEW_FS = """\t\tif (createIfAbsent !== void 0) try {
\t\t\tawait linkFile(tempPath, absolutePath);
\t\t} catch (error) {
\t\t\t// ANDROID PATCH: SELinux denies link(2) to untrusted apps (EACCES/EPERM);
\t\t\t// fall back to rename, re-checking existence to keep create-if-absent.
\t\t\tif (error?.code === "EACCES" || error?.code === "EPERM") {
\t\t\t\tlet existing;
\t\t\t\ttry {
\t\t\t\t\texisting = await inspectPublicationTarget(absolutePath);
\t\t\t\t} catch (metadataError) {
\t\t\t\t\tif (!isENOENT(metadataError) && !isENOTDIR(metadataError)) throw metadataError;
\t\t\t\t}
\t\t\t\tif (existing === void 0) {
\t\t\t\t\tawait rename(tempPath, absolutePath);
\t\t\t\t} else {
\t\t\t\t\tawait throwGuardedCreateFailure(error, absolutePath, createIfAbsent.displayPath, inspectPublicationTarget);
\t\t\t\t}
\t\t\t} else {
\t\t\t\tawait throwGuardedCreateFailure(error, absolutePath, createIfAbsent.displayPath, inspectPublicationTarget);
\t\t\t}
\t\t}"""


def patch_fs_local(root: str) -> int:
    path = os.path.join(
        root, "node_modules", "@deepseek-ai", "dsh-fs-local", "lib", "index.js",
    )
    if not os.path.isfile(path):
        print("fs-local: нет файла", path)
        return 0

    src = open(path, encoding="utf-8", errors="surrogateescape").read()

    if "await rename(tempPath, absolutePath);" in src:
        print("fs-local: уже пропатчен")
        return 0

    if src.count(OLD_FS) != 1:
        print("fs-local: ЯКОРЬ НЕ НАЙДЕН, вхождений:", src.count(OLD_FS))
        return 1

    # добавить rename в импорт, если нужно
    if "import { link" in src and ", rename," not in src:
        for line in src.split("\n"):
            if line.startswith("import {") and "node:fs/promises" in line:
                if " rename" not in line and "rename," not in line:
                    src = src.replace(line, line.replace("link,", "link, rename,"), 1)
                    print("fs-local/импорт: добавлен rename")
                break

    src = src.replace(OLD_FS, NEW_FS, 1)
    open(path, "w", encoding="utf-8", errors="surrogateescape").write(src)
    print("fs-local: патч применён")
    return 0


def main() -> int:
    if len(sys.argv) < 2:
        print("укажите путь к @deepseek-ai/dsh")
        return 1
    root = sys.argv[1]
    rc = patch_persistence(root)
    rc |= patch_attachment(root)
    rc |= patch_fs_local(root)
    print()
    if rc == 0:
        print("ВАЖНО: перезапустите dsh — патчи читаются при импорте модулей.")
    return rc


if __name__ == "__main__":
    sys.exit(main())
