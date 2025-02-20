from queue import Queue


class DoubleBuffer:
    """A double buffer class for queue processing."""

    def __init__(self):
        self.q1 = Queue()
        self.q2 = Queue()
        self.retry = Queue()
        self.active = self.q1
        self.passive = self.q2

    def put(self, item):
        """Puts an item into the active queue."""
        self.active.put(item)

    def swap(self):
        """Swaps the buffer queues."""
        self.active, self.passive = self.passive, self.active

    def get_all(self):
        """Retrieves all items from the active buffer and clears it."""
        self.swap()
        items = list(self.passive.queue)
        self.passive.queue.clear()
        return items
