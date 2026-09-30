/* Минимальный shim-заголовок spawn.h для Termux/bionic.
 *
 * Проблема: пакет Termux `libandroid-spawn` — это ТОЛЬКО симлинк на libc
 * ($PREFIX/lib/libandroid-spawn.so), заголовка в нём нет. Bionic предоставляет
 * posix_spawn* в libc начиная с API 28 (на проверенном устройстве API 33), но
 * заголовок spawn.h не поставляет. Без него сборка koffi падает:
 *
 *     base.cc:81:14: fatal error: 'spawn.h' file not found
 *
 * Установка:
 *     cat spawn.h > $PREFIX/include/spawn.h
 *
 * Проверка (в Termux НЕТ /tmp — используйте $HOME):
 *     printf '#include <spawn.h>\nint main(){posix_spawn_file_actions_t f;' > ~/t.c
 *     printf 'posix_spawn_file_actions_init(&f);posix_spawn_file_actions_destroy(&f);return 0;}\n' >> ~/t.c
 *     clang ~/t.c -o ~/t && ~/t && echo OK
 *
 * ВНИМАНИЕ: файл может исчезнуть при обновлении пакетов Termux (pkg upgrade) —
 * если сборка снова ругается на spawn.h, пересоздайте.
 */
#ifndef _SPAWN_H_SHIM
#define _SPAWN_H_SHIM

#include <sys/types.h>
#include <signal.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct { void *__data[16]; } posix_spawn_file_actions_t;
typedef struct { void *__data[16]; } posix_spawnattr_t;

int posix_spawn(pid_t *pid, const char *path,
                const posix_spawn_file_actions_t *file_actions,
                const posix_spawnattr_t *attrp,
                char *const argv[], char *const envp[]);

int posix_spawnp(pid_t *pid, const char *file,
                 const posix_spawn_file_actions_t *file_actions,
                 const posix_spawnattr_t *attrp,
                 char *const argv[], char *const envp[]);

int posix_spawn_file_actions_init(posix_spawn_file_actions_t *fa);
int posix_spawn_file_actions_destroy(posix_spawn_file_actions_t *fa);
int posix_spawn_file_actions_adddup2(posix_spawn_file_actions_t *fa, int fd, int newfd);
int posix_spawn_file_actions_addclose(posix_spawn_file_actions_t *fa, int fd);
int posix_spawn_file_actions_addopen(posix_spawn_file_actions_t *fa, int fd,
                                     const char *path, int oflag, mode_t mode);

int posix_spawnattr_init(posix_spawnattr_t *attr);
int posix_spawnattr_destroy(posix_spawnattr_t *attr);
int posix_spawnattr_setflags(posix_spawnattr_t *attr, short flags);

#ifdef __cplusplus
}
#endif

#endif /* _SPAWN_H_SHIM */
