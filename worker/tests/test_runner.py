import multiprocessing

from worker.runner import _receive_progress


def test_closed_progress_pipe_is_handled_on_all_platforms():
    receiver, sender = multiprocessing.get_context("spawn").Pipe(duplex=False)
    try:
        sender.send(("parsing", 30))
        assert _receive_progress(receiver, 1) == ("parsing", 30)
        sender.close()
        assert _receive_progress(receiver, 1) is False
    finally:
        receiver.close()
