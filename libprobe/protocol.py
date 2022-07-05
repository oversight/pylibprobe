import logging
import time
from typing import Callable
from .net.package import Package
from .net.protocol import Protocol


class AgentcoreProtocol(Protocol):

    PROTO_FAF_DUMP = 0x00

    PROTO_REQ_ANNOUNCE = 0x01

    PROTO_FAF_ASSETS = 0x02

    PROTO_REQ_INFO = 0x03

    PROTO_RES_ANNOUNCE = 0x81

    PROTO_RES_INFO = 0x82

    def __init__(self, _on_assets: Callable):
        super().__init__()
        self._on_assets = _on_assets

    def _on_res_announce(self, pkg):
        logging.debug(f'on announce {len(pkg.data)}')
        self._on_assets(pkg.data)

        future = self._get_future(pkg)
        if future is None:
            return
        future.set_result(pkg.data)

    def _on_faf_assets(self, pkg):
        logging.debug(f'on assets {len(pkg.data)}')
        self._on_assets(pkg.data)

    def _on_req_info(self, pkg: Package):
        logging.debug(f'on heartbeat')

        resp_pkg = Package.make(
            AgentcoreProtocol.PROTO_RES_INFO,
            pid=pkg.pid,
            data=time.time()
        )
        self.transport.write(resp_pkg.to_bytes())

    def on_package_received(self, pkg, _map={
        PROTO_RES_ANNOUNCE: _on_res_announce,
        PROTO_FAF_ASSETS: _on_faf_assets,
        PROTO_REQ_INFO: _on_req_info,
    }):
        handle = _map.get(pkg.tp)
        if handle is None:
            logging.error(f'unhandled package type: {pkg.tp}')
        else:
            handle(self, pkg)
