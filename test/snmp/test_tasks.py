from unittest import TestCase
from unittest.mock import MagicMock, patch

from pysnmp.smi.error import SmiError


@patch("pymongo.MongoClient")
class TestTasks(TestCase):
    @patch("splunk_connect_for_snmp.snmp.manager.get_inventory")
    @patch("splunk_connect_for_snmp.snmp.manager.Poller.__init__")
    @patch("splunk_connect_for_snmp.snmp.manager.Poller.do_work")
    @patch("time.time")
    def test_walk(
        self,
        m_time,
        m_do_work,
        m_poller,
        m_get_inventory,
        m_mongo_client,
    ):
        m_poller.return_value = None
        from splunk_connect_for_snmp.snmp.tasks import poll

        m_mongo_client.return_value = MagicMock()
        m_time.return_value = 1640692955.365186

        kwargs = {"address": "192.168.0.1", "profiles": ["profile1"], "frequency": 70}
        m_do_work.return_value = (False, {"test": "value1"})

        result = poll(**kwargs)

        self.assertEqual(
            {
                "time": 1640692955.365186,
                "address": "192.168.0.1",
                "result": {"test": "value1"},
                "frequency": 70,
                "detectchange": False,
            },
            result,
        )

    @patch("splunk_connect_for_snmp.snmp.manager.get_inventory")
    @patch("splunk_connect_for_snmp.snmp.manager.Poller.__init__")
    @patch("splunk_connect_for_snmp.snmp.manager.Poller.do_work")
    @patch("time.time")
    def test_poll_with_group(
        self,
        m_time,
        m_do_work,
        m_poller,
        m_get_inventory,
        m_mongo_client,
    ):
        m_poller.return_value = None
        from splunk_connect_for_snmp.snmp.tasks import poll

        m_time.return_value = 1640692955.365186

        kwargs = {
            "address": "192.168.0.1",
            "profiles": ["profile1"],
            "frequency": 70,
            "group": "group1",
        }
        m_do_work.return_value = (False, {"test": "value1"})

        result = poll(**kwargs)

        self.assertEqual(
            {
                "time": 1640692955.365186,
                "address": "192.168.0.1",
                "result": {"test": "value1"},
                "frequency": 70,
                "group": "group1",
                "detectchange": False,
            },
            result,
        )

    @patch("splunk_connect_for_snmp.snmp.manager.get_inventory")
    @patch("splunk_connect_for_snmp.snmp.manager.Poller.__init__")
    @patch("splunk_connect_for_snmp.snmp.manager.Poller.do_work")
    @patch("time.time")
    def test_walk_with_group(
        self,
        m_time,
        m_do_work,
        m_poller,
        m_get_inventory,
        m_mongo_client,
    ):
        m_poller.return_value = None
        from splunk_connect_for_snmp.snmp.tasks import walk

        m_mongo_client.return_value = MagicMock()
        m_time.return_value = 1640692955.365186

        kwargs = {
            "address": "192.168.0.1",
            "group": "group1",
            "chain_of_tasks_expiry_time": 120,
        }
        m_do_work.return_value = (False, {"test": "value1"})

        result = walk(**kwargs)

        self.assertEqual(
            {
                "time": 1640692955.365186,
                "address": "192.168.0.1",
                "group": "group1",
                "result": {"test": "value1"},
                "chain_of_tasks_expiry_time": 120,
            },
            result,
        )

    @patch("pysnmp.smi.rfc1902.ObjectType.resolveWithMib")
    @patch("splunk_connect_for_snmp.snmp.manager.Poller.process_snmp_data")
    @patch("splunk_connect_for_snmp.snmp.manager.Poller.__init__")
    @patch("time.time")
    def test_trap(
        self,
        m_time,
        m_poller,
        m_process_data,
        m_resolved,
        m_mongo_client,
    ):
        m_poller.return_value = None
        from splunk_connect_for_snmp.snmp.tasks import trap

        m_time.return_value = 1640692955.365186

        m_resolved.return_value = None

        work = {"data": [("asd", "tre")], "host": "192.168.0.1"}
        m_process_data.return_value = (False, [], {"test": "value1"})
        m_poller.builder = MagicMock()
        m_poller.trap = trap
        m_poller.trap.mib_view_controller = MagicMock()
        result = trap(work)

        self.assertEqual(
            {
                "address": "192.168.0.1",
                "detectchange": False,
                "result": {"test": "value1"},
                "sourcetype": "sc4snmp:traps",
                "time": 1640692955.365186,
            },
            result,
        )

    @patch("pysnmp.smi.rfc1902.ObjectType.resolveWithMib")
    @patch("splunk_connect_for_snmp.snmp.manager.Poller.process_snmp_data")
    @patch("splunk_connect_for_snmp.snmp.manager.Poller.is_mib_known")
    @patch("splunk_connect_for_snmp.snmp.manager.Poller.load_mibs")
    @patch("splunk_connect_for_snmp.snmp.manager.Poller.__init__")
    @patch("time.time")
    def test_trap_retry_translation(
        self,
        m_time,
        m_poller,
        m_load_mib,
        m_is_mib_known,
        m_process_data,
        m_resolved,
        m_mongo_client,
    ):
        m_poller.return_value = None
        from splunk_connect_for_snmp.snmp.tasks import trap

        m_time.return_value = 1640692955.365186

        m_resolved.side_effect = [SmiError, "TEST1"]
        m_is_mib_known.return_value = (True, "SOME-MIB")
        work = {"data": [("asd", "tre")], "host": "192.168.0.1"}
        m_process_data.return_value = (False, [], {"test": "value1"})
        m_poller.trap = trap
        m_poller.trap.mib_view_controller = MagicMock()
        m_poller.trap.already_loaded_mibs = set()
        result = trap(work)

        calls = m_load_mib.call_args_list
        self.assertEqual({"SOME-MIB"}, calls[0][0][0])

        process_calls = m_process_data.call_args_list
        self.assertEqual(["TEST1"], process_calls[0][0][0])

        self.assertEqual(
            {
                "address": "192.168.0.1",
                "detectchange": False,
                "result": {"test": "value1"},
                "sourcetype": "sc4snmp:traps",
                "time": 1640692955.365186,
            },
            result,
        )

    @patch("pysnmp.smi.rfc1902.ObjectType.resolveWithMib")
    @patch("splunk_connect_for_snmp.snmp.manager.Poller.process_snmp_data")
    @patch("splunk_connect_for_snmp.snmp.manager.Poller.is_mib_known")
    @patch("splunk_connect_for_snmp.snmp.manager.Poller.load_mibs")
    @patch("splunk_connect_for_snmp.snmp.manager.Poller.__init__")
    @patch("time.time")
    def test_trap_retry_translation_failed(
        self,
        m_time,
        m_poller,
        m_load_mib,
        m_is_mib_known,
        m_process_data,
        m_resolved,
        m_mongo_client,
    ):
        m_poller.return_value = None
        from splunk_connect_for_snmp.snmp.tasks import trap

        m_time.return_value = 1640692955.365186

        m_resolved.side_effect = [SmiError, SmiError]
        m_is_mib_known.return_value = (True, "SOME-MIB")

        work = {"data": [("asd", "tre")], "host": "192.168.0.1"}
        m_process_data.return_value = (False, [], {"test": "value1"})
        m_poller.trap = trap
        m_poller.trap.mib_view_controller = MagicMock()
        m_poller.trap.already_loaded_mibs = set()
        result = trap(work)

        calls = m_load_mib.call_args_list

        process_calls = m_process_data.call_args_list
        self.assertEqual([], process_calls[0][0][0])

        self.assertEqual({"SOME-MIB"}, calls[0][0][0])
        self.assertEqual(
            {
                "address": "192.168.0.1",
                "detectchange": False,
                "result": {"test": "value1"},
                "sourcetype": "sc4snmp:traps",
                "time": 1640692955.365186,
            },
            result,
        )

    @patch("splunk_connect_for_snmp.snmp.tasks.RESOLVE_TRAP_ADDRESS", "true")
    @patch("splunk_connect_for_snmp.snmp.tasks.resolve_address")
    @patch("pysnmp.smi.rfc1902.ObjectType.resolveWithMib")
    @patch("splunk_connect_for_snmp.snmp.manager.Poller.process_snmp_data")
    @patch("splunk_connect_for_snmp.snmp.manager.Poller.__init__")
    @patch("time.time")
    def test_trap_reverse_dns_lookup(
        self,
        m_time,
        m_poller,
        m_process_data,
        m_resolved,
        m_resolve_address,
        m_mongo_client,
    ):
        m_poller.return_value = None
        from splunk_connect_for_snmp.snmp.tasks import trap

        m_time.return_value = 1640692955.365186

        m_resolved.return_value = None
        m_resolve_address.return_value = "my.host"

        work = {"data": [("asd", "tre")], "host": "192.168.0.1"}
        m_process_data.return_value = (False, [], {"test": "value1"})
        m_poller.builder = MagicMock()
        m_poller.trap = trap
        m_poller.trap.mib_view_controller = MagicMock()
        result = trap(work)

        self.assertEqual(
            {
                "address": "my.host",
                "detectchange": False,
                "result": {"test": "value1"},
                "sourcetype": "sc4snmp:traps",
                "time": 1640692955.365186,
            },
            result,
        )


class TestHelpers(TestCase):
    @patch("splunk_connect_for_snmp.snmp.tasks.IPv6_ENABLED")
    def test_format_ipv4_address(self, ipv6_enabled):
        from splunk_connect_for_snmp.snmp.tasks import format_ipv4_address

        ipv6_enabled.return_value = True
        ip_address = "::ffff:172.31.20.76"
        host = format_ipv4_address(ip_address)
        self.assertEqual(host, "172.31.20.76")

    def test_format_ipv4_address_disabled(self):
        from splunk_connect_for_snmp.snmp.tasks import format_ipv4_address

        ip_address = "::ffff:172.31.20.76"
        host = format_ipv4_address(ip_address)
        self.assertEqual(host, "::ffff:172.31.20.76")

    def test_format_ipv4_address_ipv6(self):
        from splunk_connect_for_snmp.snmp.tasks import format_ipv4_address

        ip_address = "fd02::b24a:409e:a35e:b580"
        host = format_ipv4_address(ip_address)
        self.assertEqual(host, "fd02::b24a:409e:a35e:b580")
