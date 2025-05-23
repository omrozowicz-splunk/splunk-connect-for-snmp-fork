#
# Copyright 2021 Splunk Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
import re
from contextlib import suppress

from pysnmp.smi.error import SmiError

from splunk_connect_for_snmp.snmp.exceptions import SnmpActionError

with suppress(ImportError, OSError):
    from dotenv import load_dotenv

    load_dotenv()

import os
import socket
import time

import pymongo
from celery import shared_task
from celery.utils.log import get_task_logger
from mongolock import MongoLock, MongoLockLocked
from pysnmp.smi.rfc1902 import ObjectIdentity, ObjectType

from splunk_connect_for_snmp.common.custom_cache import ttl_lru_cache
from splunk_connect_for_snmp.common.hummanbool import human_bool
from splunk_connect_for_snmp.snmp.manager import Poller, get_inventory

logger = get_task_logger(__name__)

MONGO_URI = os.getenv("MONGO_URI")
MONGO_DB = os.getenv("MONGO_DB", "sc4snmp")
CONFIG_PATH = os.getenv("CONFIG_PATH", "/app/config/config.yaml")
WALK_RETRY_MAX_INTERVAL = int(os.getenv("WALK_RETRY_MAX_INTERVAL", "180"))
WALK_MAX_RETRIES = int(os.getenv("WALK_MAX_RETRIES", "5"))
SPLUNK_SOURCETYPE_TRAPS = os.getenv("SPLUNK_SOURCETYPE_TRAPS", "sc4snmp:traps")
OID_VALIDATOR = re.compile(r"^([0-2])((\.0)|(\.[1-9]\d*))*$")
RESOLVE_TRAP_ADDRESS = os.getenv("RESOLVE_TRAP_ADDRESS", "false")
MAX_DNS_CACHE_SIZE_TRAPS = int(os.getenv("MAX_DNS_CACHE_SIZE_TRAPS", "100"))
TTL_DNS_CACHE_TRAPS = int(os.getenv("TTL_DNS_CACHE_TRAPS", "1800"))
IPv6_ENABLED = human_bool(os.getenv("IPv6_ENABLED", "false").lower())


@shared_task(
    bind=True,
    base=Poller,
    retry_backoff=30,
    retry_backoff_max=WALK_RETRY_MAX_INTERVAL,
    max_retries=WALK_MAX_RETRIES,
    autoretry_for=(
        MongoLockLocked,
        SnmpActionError,
    ),
    throws=(
        SnmpActionError,
        SnmpActionError,
    ),
)
def walk(self, **kwargs):
    address = kwargs["address"]
    profile = kwargs.get("profile", [])
    group = kwargs.get("group")
    chain_of_tasks_expiry_time = kwargs.get("chain_of_tasks_expiry_time")
    if profile:
        profile = [profile]
    mongo_client = pymongo.MongoClient(MONGO_URI)
    mongo_db = mongo_client[MONGO_DB]
    mongo_inventory = mongo_db.inventory

    ir = get_inventory(mongo_inventory, address)
    retry = True
    while retry:
        retry, result = self.do_work(ir, walk=True, profiles=profile)

    # After a Walk tell schedule to recalc
    work = {
        "time": time.time(),
        "address": address,
        "result": result,
        "chain_of_tasks_expiry_time": chain_of_tasks_expiry_time,
    }
    if group:
        work["group"] = group

    return work


@shared_task(
    bind=True,
    base=Poller,
    default_retry_delay=5,
    max_retries=3,
    retry_backoff=True,
    retry_backoff_max=1,
    retry_jitter=True,
    expires=30,
)
def poll(self, **kwargs):

    address = kwargs["address"]
    profiles = kwargs["profiles"]
    group = kwargs.get("group")
    mongo_client = pymongo.MongoClient(MONGO_URI)
    mongo_db = mongo_client[MONGO_DB]
    mongo_inventory = mongo_db.inventory

    ir = get_inventory(mongo_inventory, address)
    _, result = self.do_work(ir, profiles=profiles)

    # After a Walk tell schedule to recalc
    work = {
        "time": time.time(),
        "address": address,
        "result": result,
        "detectchange": False,
        "frequency": kwargs["frequency"],
    }
    if group:
        work["group"] = group

    return work


@ttl_lru_cache(maxsize=MAX_DNS_CACHE_SIZE_TRAPS, ttl=TTL_DNS_CACHE_TRAPS)
def resolve_address(address: str):
    try:
        dns_result = socket.gethostbyaddr(address)
        result = dns_result[0]
    except socket.herror:
        logger.info(f"Traps: address {address} can't be resolved.")
        result = address
    return result


@shared_task(bind=True, base=Poller)
def trap(self, work):
    varbind_table, not_translated_oids, remaining_oids, remotemibs = [], [], [], set()
    metrics = {}
    work["host"] = format_ipv4_address(work["host"])

    _process_work_data(self, work, varbind_table, not_translated_oids)
    _process_remaining_oids(
        self,
        not_translated_oids,
        remotemibs,
        remaining_oids,
        work["host"],
        varbind_table,
    )
    _, _, result = self.process_snmp_data(varbind_table, metrics, work["host"])
    if human_bool(RESOLVE_TRAP_ADDRESS):
        work["host"] = resolve_address(work["host"])

    return _build_result(result, work["host"])


def _process_work_data(self, work, varbind_table, not_translated_oids):
    """Process the data in work to populate varbinds."""
    for w in work["data"]:
        if OID_VALIDATOR.match(w[1]):
            _load_mib_if_needed(self, w[1], work["host"])

        try:
            varbind_table.append(
                ObjectType(ObjectIdentity(w[0]), w[1]).resolveWithMib(
                    self.mib_view_controller
                )
            )
        except SmiError:
            not_translated_oids.append((w[0], w[1]))


def _load_mib_if_needed(self, oid, host):
    """Load the MIB if it is known and not already loaded."""
    with suppress(Exception):
        found, mib = self.is_mib_known(oid, oid, host)
        if found and mib not in self.already_loaded_mibs:
            self.load_mibs([mib])
            self.already_loaded_mibs.add(mib)


def _process_remaining_oids(
    self, not_translated_oids, remotemibs, remaining_oids, host, varbind_table
):
    """Process OIDs that could not be translated and add them to other oids."""
    for oid in not_translated_oids:
        found, mib = self.is_mib_known(oid[0], oid[0], host)
        if found and mib not in self.already_loaded_mibs:
            remotemibs.add(mib)
            remaining_oids.append((oid[0], oid[1]))

    if remotemibs:
        self.load_mibs(remotemibs)
        self.already_loaded_mibs.update(remotemibs)
        _resolve_remaining_oids(self, remaining_oids, varbind_table)


def _resolve_remaining_oids(self, remaining_oids, varbind_table):
    """Resolve remaining OIDs."""
    for w in remaining_oids:
        try:
            varbind_table.append(
                ObjectType(ObjectIdentity(w[0]), w[1]).resolveWithMib(
                    self.mib_view_controller
                )
            )
        except SmiError:
            logger.warning(f"No translation found for {w[0]}")


def _build_result(result, host):
    """Build the final result dictionary."""
    return {
        "time": time.time(),
        "result": result,
        "address": host,
        "detectchange": False,
        "sourcetype": SPLUNK_SOURCETYPE_TRAPS,
    }


def format_ipv4_address(host: str) -> str:
    # IPv4 addresses from IPv6 socket have added ::ffff: prefix, which is removed
    if IPv6_ENABLED and "." in host:
        return host.split(":")[-1]
    return host
