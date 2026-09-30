#!/usr/bin/env python3
"""Android-патч koffi: убрать statx(2) из сборки.

Проблема: koffi вызывает statx(2) под `#if defined(__linux__)`. В Android/bionic
`statx` — это имя ТИПА структуры, а не функция, поэтому компиляция падает с
"cannot initialize a member subobject of type '__u32' with an lvalue of type
'const char *'". У koffi есть рабочий fallback на fstatat — надо лишь не входить
в эту ветку на Android.

Покрывает обе версии:
  * koffi 3.1.1 (в dsh 0.2.0-rc.2) — голый `#if defined(__linux__)`, патч НУЖЕН;
  * koffi 3.2.1 (в dsh 0.1.5-rc.1) — уже `#if defined(__linux__) && defined(STATX_TYPE)`.

Идемпотентен: повторный запуск ничего не делает.

Использование:
    python3 patch-koffi.py "$(npm root -g)/@deepseek-ai/dsh"
"""
import os
import sys


def main() -> int:
    if len(sys.argv) < 2:
        print("укажите путь к @deepseek-ai/dsh")
        return 1

    path = os.path.join(
        sys.argv[1], "node_modules", "koffi", "lib", "native", "base", "base.cc"
    )
    if not os.path.isfile(path):
        print("нет файла:", path)
        return 1

    src = open(path, encoding="utf-8", errors="surrogateescape").read()

    if "!defined(__ANDROID__)" in src:
        print("koffi: уже пропатчен")
        return 0

    # Якорь — начало тела StatAt с голым linux-guard.
    old = """static StatResult StatAt(int fd, bool fd_is_directory, const char *filename, unsigned int flags, FileInfo *out_info)
{
#if defined(__linux__)
    const char *pathname = filename;"""

    # Вариант 3.2.1: guard с STATX_TYPE — патч не требуется.
    if "#if defined(__linux__) && defined(STATX_TYPE)" in src:
        print("koffi: апстрим уже guard'ит statx через STATX_TYPE — патч не нужен")
        return 0

    if src.count(old) != 1:
        print("koffi: ЯКОРЬ НЕ НАЙДЕН, вхождений:", src.count(old))
        print("       вероятно, изменилась версия koffi — сверься с апстримом")
        return 1

    new = old.replace(
        "#if defined(__linux__)",
        "// statx(2) unavailable on Android/bionic; use the fstatat fallback.\n"
        "#if defined(__linux__) && !defined(__ANDROID__)",
    )

    open(path, "w", encoding="utf-8", errors="surrogateescape").write(
        src.replace(old, new, 1)
    )
    print("koffi: патч statx применён")
    print("дальше: cd", os.path.dirname(os.path.dirname(os.path.dirname(path))))
    print("        node ./cnoke.cjs -P . -D src/koffi --prebuild --release")
    return 0


if __name__ == "__main__":
    sys.exit(main())
