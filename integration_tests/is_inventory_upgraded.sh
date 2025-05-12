#!/bin/bash
while [ "$(sudo microk8s kubectl get job -n sc4snmp | grep Complete | wc -l)" != "1" ]; do
    echo "Waiting for inventory upgrade to finish..."
    sleep 1
done