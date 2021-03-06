from ipaddress import ip_address, ip_network
from concurrent.futures import ThreadPoolExecutor
from itertools import repeat
from collections import defaultdict, OrderedDict
import copy
import csv

from netmiko import ConnectHandler

from ..database.database import DataBase


class InvalidIPError(Exception):
    pass


class TrackHost:
    def __init__(self):
        """
        initializes all the instance variables to there default values/
        """
        self.db = DataBase("mysql://root:mysql@db/inventory_db")
        self._arp_tables = {}
        # to store the arp table of all the routers in the network
        self._mac_address_tables = defaultdict(list)
        # to store the mac address to port bindings of all the mac
        # address in the network
        self.error_logs = []
        self.username = "admin"
        self.password = "cisco"

    @staticmethod
    def check_if_ip_address(ip):
        """
        checks if the string provided is an ip address
        :param ip: string
        :return: boolean : True if the str is ip address otherwise False
        """
        try:
            ip_address(ip)
        except Exception:
            return False
        else:
            return True

    def _get_devices(self, host):
        self.db.connect()
        if not self.check_if_ip_address(host):
            hosts = self.db.select_groups(host, "both")
            self.db.disconnect()
            for host in hosts:
                device_data = dict(host)
                device_data.update(
                    ip=device_data["address"],
                    username=self.username,
                    password=self.password,
                )
                device_data.pop("address")
                yield device_data
        else:
            host = self.db.select_one(host)
            self.db.disconnect()
            if host:
                device_data = dict(host)
                device_data.update(
                    ip=device_data["address"],
                    username=self.username,
                    password=self.password,
                )
                device_data.pop("address")
                yield device_data
            else:
                raise KeyError("Host not found")

    @staticmethod
    def netmiko_device_data_parser(device_params):
        """
        Parses individual device params and return only netmiko specific dictionary
        :param device_params: dict: dict of device params
        :return: dict: dict of device params for netmiko connection
        """
        device_dict = {}

        device_dict.update(host=device_params.get("ip"))
        device_dict.update(device_type=device_params.get("device_type"))
        device_dict.update(username=device_params.get("username"))
        device_dict.update(password=device_params.get("password"))

        return device_dict

    def _netmiko_connect_and_run(self, device_params, commands, text_fsm=True):
        """
        to connect to network device using netmiko and run show commands
        :param text_fsm: if to use text_fsm or not
        :param device_params: dict: inventory device params
        :param commands: list: commands to be run on the host
        :return: list of command outputs from the device
        """
        output = []
        # if the device in the inventory is not accessible return a empty list for its data
        try:
            ssh = ConnectHandler(**self.netmiko_device_data_parser(device_params))

            for command in commands:
                output.append(ssh.send_command(command, use_textfsm=text_fsm))

        except Exception:
            self.error_logs.append(
                f"ERROR: Unable to connect to device {device_params['ip']}, this device will be skipped"
            )
            output = []  # empty list
        else:
            ssh.disconnect()

        return output

    def _manipulating_arp_data(self, result):
        """
        to manipulate raw arp data from network devices and save it in the form of
        dict of ip to mac binding in self.arp_tables object variable
        :param result: raw arp data
        :return: None
        """
        for device_arp_data in result:
            if device_arp_data:
                # to check if the arp data list is empty for a device which could mean that the
                # device is not accessible
                for arp_entry in device_arp_data[0]:
                    self._arp_tables.update({arp_entry["address"]: arp_entry["mac"]})

    def _manipulating_mac_data(self, switch_list, switch_data):
        """
        to manipulate raw mac table data and int status table data and save it in the form of
        dict of mac address to list of (switch, port, port_type) in variable self.mac_address_tables
        :param switch_list: switch params list
        :param switch_data: associated mac address table output
        :return: None
        """
        for data, switch_params in zip(switch_data, switch_list):
            if data:
                # to check if the data list for a device is empty or not which could mean that the device
                # was not accessible
                int_dict = {}
                for int_entry in data[1]:
                    int_dict.update({int_entry["port"]: int_entry["vlan"]})

                for mac_entry in data[0]:
                    port_type = (
                        "trunk"
                        if int_dict[mac_entry["destination_port"]] == "trunk"
                        else "access"
                    )
                    foo_dict = OrderedDict(
                        switch=switch_params["ip"],
                        port=mac_entry["destination_port"],
                        port_type=port_type,
                    )
                    self._mac_address_tables[mac_entry["destination_address"]].append(
                        OrderedDict(foo_dict)
                    )

    def _network_data_collection(self):
        """
        To connect to the devices in the network and collect relevant data for processing
        :return: None
        """
        self.error_logs.clear()
        router_list = list(self._get_devices("router"))
        with ThreadPoolExecutor(max_workers=5) as executor:
            result = executor.map(
                self._netmiko_connect_and_run, router_list, repeat(["show ip arp"])
            )
            # to manipulate the collected arp data in desired form for further processing
            self._manipulating_arp_data(result)

        switch_list = list(self._get_devices("switch"))
        with ThreadPoolExecutor(max_workers=10) as executor:
            result = executor.map(
                self._netmiko_connect_and_run,
                switch_list,
                repeat(["show mac address-table", "show int status"]),
            )
            # to manipulate the collected mac and interface data in desired form for further processing
            self._manipulating_mac_data(switch_list, result)

    @staticmethod
    def print_data(tracking_data):
        """
        to print host interface data in table form
        :return: None
        """
        table_print_data = []
        for ip, data in tracking_data.items():
            for interface in data["interfaces"]:
                print_dict = {
                    "IP": ip,
                    "MAC": data["mac_address"],
                }
                print_dict.update(interface)
                table_print_data.append(print_dict)

        return table_print_data

    @staticmethod
    def _export_to_csv(tracking_data):
        """
        To export the tracking data to tracking_data.csv file
        :param tracking_data: the data to be printed
        :return: None
        """
        csv_print_data = []
        for ip, data in tracking_data.items():
            for interface in data["interfaces"]:
                print_dict = {
                    "IP": ip,
                    "MAC": data["mac_address"],
                }
                print_dict.update(interface)
                csv_print_data.append(print_dict)

        with open("static/report.csv", "w") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=list(csv_print_data[0].keys()),
                quoting=csv.QUOTE_NONNUMERIC,
            )
            writer.writeheader()
            for d in csv_print_data:
                writer.writerow(d)

    def _netmiko_run_show(self, interface_data, commands):

        switch, interfaces = interface_data
        interface_list = list(interfaces)
        command_list = [
            command.replace("{}", inter)
            for inter in interface_list
            for command in commands
        ]

        device_data = list(self._get_devices("switch"))
        output = self._netmiko_connect_and_run(
            device_data[0], command_list, text_fsm=False
        )

        len_of_commands = len(commands)
        interface_output = [
            output[i: i + len_of_commands]
            for i in range(0, len(interface_list) * len_of_commands, len_of_commands)
        ]

        interface_dict = {
            inter: output for inter, output in zip(interface_list, interface_output)
        }

        return switch, interface_dict

    def _command_and_print(self, tracking_data, commands):
        """
        to run commands on host specific interfaces and display the data in table format
        :param tracking_data: tracking data of hosts
        :param commands: commands to run on the interfaces
        :return: None
        """
        switches_of_interest = defaultdict(set)
        for ip, data in tracking_data.items():
            for interface in data["interfaces"]:
                if interface["switch"]:
                    switches_of_interest[interface.get("switch")].add(
                        interface.get("port")
                    )

        with ThreadPoolExecutor(max_workers=20) as executor:
            result = list(
                executor.map(
                    self._netmiko_run_show,
                    switches_of_interest.items(),
                    repeat(commands),
                )
            )

        result_dict = {switch: interfaces for switch, interfaces in result}

        for ip, data in tracking_data.items():
            for interface in data["interfaces"]:
                if interface["switch"]:
                    interface["show commands"] = "\n".join(
                        result_dict[interface["switch"]].get(interface["port"])
                    )
                else:
                    interface["show commands"] = "NA"

        return tracking_data

    def track(self, hosts, port_type="access"):
        """
        To check if a particular IP has its mac resolved and collect all the access interfaces
        where this mac address is being learnt
        saves the data in the form of a dictionary where the dictionary is
        { ip:
          { mac_address: 'address',
            interfaces: [
            { switch: 'ip',
              port: 'portid',
              port_type: 'port_type'}
            ]
          }
        }
        and assigns it object variable self.host_access_ports
        :return: None
        """
        host_access_ports = {}

        if not all(map(self.check_if_ip_address, hosts)):
            raise InvalidIPError("Invalid IP entered")

        # for every host
        for host in hosts:
            host_interfaces = []
            mac_mapping = copy.deepcopy(self._mac_address_tables)

            # check if arp entry is resolved
            host_mac = self._arp_tables.get(host, None)

            # if arp entry is resolved check the ports, access or trunk on which the mac is learnt
            if host_mac:
                host_interfaces = mac_mapping.get(host_mac, [])

            # extract access ports from the list of ports
            if port_type == "access":
                host_interface_list = list(
                    filter(lambda x: x["port_type"] == "access", host_interfaces)
                )
            elif port_type == "trunk":
                host_interface_list = list(
                    filter(lambda x: x["port_type"] == "trunk", host_interfaces)
                )
            else:
                host_interface_list = host_interfaces

            if not host_interface_list:
                host_interface_list = [
                    OrderedDict(switch=None, port=None, port_type=None)
                ]
            host_dict = {
                host: {"mac_address": host_mac, "interfaces": host_interface_list}
            }

            host_access_ports.update(host_dict)
        return host_access_ports

    def track_and_print(self, hosts, export=False, port_type="access"):
        """
        to track the list of IP the user will provide and display the information on the terminal
        :param export: to export result to csv
        :param hosts: list of IP address to be tracked
        :param port_type: default is access port however you can also use trunk or all ( both access and trunk ports )
        :return: None, print the tracking information in table format
        """
        tracking_data = self.track(hosts, port_type)
        if export:
            self._export_to_csv(tracking_data)

        return self.print_data(tracking_data)

    def track_command_print(self, hosts, commands, export=False, port_type="access"):
        """
        to track the list of IP the user will provide and run the list of show commands against those ports and display
        the information on the terminal in table format
        :param export: to export result to csv
        :param hosts: list of IP addresses to be tracked
        :param commands: list of show commands to run, use '{}' to place the port id in the command.
        :param port_type: default is access port however you can also use trunk or all ( both access and trunk ports )
        :return: None, print the tracking information in table format
        """
        tracking_data = self.track(hosts, port_type)
        tracking_data_command = self._command_and_print(tracking_data, commands)
        if export:
            self._export_to_csv(tracking_data_command)

        return self.print_data(tracking_data_command)

    def track_subnet(self, subnet, export, port_type, excluded):
        """
        to track a particular subnet IPs on the network
        :param export:
        :param subnet: ip subnet to be tracked in format x.x.x.x/y
        :param port_type: type of port to be searched for, default is access
        :param excluded: ips to be excluded from the search
        :return: None
        """
        subnetrange = ip_network(subnet)
        ips = list(map(str, subnetrange.hosts()))

        if excluded and not all(map(self.check_if_ip_address, excluded)):
            raise InvalidIPError("Invalid IP entered")

        ipsofinterset = [ip for ip in ips if ip not in excluded]

        data = self.track_and_print(ipsofinterset, export, port_type)
        returndata = [foo for foo in data if foo["MAC"]]

        return returndata

    def load(self):
        """
        Connects to all the devices in the network and loads all the necessary data to track end hosts.
        example: arp table from devices in the router group and mac address table from devices in the switch group.
        :return: None
        """
        self._network_data_collection()  # to connect to the network devices and load all the data.
        return self.error_logs
