#!/bin/bash
while [ "$(microk8s kubectl get pods -n sc4snmp | grep splunk-connect-for-snmp-inventory | wc -l )" = "1" ] ; do
    echo "Waiting for inventory pod to die..."
    sleep 1
done
EOF