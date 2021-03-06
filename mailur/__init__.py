import functools as ft
import hashlib
import inspect
import logging
import logging.config
import os
import signal
import time
import uuid
from contextlib import contextmanager

from gevent import sleep

cache = {}
conf = {
    'DEBUG': os.environ.get('MLR_DEBUG', True),
    'DEBUG_IMAP': os.environ.get('MLR_DEBUG_IMAP', 0),
    'IMAP_OFF': os.environ.get('MLR_IMAP_OFF', '').split(),
    'SECRET': os.environ.get('MLR_SECRET', uuid.uuid4().hex),
    'MASTER': os.environ.get('MLR_MASTER', 'root:root').split(':'),
    'USER': os.environ.get('MLR_USER', 'user'),
}


class UserFilter(logging.Filter):
    def filter(self, record):
        record.user = conf['USER']
        return True


log = logging.getLogger(__name__)
log.addFilter(UserFilter())
logging.config.dictConfig({
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {'f': {
        'datefmt': '%Y-%m-%d %H:%M:%S%Z',
        'format': (
            '[%(asctime)s][%(process)s][%(user)s][%(levelname).3s] %(message)s'
        ),
    }},
    'handlers': {'h': {
        'class': 'logging.StreamHandler',
        'level': logging.DEBUG,
        'formatter': 'f',
        'stream': 'ext://sys.stdout',
    }},
    'loggers': {
        __name__: {
            'handlers': 'h',
            'level': logging.DEBUG if conf['DEBUG'] else logging.INFO,
            'propagate': False
        },
        '': {
            'handlers': 'h',
            'level': logging.INFO,
            'propagate': False
        },
    }
})


def fn_desc(func, *a, **kw):
    args = ', '.join(
        [repr(i) for i in a] +
        (['**%r' % kw] if kw else [])
    )
    maxlen = 80
    if len(args) > maxlen:
        args = '%s...' % args[:maxlen]
    name = getattr(func, 'name', None)
    if not name:
        name = getattr(func, '__name__', None)
    if not name:
        name = str(func)
    return '%s(%s)' % (name, args)


def fn_time(func, desc=None):
    @contextmanager
    def timing(*a, **kw):
        start = time.time()
        try:
            yield
        finally:
            d = desc if desc else fn_desc(func, *a, **kw)
            log.debug('## %s: done for %.2fs', d, time.time() - start)

    def inner_fn(*a, **kw):
        with timing(*a, **kw):
            return func(*a, **kw)

    def inner_gen(*a, **kw):
        with timing(*a, **kw):
            yield from func(*a, **kw)

    inner = inner_gen if inspect.isgeneratorfunction(func) else inner_fn
    return ft.wraps(func)(inner)


def fn_cache(fn):
    def get_cache():
        cache = user_cache()
        cache.setdefault(fn, {})
        return cache[fn]

    @ft.wraps(fn)
    def inner(*a, **kw):
        cache = get_cache()
        key = a, tuple((k, kw[k]) for k in sorted(kw))
        if key not in cache:
            res = fn(*a, **kw)
            cache[key] = res
        return cache[key]

    inner.cache_clear = lambda: get_cache().clear()
    return inner


def user_cache():
    global cache

    user = conf['USER']
    cache.setdefault(user, {})
    return cache[user]


class LockError(Exception):
    pass


@contextmanager
def global_lock(target, timeout=180, wait=3, force=False):
    path = '/tmp/%s' % (hashlib.md5(target.encode()).hexdigest())

    def is_locked():
        if not os.path.exists(path):
            return

        with open(path) as f:
            pid = f.read()

        # Check if process exists
        try:
            os.kill(int(pid), 0)
        except (OSError, ValueError):
            os.remove(path)
            return

        elapsed = time.time() - os.path.getctime(path)
        if elapsed > timeout or force:
            try:
                os.kill(int(pid), signal.SIGQUIT)
                os.remove(path)
            except Exception:
                pass
            return
        return elapsed

    locked = True
    for i in range(wait):
        locked = is_locked()
        if not locked:
            break
        sleep(1)

    if locked:
        msg = (
            '## %r is locked (for %.2f minutes). Remove file %r to run'
            % (target, locked, path)
        )
        raise LockError(msg)

    try:
        with open(path, 'w') as f:
            f.write(str(os.getpid()))
        yield
    finally:
        os.remove(path)


@contextmanager
def user_lock(target, **opts):
    target = '%s:%s' % (conf['USER'], target)
    with global_lock(target, **opts):
        yield
