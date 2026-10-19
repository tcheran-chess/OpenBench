import contextlib
import json
import logging
import os
import tempfile

from OpenSite.settings import MEDIA_ROOT

## LLR History
##
## Result submissions feed a (games, llr, verdict) series in a small JSON file,
## which the workload page renders as an inline SVG sparkline. The series is
## append-only, and downsampled once it grows past twice the cap.
##
## Submissions arrive far faster than the curve says anything new, so a sample
## is only taken once LLR_HISTORY_INTERVAL games have been played since the
## last one, and its LLR is an EMA over the previous sample rather than the
## raw value. The raw LLR still drives pass/fail; only the drawn curve is
## smoothed, and the final sample of a finished test is recorded unsmoothed so
## the graph ends where the test actually stopped.

LLR_HISTORY_SIZE     = 120
LLR_HISTORY_INTERVAL = 50
LLR_HISTORY_ALPHA    = 0.30

_logger = logging.getLogger(__name__)

try: import fcntl
except ImportError: fcntl = None

try: import msvcrt
except ImportError: msvcrt = None

def llr_history_path(test_id):
    return os.path.join(MEDIA_ROOT, 'llr_history', '%d.json' % (test_id))

@contextlib.contextmanager
def _history_lock(path):

    # Serialize the whole read-modify-write. Two concurrent result submissions
    # would otherwise both load the same file, and the slower writer would
    # clobber the faster one's appends, leaving gaps in the series.

    os.makedirs(os.path.dirname(path), exist_ok=True)
    lockfd = os.open(path + '.lock', os.O_CREAT | os.O_RDWR, 0o644)

    try:
        if fcntl:
            fcntl.flock(lockfd, fcntl.LOCK_EX)
        elif msvcrt:
            msvcrt.locking(lockfd, msvcrt.LK_LOCK, 1)
        yield
    finally:
        try:
            if not fcntl and msvcrt:
                os.lseek(lockfd, 0, os.SEEK_SET)
                msvcrt.locking(lockfd, msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        os.close(lockfd)

def _read_llr_history(path):

    if not os.path.exists(path):
        return None

    with open(path) as fin:
        content = fin.read()

    if not content.strip():
        return None

    history = json.loads(content)

    if not isinstance(history, list) or not all(
            isinstance(p, list) and 2 <= len(p) <= 3 for p in history):
        raise ValueError('Malformed LLR history in %s' % (path))

    return history

def _write_llr_history(path, history):

    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmppath = tempfile.mkstemp(dir=os.path.dirname(path), suffix='.tmp')

    try:
        with os.fdopen(fd, 'w') as fout:
            json.dump(history, fout)
        os.replace(tmppath, path)

    except Exception:
        try: os.unlink(tmppath)
        except OSError: pass
        raise

def downsample_history(history, target_size):

    N = len(history)
    if N <= target_size or target_size < 2:
        return history

    buckets = target_size - 2
    step    = (N - 2) / float(buckets)
    out     = [history[0]]

    for i in range(buckets):
        lo, hi = int(i * step) + 1, max(int((i + 1) * step) + 1, int(i * step) + 2)
        bucket = history[lo:hi]
        if bucket: # Keep the most extreme sample, so peaks survive
            out.append(max(bucket, key=lambda p: abs(p[1])))

    out.append(history[-1])
    return out

def load_llr_history(test):

    try:
        history = _read_llr_history(llr_history_path(test.id))
    except Exception:
        _logger.warning('Failed to load LLR history for Test %s', test.id, exc_info=True)
        return [[0, 0.0]]

    return history or [[0, 0.0]]

def record_llr_history(test):

    path = llr_history_path(test.id)

    with _history_lock(path):

        try:
            history = _read_llr_history(path)

        except Exception:
            _logger.warning('Corrupt LLR history %s; starting fresh', path, exc_info=True)
            try: os.replace(path, path + '.corrupt')
            except OSError: pass
            history = None

        history = history or [[0, 0.0]]

        if test.games < history[-1][0]:
            return

        # Hold off until enough games have accumulated to be worth a sample.
        # A finished test always records, so the curve reaches its endpoint.
        played = test.games - history[-1][0]
        if played < LLR_HISTORY_INTERVAL and not test.finished:
            return

        llr = test.currentllr
        if not test.finished:
            llr = LLR_HISTORY_ALPHA * llr + (1 - LLR_HISTORY_ALPHA) * history[-1][1]

        point = [test.games, round(llr, 4), int(test.wins >= test.losses)]

        if history[-1][0] == point[0]:
            history[-1] = point
        else:
            history.append(point)

        if history[0][0] != 0:
            history.insert(0, [0, 0.0])

        if len(history) >= LLR_HISTORY_SIZE * 2:
            history = downsample_history(history, LLR_HISTORY_SIZE)

        _write_llr_history(path, history)



def safe_record_llr_history(test):
    try:
        record_llr_history(test)
    except Exception:
        _logger.warning('Failed to record LLR history for Test %s', test.id, exc_info=True)
