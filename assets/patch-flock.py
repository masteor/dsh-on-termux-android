#!/usr/bin/env python3
"""Android-патч: реализовать flock на Termux через libc (koffi FFI).

Проблема: @deepseek-ai/node-addon-system/flock.js жёстко проверяет
`platform !== 'linux' && platform !== 'darwin'` и на Termux (platform === 'android')
бросает ERR_FLOCK_UNSUPPORTED_PLATFORM: "flock is not supported on android-arm64".

Симптом в UI: каждый ход падает с "This turn failed: flock is not supported on
android-arm64" — flock нужен dsh-session-persistence-jsonl для эксклюзивной
блокировки журнала сессии.

Готовой сборки node-addon-system-android-arm64 не существует, и Termux — bionic,
поэтому ветка glibc/musl тоже не подходит.

Решение: вызывать flock(2) из libc через koffi, который на этом хосте уже собран
под android-arm64 (он и так зависимость dsh). Семантика идентична нативной
обёртке: неблокирующий эксклюзивный flock, возврат errno.

Идемпотентен.

Использование:
    python3 patch-flock.py "$(npm root -g)/@deepseek-ai/dsh"
"""
import os
import sys

OLD = """    const { platform, arch } = process;
    if (platform !== 'linux' && platform !== 'darwin') {
        throw Object.assign(new Error(`flock is not supported on ${platform}-${arch}`), {
            code: 'ERR_FLOCK_UNSUPPORTED_PLATFORM',
            syscall: 'flock',
        });
    }"""

NEW = """    const { platform, arch } = process;
    // ANDROID PATCH: Termux reports platform === 'android' and uses bionic, so
    // neither the linux-glibc/musl prebuild nor the darwin one applies. Call
    // flock(2) straight from libc via koffi (already present for android-arm64).
    if (platform === 'android') {
        const require = createRequire(import.meta.url);
        const koffi = require('koffi');
        const libc = koffi.load('libc.so');
        const flockNative = libc.func('int flock(int fd, int op)');
        binding = {
            tryLock(fd, callback) {
                // LOCK_EX | LOCK_NB = 2 | 4 = 6; errno read via koffi.errno()
                const rc = flockNative(fd, 6);
                if (rc === 0) return callback(0);
                callback(koffi.errno() || 11 /* EAGAIN */);
            },
        };
        return binding;
    }
    if (platform !== 'linux' && platform !== 'darwin') {
        throw Object.assign(new Error(`flock is not supported on ${platform}-${arch}`), {
            code: 'ERR_FLOCK_UNSUPPORTED_PLATFORM',
            syscall: 'flock',
        });
    }"""


def main() -> int:
    if len(sys.argv) < 2:
        print("укажите путь к @deepseek-ai/dsh")
        return 1

    path = os.path.join(
        sys.argv[1],
        "node_modules",
        "@deepseek-ai",
        "node-addon-system",
        "lib",
        "flock.js",
    )
    if not os.path.isfile(path):
        print("нет файла:", path)
        return 1

    src = open(path, encoding="utf-8", errors="surrogateescape").read()

    if "ANDROID PATCH: Termux reports platform" in src:
        print("flock: уже пропатчен")
        return 0

    if src.count(OLD) != 1:
        print("flock: ЯКОРЬ НЕ НАЙДЕН, вхождений:", src.count(OLD))
        print("       вероятно, изменилась версия node-addon-system")
        return 1

    open(path, "w", encoding="utf-8", errors="surrogateescape").write(
        src.replace(OLD, NEW, 1)
    )
    print("flock: патч применён (flock через libc/koffi)")
    print()
    print("ВАЖНО: перезапустите dsh, патч читается при импорте модуля.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
