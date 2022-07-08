import asyncio
import logging
import os
import random
import time
from configparser import ConfigParser, NoSectionError
from pathlib import Path
from setproctitle import setproctitle
from typing import Optional
from .exceptions import (
    CheckException,
    IgnoreResultException,
    IgnoreCheckException,
    IncompleteResultException,
)
from .logger import setup_logger
from .net.package import Package
from .protocol import AgentcoreProtocol
from .asset import Asset
from .severity import Severity


AGENTCORE_HOST = os.getenv('AGENTCORE_HOST', '127.0.0.1')
AGENTCORE_PORT = int(os.getenv('AGENTCORE_PORT', 8750))
OVERSIGHT_CONF_FN = os.getenv('OVERSIGHT_CONF', '/data/config/oversight.conf')

# Index in names
ASSET_NAME_IDX, CHECK_NAME_IDX = range(2)


class Probe:
    """This class should only be initialized once."""

    def __init__(
        self,
        name: str,
        version: str,
        checks: dict,
        config_path: Optional[str] = OVERSIGHT_CONF_FN
    ):
        setproctitle(name)
        setup_logger()

        self.name = name
        self.version = version
        self._checks_funs = checks
        self._config_path = Path(config_path)
        self._connecting = False
        self._protocol = None
        self._retry_next = 0
        self._retry_step = 1
        self._local_config = None
        self._local_config_mtime = None
        self._checks_config = {}
        self._checks = {}

        if not os.path.exists(config_path):
            logging.error(f"config file not found: {config_path}")
            exit(0)
        try:
            self._read_local_config()
        except Exception:
            logging.exception(f"config file invalid: {config_path}")
            exit(0)

    def is_connected(self) -> bool:
        return self._protocol is not None and self._protocol.is_connected()

    def is_connecting(self) -> bool:
        return self._connecting

    async def start(self):
        initial_step = 2
        step = 2
        max_step = 2 ** 7

        while True:
            if not self.is_connected() and not self.is_connecting():
                asyncio.ensure_future(self._connect())
                step = min(step * 2, max_step)
            else:
                step = initial_step
            await asyncio.sleep(step)

    async def _connect(self):
        conn = asyncio.get_event_loop().create_connection(
            lambda: AgentcoreProtocol(self._on_assets),
            host=AGENTCORE_HOST,
            port=AGENTCORE_PORT
        )
        self._connecting = True

        try:
            _, self._protocol = await asyncio.wait_for(conn, timeout=10)
        except Exception as e:
            error_msg = str(e) or type(e).__name__
            logging.error(f'connecting to agentcore failed: {error_msg}')
        else:
            pkg = Package.make(
                AgentcoreProtocol.PROTO_REQ_ANNOUNCE,
                data=[self.name, self.version]
            )
            if self._protocol and self._protocol.transport:
                try:
                    await self._protocol.request(pkg, timeout=10)
                except Exception as e:
                    logging.error(e)
        finally:
            self._connecting = False

    def send(self, path: tuple, rows: dict, ts: float):
        _, asset_id, _ = path
        pkg = Package.make(
            AgentcoreProtocol.PROTO_FAF_DUMP,
            partid=asset_id,
            data=[path, rows, ts]
        )

        if self._protocol and self._protocol.transport:
            self._protocol.transport.write(pkg.to_bytes())

    def close(self):
        if self._protocol and self._protocol.transport:
            self._protocol.transport.close()
        self._protocol = None

    def _read_local_config(self):
        mtime = self._config_path.stat().st_mtime
        if mtime == self._local_config_mtime:
            return
        config = ConfigParser()
        config.read(self._config_path)
        self._local_config_mtime = mtime
        self._local_config = config

    def _asset_config(self, asset_id: int) -> dict:
        try:
            self._read_local_config()
        except Exception:
            logging.warning('new config file invalid, keep using previous')

        try:
            return self._local_config[f'{self.name}/{asset_id}']
        except (NoSectionError, KeyError):
            pass
        try:
            return self._local_config[self.name]
        except (NoSectionError, KeyError):
            return {}

    def _on_assets(self, assets: list):
        new_checks_config = {
            tuple(path): (names, config)
            for path, names, config in assets
            if names[CHECK_NAME_IDX] in self._checks_funs}

        desired_checks = set(new_checks_config)

        for path in set(self._checks):
            if path not in desired_checks:
                # the check is no longer required, pop and cancel the task
                self._checks.pop(path).cancel()
            elif new_checks_config[path] != self._checks_config[path] and \
                    self._checks[path].cancelled():
                # this task is desired but has previously been cancelled;
                # now the config has been changed so we want to re-scheduled.
                del self._checks[path]

        # overwite check_config
        self._checks_config = new_checks_config

        # start new checks
        for path in desired_checks - set(self._checks):
            self._checks[path] = asyncio.ensure_future(
                self._run_check_loop(path)
            )

    async def _run_check_loop(self, path: tuple):
        _, asset_id, _ = path
        (asset_name, check_name), config = self._checks_config[path]
        interval = config.get('_interval')
        fun = self._checks_funs[check_name]
        asset = Asset(asset_id, asset_name, check_name)

        my_task = self._checks[path]

        assert isinstance(interval, int) and interval > 0

        ts = time.time()
        ts_next = int(ts + random.random() * interval) + 1

        while True:
            assert ts < ts_next

            try:
                await asyncio.sleep(ts_next - ts)
            except asyncio.CancelledError:
                logging.info(f'cancelled; {asset}')
                break

            asset_config = self._asset_config(asset.id)
            _, config = self._checks_config[path]
            interval = config.get('_interval')
            timeout = 0.8 * interval

            logging.debug(f'run check; {asset}')

            try:
                try:
                    res = await asyncio.wait_for(
                        fun(asset, asset_config, config), timeout=timeout)
                    if not isinstance(res, dict):
                        raise TypeError(
                            'expecting type `dict` as check result '
                            f'but got type `{type(res).__name__}`')
                except asyncio.TimeoutError:
                    raise CheckException('timed out')
                except asyncio.CancelledError:
                    if my_task is self._checks.get(path):
                        # cancelled from within, just raise
                        raise CheckException('cancelled')
                    logging.warning(f'cancelled; {asset}')
                    break
                except (IgnoreCheckException,
                        IgnoreResultException,
                        CheckException):
                    raise
                except Exception as e:
                    # fall-back to exception class name
                    error_msg = str(e) or type(e).__name__
                    raise CheckException(error_msg)

            except IgnoreResultException:
                logging.info(f'ignore result; {asset}')

            except IgnoreCheckException:
                # log as warning; the user is able to prevent this warning by
                # disabling the check if not relevant for the asset;
                logging.warning(f'ignore check; {asset}')
                break

            except IncompleteResultException as e:
                logging.warning(
                    'incomplete result; '
                    f'{asset} error: `{e}` severity: {e.severity}')
                self.send(path, (e.result, e.to_dict()), ts_next)

            except CheckException as e:
                logging.error(
                    'check error; '
                    f'{asset} error: `{e}` severity: {e.severity}')
                self.send(path, (None, e.to_dict()), ts_next)

            else:
                logging.debug(f'run check ok; {asset}')
                self.send(path, (res, None), ts_next)

            ts = time.time()
            ts_next += interval
