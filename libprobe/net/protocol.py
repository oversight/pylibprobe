import asyncio
import logging
from .package import Package


RESPONSE_BIT = 0x80


class Protocol(asyncio.Protocol):

    _connected = False

    def __init__(self):
        super().__init__()
        self._buffered_data = bytearray()
        self._package = None
        self._requests = dict()
        self._pid = 0
        self.transport = None

    def connection_made(self, transport):
        '''
        override asyncio.Protocol
        '''
        self.transport = transport

    def connection_lost(self, exc):
        '''
        override asyncio.Protocol
        '''
        self.transport = None
        self._package = None
        self._buffered_data.clear()

    def is_connected(self):
        return self.transport is not None

    def request(self, pkg, timeout=None):
        self._pid += 1
        self._pid %= 0x10000

        pkg.pid = self._pid

        task = asyncio.ensure_future(
            self._timer(pkg.pid, timeout)) if timeout else None

        future = asyncio.Future()
        self._requests[pkg.pid] = (future, task)

        self.transport.write(pkg.to_bytes())

        return future

    def data_received(self, data):
        '''
        override asyncio.Protocol
        '''
        self._buffered_data.extend(data)
        while self._buffered_data:
            size = len(self._buffered_data)
            if self._package is None:
                if size < Package.st_package.size:
                    return None
                self._package = Package(self._buffered_data)
            if size < self._package.total:
                return None
            try:
                self._package.extract_data_from(self._buffered_data)
            except KeyError as e:
                logging.error(f'unsupported package received: {e}')
            except Exception as e:
                logging.exception(e)
                # empty the byte-array to recover from this error
                self._buffered_data.clear()
            else:
                self.on_package_received(self._package)
            self._package = None

    def on_package_received(self, pkg):
        raise NotImplementedError

    async def _timer(self, pid, timeout):
        await asyncio.sleep(timeout)
        try:
            future, task = self._requests.pop(pid)
        except KeyError:
            logging.error('timed out package id not found: {}'.format(
                self._package.pid))
            return None

        future.set_exception(TimeoutError(
            f'request timed out on pkg id {pid}'))

    def _get_future(self, pkg, default_=(None, None)):
        future, task = self._requests.pop(pkg.pid, default_)
        if future is None:
            logging.error(
                f'got a response on pkg id {pkg.pid} but the original '
                'request has probably timed-out'
            )
            return
        task.cancel()
        return future