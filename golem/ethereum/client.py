import atexit
import json
import logging
import os
import time
from os import path
from subprocess import Popen

import appdirs
import psutil
import rlp
from eth_rpc_client import Client as EthereumRpcClient

from golem.environments.utils import find_program
from golem.utils import find_free_net_port

log = logging.getLogger('golem.eth.rpc')


class Client(EthereumRpcClient):

    STATIC_NODES = ["enode://f1fbbeff7e9777a3a930f1e55a5486476845f799f7d603f71be7b00898df98f2dc2e81b854d2c774c3d266f1fa105d130d4a43bc58e700155c4565726ae6804e@94.23.17.170:30900"]  # noqa

    __client_subprocess = None
    __client_rpc_port = None
    __client_datadir = None

    @staticmethod
    def __start_client_subprocess(datadir):
        if not Client.__client_subprocess:
            assert not Client.__client_rpc_port
            program = find_program('geth')
            assert program  # TODO: Replace with a nice exception
            rpcport = find_free_net_port(9001)
            # Data dir must be set the class user to allow multiple nodes running
            if not datadir:
                datadir = path.join(appdirs.user_data_dir('golem'), 'ethereum9')
            Client.__client_datadir = datadir
            basedir = path.dirname(__file__)
            genesis_file = path.join(basedir, 'genesis_golem.json')
            args = [
                program,
                '--datadir', datadir,
                '--rpc',
                '--rpcport', str(rpcport),
                '--networkid', '9',
                '--genesis', genesis_file,
                '--nodiscover',
                '--gasprice', '0',
                '--verbosity', '0',
            ]

            Client.__config_static_nodes(datadir)
            Client.__client_subprocess = Popen(args)
            Client.__client_rpc_port = rpcport
            atexit.register(Client.__terminate_client_subprocess)
            # FIXME: We should check if the process was started.
            ps = psutil.Process(Client.__client_subprocess.pid)
            WAIT_PERIOD = 0.01
            wait_time = 0
            while True:
                # FIXME: Add timeout limit, we don't want to loop here forever.
                time.sleep(WAIT_PERIOD)
                if rpcport in set(c.laddr[1] for c in ps.connections('tcp')):
                    break
                wait_time += WAIT_PERIOD
            log.info("Ethereum client started in {} s: `{}`"
                     .format(wait_time, " ".join(args)))

    @staticmethod
    def __terminate_client_subprocess():
        if Client.__client_subprocess:
            start_time = time.clock()
            Client.__client_subprocess.terminate()
            Client.__client_subprocess.wait()
            Client.__client_subprocess = None
            Client.__client_rpc_port = None
            duration = time.clock() - start_time
            log.info("Ethereum client terminated in {:.2f} s".format(duration))

    @staticmethod
    def __config_static_nodes(datadir):
        if not path.exists(datadir):
            os.makedirs(datadir)
        assert path.isdir(datadir)
        file = path.join(datadir, 'static-nodes.json')
        if not path.exists(file):
            json.dump(Client.STATIC_NODES, open(file, 'w'))

    def __init__(self, datadir=None):
        if datadir and self.__client_datadir:
            assert datadir == self.__client_datadir
        self.__start_client_subprocess(datadir)
        assert self.__client_subprocess and self.__client_rpc_port
        super(Client, self).__init__(port=self.__client_rpc_port)

    def get_peer_count(self):
        """
        https://github.com/ethereum/wiki/wiki/JSON-RPC#net_peerCount
        """
        response = self.make_request("net_peerCount", [])
        return int(response['result'], 16)

    def is_syncing(self):
        """
        https://github.com/ethereum/wiki/wiki/JSON-RPC#eth_syncing
        """
        response = self.make_request("eth_syncing", [])
        result = response['result']
        return bool(result)

    def get_transaction_count(self, address):
        """
        https://github.com/ethereum/wiki/wiki/JSON-RPC#eth_gettransactioncount
        """
        response = self.make_request("eth_getTransactionCount", [address, "pending"])
        return int(response['result'], 16)

    def send_raw_transaction(self, data):
        response = self.make_request("eth_sendRawTransaction", [data])
        return response['result']

    def send(self, transaction):
        return self.send_raw_transaction(rlp.encode(transaction).encode('hex'))