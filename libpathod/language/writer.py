import time
import netlib.tcp

BLOCKSIZE = 1024


def send_chunk(fp, val, blocksize, start, end):
    """
        (start, end): Inclusive lower bound, exclusive upper bound.
    """
    for i in range(start, end, blocksize):
        fp.write(
            val[i:min(i + blocksize, end)]
        )
    return end - start


def write_values(fp, vals, actions, sofar=0, blocksize=BLOCKSIZE):
    """
        vals: A list of values, which may be strings or Value objects.

        actions: A list of (offset, action, arg) tuples. Action may be "pause"
        or "disconnect".

        Both vals and actions are in reverse order, with the first items last.

        Return True if connection should disconnect.
    """
    sofar = 0
    try:
        while vals:
            v = vals.pop()
            offset = 0
            while actions and actions[-1][0] < (sofar + len(v)):
                a = actions.pop()
                offset += send_chunk(
                    fp,
                    v,
                    blocksize,
                    offset,
                    a[0] - sofar - offset
                )
                if a[1] == "pause":
                    time.sleep(a[2])
                elif a[1] == "disconnect":
                    return True
                elif a[1] == "inject":
                    send_chunk(fp, a[2], blocksize, 0, len(a[2]))
            send_chunk(fp, v, blocksize, offset, len(v))
            sofar += len(v)
        # Remainders
        while actions:
            a = actions.pop()
            if a[1] == "pause":
                time.sleep(a[2])
            elif a[1] == "disconnect":
                return True
            elif a[1] == "inject":
                send_chunk(fp, a[2], blocksize, 0, len(a[2]))
    except netlib.tcp.NetLibDisconnect:  # pragma: no cover
        return True
